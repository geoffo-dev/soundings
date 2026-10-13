"""Text extraction of bid documents, on the worker (contract-phase10 section 6.3, ADR 0018
decision 5): never in the API process.

**One at a time per worker**: the ``bid_documents`` queue has a pool of its own in the
worker (:data:`app.worker.DOCUMENT_QUEUES`, concurrency
:data:`~app.schemas.bids.BID_EXTRACTIONS_PER_WORKER`), so a 30-second extraction never
holds up email, the schedules or AI runs.

**Each document in a fresh child process** (:func:`run_child`): ``python -I -B -m
app.bids.extract_child`` with an **allow-listed environment** (:data:`CHILD_ENVIRONMENT`:
no database URL, secret key or SMTP credentials; its own empty temporary folder as
``TMPDIR`` and ``HOME``, deleted afterwards), the bytes on **stdin**, one JSON object read
from **stdout** up to :func:`output_bound` (more: ``internal_error``), killed after
:data:`~app.schemas.bids.BID_EXTRACTION_TIMEOUT` (``timeout``). The child caps its own
address space (:data:`~app.schemas.bids.BID_EXTRACTION_MEMORY_BYTES`: ``memory``) and the
archive, XML and text bounds (:mod:`app.bids.extract_child`).

**Attempts** (:func:`extract_document`): each run is counted in
``bid_documents.extraction_attempts`` *before* the child starts (committed), so a child or
worker that dies mid-way still counts; a crashed child is tried again a little later; at
:data:`~app.schemas.bids.BID_EXTRACTION_MAX_ATTEMPTS` the document is ``failed``
``internal_error``, so one bad file can't crash-loop the worker. The minute sweep
(:func:`sweep_documents`) re-queues a pending document whose job was lost (a worker that
died: ``finish_stalled_jobs`` failed its job).

A failed extraction never refuses the document. When a bid's last pending document is
read, the call's AI assessor may start its automatic run (:mod:`app.bids.assess`).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import shutil
import signal
import sys
import tempfile
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Final
from uuid import UUID

from procrastinate.exceptions import AlreadyEnqueued
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionMaker, session_scope
from app.email.outbox import psycopg_connection
from app.models.base import utcnow
from app.models.bid import (
    BID_TEXT_MAX_CHARS,
    BidDocument,
    BidDocumentContent,
    BidDocumentText,
)
from app.models.enums import ExtractionError, ExtractionState
from app.schemas.bids import (
    BID_ARCHIVE_MAX_ENTRIES,
    BID_ARCHIVE_MAX_RATIO,
    BID_ARCHIVE_PART_MAX_BYTES,
    BID_ARCHIVE_TOTAL_MAX_BYTES,
    BID_EXTRACTION_MAX_ATTEMPTS,
    BID_EXTRACTION_MEMORY_BYTES,
    BID_EXTRACTION_TIMEOUT,
)
from app.worker import procrastinate_app

__all__ = [
    "BID_DOCUMENT_QUEUE",
    "CHILD_ENVIRONMENT",
    "CHILD_LIMITS",
    "EXTRACT_TASK",
    "ChildOutcome",
    "defer_extraction",
    "extract_document",
    "extract_in_session",
    "output_bound",
    "run_child",
    "sweep_documents",
]

logger = logging.getLogger("soundings.bids")

EXTRACT_TASK: Final = "extract_bid_document"
BID_DOCUMENT_QUEUE: Final = "bid_documents"
CHILD_MODULE: Final = "app.bids.extract_child"
RETRY_AFTER_CRASH: Final = timedelta(seconds=15)
"""A crashed extraction is tried again this much later (until its attempts run out)."""
SWEEP_AFTER: Final = timedelta(minutes=2)
"""The sweep re-queues a pending document without a job once it is this old."""
SWEEP_BATCH: Final = 100

CHILD_ENVIRONMENT: Final = frozenset({"PATH", "LANG", "LANGUAGE", "TZ"})
"""The worker's environment variables the child keeps (with ``LC_*``); everything else
(the database URL, the secret key, SMTP credentials, OIDC secrets) stays out."""

CHILD_LIMITS: Final[dict[str, int]] = {
    "max_chars": BID_TEXT_MAX_CHARS,
    "max_entries": BID_ARCHIVE_MAX_ENTRIES,
    "part_max_bytes": BID_ARCHIVE_PART_MAX_BYTES,
    "total_max_bytes": BID_ARCHIVE_TOTAL_MAX_BYTES,
    "max_ratio": BID_ARCHIVE_MAX_RATIO,
    "memory_bytes": BID_EXTRACTION_MEMORY_BYTES,
}
"""The bounds passed to the child (:class:`app.bids.extract_child.Limits`)."""


def output_bound(max_chars: int = BID_TEXT_MAX_CHARS) -> int:
    """The most the child may write: the text cap at UTF-8's 4 bytes a character (the
    child keeps only tab, line feed and carriage return of the control characters, which
    JSON escapes in 2 bytes), plus 64 KiB for the rest of the object."""
    return 4 * max_chars + 64 * 1024


async def defer_extraction(db: AsyncSession, document_id: UUID) -> None:
    """The ``extract_bid_document`` job on the session's connection (it exists when the
    upload commits, or never). Its queueing lock keeps one waiting job per document."""
    connection = await psycopg_connection(db)
    deferrer = procrastinate_app.configure_task(
        EXTRACT_TASK,
        connection=connection,
        queue=BID_DOCUMENT_QUEUE,
        queueing_lock=f"bid_document:{document_id}",
    )
    await deferrer.defer_async(document_id=str(document_id))


# --- The child -----------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ChildOutcome:
    """What a child run gave: a result (``state`` and the rest), or ``crashed`` (it died
    or wrote nothing valid: the attempt counts and it may be tried again)."""

    state: ExtractionState | None = None
    error: ExtractionError | None = None
    text: str = ""
    truncated: bool = False
    active_content: bool = False
    crashed: bool = False

    @classmethod
    def failed(cls, error: ExtractionError) -> ChildOutcome:
        return cls(state=ExtractionState.FAILED, error=error)


class _TooMuchOutput(Exception):
    pass


def _child_environment(scratch: str) -> dict[str, str]:
    env = {
        name: value
        for name, value in os.environ.items()
        if name in CHILD_ENVIRONMENT or name.startswith("LC_")
    }
    env.update(TMPDIR=scratch, HOME=scratch, PYTHONDONTWRITEBYTECODE="1")
    return env


async def _feed(stream: asyncio.StreamWriter | None, data: bytes) -> None:
    if stream is None:  # pragma: no cover - stdin is a pipe
        return
    try:
        stream.write(data)
        await stream.drain()
        stream.close()
    except (BrokenPipeError, ConnectionResetError):
        pass  # the child stopped reading (it failed early, or was killed)


async def _read(stream: asyncio.StreamReader | None, bound: int) -> bytes:
    if stream is None:  # pragma: no cover - stdout is a pipe
        return b""
    chunks: list[bytes] = []
    size = 0
    while chunk := await stream.read(256 * 1024):
        size += len(chunk)
        if size > bound:
            raise _TooMuchOutput
        chunks.append(chunk)
    return b"".join(chunks)


def _parse(output: bytes, max_chars: int) -> ChildOutcome:
    try:
        value: Any = json.loads(output)
        state = ExtractionState(value["state"])
        error = ExtractionError(value["error"]) if value.get("error") else None
        text = value.get("text", "")
        if not isinstance(text, str) or len(text) > max_chars:
            raise ValueError("text")
        if (state is ExtractionState.FAILED) != (error is not None):
            raise ValueError("error")
        if state is ExtractionState.PENDING:
            raise ValueError("state")
        return ChildOutcome(
            state=state,
            error=error,
            text=text if state is ExtractionState.DONE else "",
            truncated=bool(value.get("truncated")) and state is ExtractionState.DONE,
            active_content=bool(value.get("active_content")),
        )
    except (ValueError, KeyError, TypeError):
        return ChildOutcome(crashed=True)


async def run_child(
    kind: str,
    data: bytes,
    *,
    time_limit: float = BID_EXTRACTION_TIMEOUT.total_seconds(),
    limits: dict[str, int] | None = None,
    python: str = sys.executable,
) -> ChildOutcome:
    """Run the extraction child on one document (see the module docstring)."""
    limits = {**CHILD_LIMITS, **(limits or {})}
    scratch = tempfile.mkdtemp(prefix="soundings-extract-")
    process: asyncio.subprocess.Process | None = None
    try:
        process = await asyncio.create_subprocess_exec(
            python,
            "-I",
            "-B",
            "-m",
            CHILD_MODULE,
            kind,
            json.dumps(limits),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=_child_environment(scratch),
            cwd=scratch,
            start_new_session=True,
        )
        try:
            async with asyncio.timeout(time_limit):
                feeding = asyncio.create_task(_feed(process.stdin, data))
                try:
                    output = await _read(process.stdout, output_bound(limits["max_chars"]))
                finally:
                    await feeding
                code = await process.wait()
        except TimeoutError:
            return ChildOutcome.failed(ExtractionError.TIMEOUT)
        except _TooMuchOutput:
            return ChildOutcome.failed(ExtractionError.INTERNAL_ERROR)
        if code != 0 or not output:
            return ChildOutcome(crashed=True)
        return _parse(output, limits["max_chars"])
    finally:
        if process is not None:
            await _kill(process)
        shutil.rmtree(scratch, ignore_errors=True)


async def _kill(process: asyncio.subprocess.Process) -> None:
    """End the child and anything it started: its process group (it leads its own
    session), so nothing it left behind keeps the pipes open."""
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(process.pid, signal.SIGKILL)
    with contextlib.suppress(TimeoutError):
        async with asyncio.timeout(5):
            await process.wait()


# --- The job ---------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class _Claim:
    kind: str
    data: bytes
    attempt: int
    bid_id: UUID


async def _claim(sessionmaker: SessionMaker, document_id: UUID) -> _Claim | None:
    """Count the attempt (committed before the child starts) and read the bytes; ``None``
    when the document is gone, not pending, or out of attempts (then ``failed``)."""
    async with session_scope(sessionmaker) as db:
        document: BidDocument | None = await db.scalar(
            select(BidDocument)
            .where(BidDocument.id == document_id)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
        if document is None or document.extraction_state is not ExtractionState.PENDING:
            return None
        if document.extraction_attempts >= BID_EXTRACTION_MAX_ATTEMPTS:
            _finish(document, ChildOutcome.failed(ExtractionError.INTERNAL_ERROR))
            return None
        document.extraction_attempts += 1
        data = await db.scalar(
            select(BidDocumentContent.data).where(BidDocumentContent.document_id == document.id)
        )
        if data is None:  # pragma: no cover - written with the document
            return None
        return _Claim(
            kind=document.type.value,
            data=bytes(data),
            attempt=document.extraction_attempts,
            bid_id=document.bid_id,
        )


def _finish(document: BidDocument, outcome: ChildOutcome) -> None:
    assert outcome.state is not None  # noqa: S101 - a result, not a crash
    document.extraction_state = outcome.state
    document.extraction_error = outcome.error
    document.extracted_at = utcnow()
    document.text_chars = len(outcome.text) if outcome.state is ExtractionState.DONE else None
    document.text_truncated = outcome.truncated
    document.active_content = document.active_content or outcome.active_content


async def _record(
    sessionmaker: SessionMaker, document_id: UUID, outcome: ChildOutcome, attempt: int
) -> bool:
    """Store the result (or schedule the retry of a crash). ``True`` when the document is
    no longer pending."""
    async with session_scope(sessionmaker) as db:
        document: BidDocument | None = await db.scalar(
            select(BidDocument)
            .where(BidDocument.id == document_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if document is None or document.extraction_state is not ExtractionState.PENDING:
            return False  # deleted, or finished by another attempt
        if outcome.crashed:
            if attempt >= BID_EXTRACTION_MAX_ATTEMPTS:
                _finish(document, ChildOutcome.failed(ExtractionError.INTERNAL_ERROR))
                return True
            connection = await psycopg_connection(db)
            await procrastinate_app.configure_task(
                EXTRACT_TASK,
                connection=connection,
                queue=BID_DOCUMENT_QUEUE,
                schedule_in={"seconds": int(RETRY_AFTER_CRASH.total_seconds())},
            ).defer_async(document_id=str(document_id))
            return False
        if outcome.state is ExtractionState.DONE:
            db.add(BidDocumentText(document_id=document.id, text=outcome.text))
        _finish(document, outcome)
        await db.flush()
        return True


async def extract_document(
    sessionmaker: SessionMaker,
    document_id: UUID,
    *,
    on_done: Any = None,
    time_limit: float = BID_EXTRACTION_TIMEOUT.total_seconds(),
) -> ExtractionState | None:
    """The ``extract_bid_document`` job: claim, run the child, record. ``on_done(bid_id)``
    runs after the document left ``pending`` (the automatic AI check). The state it ended
    in, or ``None`` when nothing was done (or it waits for a retry)."""
    claim = await _claim(sessionmaker, document_id)
    if claim is None:
        async with session_scope(sessionmaker) as db:
            state = await db.scalar(
                select(BidDocument.extraction_state).where(BidDocument.id == document_id)
            )
        return state if state is not ExtractionState.PENDING else None
    try:
        outcome = await run_child(claim.kind, claim.data, time_limit=time_limit)
    except OSError:  # pragma: no cover - the interpreter couldn't be started
        logger.exception("bid extraction child failed to start")
        outcome = ChildOutcome(crashed=True)
    finished = await _record(sessionmaker, document_id, outcome, claim.attempt)
    logger.info(
        "bid document extracted",
        extra={
            "document_id": str(document_id),
            "attempt": claim.attempt,
            "state": outcome.state.value if outcome.state else "crashed",
            "error": outcome.error.value if outcome.error else None,
        },
    )
    if not finished:
        return None
    if on_done is not None:
        await on_done(claim.bid_id)
    async with session_scope(sessionmaker) as db:
        final: ExtractionState | None = await db.scalar(
            select(BidDocument.extraction_state).where(BidDocument.id == document_id)
        )
    return final


async def extract_in_session(
    db: AsyncSession, document: BidDocument, data: bytes
) -> ExtractionState | None:
    """Extract one document **now, in the caller's unit of work**, with the same child as
    the worker (the demo seed: its documents are extracted at seed time, in the seed's
    transaction). A crash counts as ``internal_error`` (no retries here). The worker's job,
    deferred by the upload, then finds it done and does nothing."""
    document.extraction_attempts += 1
    outcome = await run_child(document.type.value, data)
    if outcome.crashed:
        outcome = ChildOutcome.failed(ExtractionError.INTERNAL_ERROR)
    if outcome.state is ExtractionState.DONE:
        db.add(BidDocumentText(document_id=document.id, text=outcome.text))
    _finish(document, outcome)
    await db.flush()
    return document.extraction_state


# --- The sweep -------------------------------------------------------------------------------
_LOST = text(
    """
    SELECT d.id FROM bid_documents d
    WHERE d.extraction_state = 'pending'
      AND d.uploaded_at < :before
      AND NOT EXISTS (
        SELECT 1 FROM procrastinate_jobs j
        WHERE j.task_name = :task
          AND j.status IN ('todo', 'doing')
          AND j.args ->> 'document_id' = d.id::text
      )
    ORDER BY d.uploaded_at
    LIMIT :limit
    """
)


async def sweep_documents(sessionmaker: SessionMaker) -> int:
    """Re-queue pending documents whose job was lost (a worker that died mid-way; its job
    was marked failed by ``finish_stalled_jobs``). How many."""
    before = utcnow() - SWEEP_AFTER
    queued = 0
    async with session_scope(sessionmaker) as db:
        ids = list(
            await db.scalars(_LOST, {"before": before, "task": EXTRACT_TASK, "limit": SWEEP_BATCH})
        )
        for document_id in ids:
            try:
                async with db.begin_nested():
                    await defer_extraction(db, document_id)
            except AlreadyEnqueued:
                continue  # queued meanwhile
            queued += 1
    if queued:
        logger.warning("bid extractions re-queued", extra={"count": queued})
    return queued
