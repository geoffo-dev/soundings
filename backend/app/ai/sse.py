"""Live run progress over server-sent events (contract-phase6 section 3.6).

``GET /ideas/{idea}/ai-runs/{run_id}/events`` (``idea.view``): problems (401, 404, 422,
429) come as problem+json before any stream byte; a run that is over when the client
already has every event gets **204** (EventSource stops reconnecting). Otherwise a
``text/event-stream``: ``retry: 3000`` first, then every event after ``Last-Event-ID``
(or ``?after=``; the header wins) as ``id: <seq>`` + ``data: <AiRunEvent JSON>`` (no
``event:`` field), then new ones as they are written, ``: keep-alive`` every 15 s. The
stream ends after the final event, after 10 minutes (the browser reconnects with
``Last-Event-ID``), or when the 30-second re-check finds the session or key gone or
``idea.view`` lost (the reconnect then gets the 401 / 404).

**One poller per run per API process** (:class:`RunEventHub`) reads ``ai_run_events``
once a second in a short session of its own and fans new events out to every open
stream of that run here; no ``LISTEN/NOTIFY`` and no request session (the request's is
closed before streaming starts). At most 5 open streams per person per process.

**Blind safety by construction:** a stream carries :class:`~app.schemas.ai.AiRunEvent`
only (Soundings' fixed sentences), so pending evaluators may watch an AI evaluation.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections import Counter
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any, Final
from uuid import UUID

from fastapi import Request
from sqlalchemy import select
from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from app.api_keys.verify import reload_api_key
from app.auth.cookies import SESSION_COOKIE, read_cookie
from app.db import SessionMaker
from app.domain.principal import Principal
from app.errors import ProblemError
from app.models.ai import AiRun, AiRunEvent
from app.models.enums import AuthMethod
from app.observability import AI_RUN_EVENT_STREAMS
from app.schemas.ai import (
    AI_SSE_HEARTBEAT,
    AI_SSE_MAX_DURATION,
    AI_SSE_RECHECK,
    AI_SSE_RETRY_MS,
    AI_SSE_STREAMS_PER_USER,
)
from app.schemas.ai import AiRunEvent as AiRunEventOut
from app.services import sessions

__all__ = [
    "EVENT_STREAM_HEADERS",
    "EventStreamResponse",
    "RunEventHub",
    "TooManyStreamsProblem",
    "event_stream",
    "frame",
    "get_hub",
]

logger = logging.getLogger("soundings.ai")

EVENT_STREAM_HEADERS: Final = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}
POLL_INTERVAL: Final = 1.0
_HUB: Final = "ai_event_hub"


class TooManyStreamsProblem(ProblemError):
    def __init__(self) -> None:
        super().__init__(
            429,
            "too_many_attempts",
            detail=f"You have {AI_SSE_STREAMS_PER_USER} AI run streams open. Close one first.",
            headers={"Retry-After": "5"},
        )


def frame(event: AiRunEventOut) -> bytes:
    """One SSE message: ``id`` = ``seq``, ``data`` = the event as JSON (one line)."""
    return f"id: {event.seq}\ndata: {event.model_dump_json()}\n\n".encode()


def _event_out(row: AiRunEvent) -> AiRunEventOut:
    return AiRunEventOut(seq=row.seq, type=row.type, message=row.message, created_at=row.created_at)


async def read_events(sessionmaker: SessionMaker, run_id: UUID, after: int) -> list[AiRunEventOut]:
    async with sessionmaker() as db:
        rows = await db.scalars(
            select(AiRunEvent)
            .where(AiRunEvent.run_id == run_id, AiRunEvent.seq > after)
            .order_by(AiRunEvent.seq)
        )
        return [_event_out(row) for row in rows]


# --- The hub ---------------------------------------------------------------------------------
@dataclass(slots=True)
class _Feed:
    last: int = 0
    queues: set[asyncio.Queue[AiRunEventOut]] = field(default_factory=set)
    task: asyncio.Task[None] | None = None


class RunEventHub:
    """One poller per run with open streams in this process, and the per-person count."""

    def __init__(self, sessionmaker: SessionMaker, *, interval: float = POLL_INTERVAL) -> None:
        self._sessionmaker = sessionmaker
        self._interval = interval
        self._feeds: dict[UUID, _Feed] = {}
        self._streams: Counter[UUID] = Counter()

    def open_stream(self, user_id: UUID) -> None:
        """Count a new stream for ``user_id`` (429 past the limit)."""
        if self._streams[user_id] >= AI_SSE_STREAMS_PER_USER:
            raise TooManyStreamsProblem
        self._streams[user_id] += 1
        AI_RUN_EVENT_STREAMS.inc()

    def close_stream(self, user_id: UUID) -> None:
        if self._streams[user_id] > 0:
            self._streams[user_id] -= 1
            AI_RUN_EVENT_STREAMS.dec()
        if self._streams[user_id] <= 0:
            del self._streams[user_id]

    def open_streams(self, user_id: UUID) -> int:
        return self._streams.get(user_id, 0)

    def subscribe(self, run_id: UUID, after: int) -> asyncio.Queue[AiRunEventOut]:
        """A queue that gets the run's new events (seq > the poller's position, which
        starts at ``after`` for a new poller; subscribers drop what they already have)."""
        feed = self._feeds.get(run_id)
        if feed is None:
            feed = self._feeds[run_id] = _Feed(last=after)
        queue: asyncio.Queue[AiRunEventOut] = asyncio.Queue()
        feed.queues.add(queue)
        if feed.task is None or feed.task.done():
            feed.task = asyncio.create_task(self._poll(run_id, feed), name=f"ai-events-{run_id}")
        return queue

    def unsubscribe(self, run_id: UUID, queue: asyncio.Queue[AiRunEventOut]) -> None:
        feed = self._feeds.get(run_id)
        if feed is None:
            return
        feed.queues.discard(queue)
        if not feed.queues:
            if feed.task is not None:
                feed.task.cancel()
            del self._feeds[run_id]

    async def _poll(self, run_id: UUID, feed: _Feed) -> None:
        while feed.queues:
            try:
                events = await read_events(self._sessionmaker, run_id, feed.last)
            except Exception:  # the next poll tries again
                logger.exception("ai run event poll failed", extra={"run_id": str(run_id)})
                events = []
            for event in events:
                feed.last = event.seq
                for queue in feed.queues:
                    queue.put_nowait(event)
            await asyncio.sleep(self._interval)

    async def close(self) -> None:
        tasks = [feed.task for feed in self._feeds.values() if feed.task is not None]
        self._feeds.clear()
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(BaseException):
                await task


def get_hub(app: Any) -> RunEventHub:
    hub = getattr(app.state, _HUB, None)
    if not isinstance(hub, RunEventHub):
        hub = RunEventHub(app.state.sessionmaker)
        setattr(app.state, _HUB, hub)
    return hub


# --- One stream ------------------------------------------------------------------------------
async def still_allowed(
    app: Any, request: Request, principal: Principal, idea_id: UUID, run_id: UUID
) -> bool:
    """The 30-second re-check: the session (not kept alive) or the key is still valid,
    and its user may still view the idea, whose run this still is."""
    from app.services.ideas import load_idea

    settings = app.state.settings
    async with app.state.sessionmaker() as db:
        live: Principal | None = None
        if principal.auth == "api_key" and principal.api_key_id is not None:
            live = (await reload_api_key(db, principal.api_key_id, settings=settings)).principal
        else:
            token = read_cookie(request, settings, SESSION_COOKIE)
            found = (
                await sessions.resolve_session(db, token, settings=settings, touch=False)
                if token
                else None
            )
            if found is not None and found[1].id == principal.user_id:
                row, user = found
                live = Principal(
                    user=user,
                    auth="session",
                    session_id=row.id,
                    auth_method=AuthMethod(row.auth_method),
                )
        if live is None:
            return False
        try:
            await load_idea(db, live, str(idea_id))
        except ProblemError:
            return False
        found_run = await db.scalar(
            select(AiRun.id).where(AiRun.id == run_id, AiRun.idea_id == idea_id)
        )
        return found_run is not None


Recheck = Callable[[], Any]


async def event_stream(
    hub: RunEventHub,
    sessionmaker: SessionMaker,
    run_id: UUID,
    after: int,
    recheck: Recheck,
    *,
    heartbeat: float = AI_SSE_HEARTBEAT.total_seconds(),
    recheck_every: float = AI_SSE_RECHECK.total_seconds(),
    max_duration: float = AI_SSE_MAX_DURATION.total_seconds(),
) -> AsyncIterator[bytes]:
    """The body of one stream (see the module docstring)."""
    queue = hub.subscribe(run_id, after)
    try:
        yield f"retry: {AI_SSE_RETRY_MS}\n\n".encode()
        cursor = after
        for replayed in await read_events(sessionmaker, run_id, after):
            yield frame(replayed)
            cursor = replayed.seq
            if replayed.final:
                return
        started = time.monotonic()
        last_write = started
        next_check = started + recheck_every
        ends = started + max_duration
        while True:
            now = time.monotonic()
            wait = max(0.0, min(last_write + heartbeat, next_check, ends) - now)
            event: AiRunEventOut | None
            try:
                event = await asyncio.wait_for(queue.get(), wait)
            except TimeoutError:
                event = None
            if event is not None and event.seq > cursor:
                yield frame(event)
                cursor = event.seq
                last_write = time.monotonic()
                if event.final:
                    return
            now = time.monotonic()
            if now >= ends:
                return
            if now >= next_check:
                if not await recheck():
                    return
                next_check = now + recheck_every
            if now - last_write >= heartbeat:
                yield b": keep-alive\n\n"
                last_write = now
    finally:
        hub.unsubscribe(run_id, queue)


class EventStreamResponse(StreamingResponse):
    """``text/event-stream; charset=utf-8`` with :data:`EVENT_STREAM_HEADERS`; calls
    ``on_close`` when the response is done, however it ends (the per-person count)."""

    def __init__(self, content: AsyncIterator[bytes], *, on_close: Callable[[], None]) -> None:
        super().__init__(
            content, media_type="text/event-stream; charset=utf-8", headers=EVENT_STREAM_HEADERS
        )
        self._on_close = on_close

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            self._on_close()
