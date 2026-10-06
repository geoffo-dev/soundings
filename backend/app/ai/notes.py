"""Research notes (contract-phase6 section 3.8): what a "Research this" run produces.

A note is an ``activity_events`` row of type ``ai_research_note`` (actor: the agent's
service account) whose payload holds ``{run_id, agent_id, body_md, sources: [{title,
url}]}``: Markdown and cited sources written by an AI agent, untrusted, rendered
sanitised with an AI label. One per run: calling ``add_research_note`` again in the same
run replaces it. No notifications, mentions or emails. Deleting (``ai.delete_note``:
the idea's owner and admins) clears the text and sources and keeps the item ("deleted a
research note"). Never score data: the agent never sees others' scores (rule 9).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents import agent_ref
from app.authz import Resource, Rule, can, require
from app.domain.principal import Principal
from app.errors import ConflictProblem, NotFoundProblem, ProblemError
from app.models.activity import ActivityEvent
from app.models.ai import AiAgent, AiRun
from app.models.base import utcnow
from app.models.enums import IdeaStatus
from app.schemas.activity import AI_RESEARCH_NOTE
from app.schemas.ai import AiAgentRef, Citation, CitationIn, ResearchNote
from app.services import activity
from app.services.ideas import LoadedIdea

__all__ = [
    "agent_refs",
    "delete_note",
    "get_note",
    "note_out",
    "write_note",
]


def _note_not_found() -> ProblemError:
    return NotFoundProblem("Not found.")


def _uuid(value: object) -> UUID | None:
    try:
        return UUID(str(value)) if value else None
    except ValueError:
        return None


def note_out(
    principal: Principal,
    event: ActivityEvent,
    agents: Mapping[UUID, AiAgentRef],
    resource: Resource,
) -> ResearchNote:
    """The note as ``principal`` sees it (``can_delete``: ``ai.delete_note``)."""
    payload: Mapping[str, Any] = event.payload or {}
    deleted = bool(payload.get("deleted"))
    agent_id = _uuid(payload.get("agent_id"))
    sources = [] if deleted else payload.get("sources") or []
    return ResearchNote(
        id=event.id,
        run_id=_uuid(payload.get("run_id")),
        agent=agents.get(agent_id) if agent_id else None,
        body_md="" if deleted else str(payload.get("body_md") or ""),
        sources=[
            Citation(title=str(source.get("title", "")), url=str(source.get("url", "")))
            for source in sources
            if isinstance(source, Mapping)
        ],
        deleted=deleted,
        can_delete=not deleted and can(principal, Rule.AI_DELETE_NOTE, resource),
    )


async def agent_refs(db: AsyncSession, agent_ids: Iterable[UUID | None]) -> dict[UUID, AiAgentRef]:
    wanted = {agent_id for agent_id in agent_ids if agent_id is not None}
    if not wanted:
        return {}
    rows = await db.scalars(select(AiAgent).where(AiAgent.id.in_(wanted)))
    return {agent.id: agent_ref(agent) for agent in rows}


def note_agent_ids(events: Sequence[ActivityEvent]) -> list[UUID | None]:
    return [
        _uuid((event.payload or {}).get("agent_id"))
        for event in events
        if event.type == AI_RESEARCH_NOTE
    ]


async def _load(
    db: AsyncSession, loaded: LoadedIdea, note_id: UUID, *, for_update: bool = False
) -> ActivityEvent:
    statement = select(ActivityEvent).where(
        ActivityEvent.id == note_id,
        ActivityEvent.idea_id == loaded.idea.id,
        ActivityEvent.type == AI_RESEARCH_NOTE,
    )
    if for_update:
        statement = statement.with_for_update()
    event = await db.scalar(statement.execution_options(populate_existing=True))
    if event is None:
        raise _note_not_found()
    return event


async def get_note(
    db: AsyncSession, principal: Principal, loaded: LoadedIdea, note_id: UUID
) -> ResearchNote:
    """``GET /ideas/{idea}/research-notes/{note_id}`` (``idea.view``, checked by
    :func:`~app.services.ideas.load_idea`)."""
    event = await _load(db, loaded, note_id)
    agents = await agent_refs(db, note_agent_ids([event]))
    return note_out(principal, event, agents, loaded.resource)


async def delete_note(
    db: AsyncSession, principal: Principal, loaded: LoadedIdea, note_id: UUID
) -> None:
    """``DELETE``: 404 (not this idea's note) -> 403 -> 409 (archived, c19); idempotent."""
    event = await _load(db, loaded, note_id, for_update=True)
    require(principal, Rule.AI_DELETE_NOTE, loaded.resource)
    payload = dict(event.payload or {})
    if payload.get("deleted"):
        return
    event.payload = {
        "run_id": payload.get("run_id"),
        "agent_id": payload.get("agent_id"),
        "body_md": "",
        "sources": [],
        "deleted": True,
        # Who deleted it and when stay with the item (review L4; there is no audit action
        # for it yet: a new AuditAction needs the SPA's phrase in the same change).
        "deleted_by_id": str(principal.user_id),
        "deleted_at": utcnow().isoformat(),
    }
    await db.flush()


def _sources(sources: Sequence[CitationIn]) -> list[dict[str, str]]:
    return [{"title": source.title, "url": source.url} for source in sources]


async def write_note(
    db: AsyncSession,
    principal: Principal,
    loaded: LoadedIdea,
    run: AiRun,
    *,
    body_md: str,
    sources: Sequence[CitationIn],
) -> tuple[UUID, bool]:
    """MCP ``add_research_note`` for ``run`` (the agent's open research run on the idea,
    locked by :func:`app.ai.scope.lock_run`): ``comment.create`` (the member role and the
    ``write`` scope; 409 archived, c19), then 409 ``idea_closed``. Returns the note's id
    and whether it replaced the run's earlier note. Attaches it to the run."""
    require(principal, Rule.COMMENT_CREATE, loaded.resource)
    if loaded.idea.status is IdeaStatus.CLOSED:
        raise ConflictProblem("The idea is closed.", code="idea_closed")
    stored = _sources(sources)
    if run.activity_event_id is not None:
        event = await db.get(ActivityEvent, run.activity_event_id)
        if event is not None:
            event.payload = {
                "run_id": str(run.id),
                "agent_id": str(run.agent_id),
                "body_md": body_md,
                "sources": stored,
            }
            await db.flush()
            return event.id, True
    event = await activity.emit(
        db,
        loaded.idea,
        AI_RESEARCH_NOTE,
        actor=principal,
        payload={"run_id": run.id, "agent_id": run.agent_id, "body_md": body_md, "sources": stored},
    )
    await db.flush()
    await db.execute(
        update(AiRun)
        .where(AiRun.id == run.id)
        .values(activity_event_id=event.id)
        .execution_options(synchronize_session=False)
    )
    run.activity_event_id = event.id
    return event.id, False
