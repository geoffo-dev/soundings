"""The idea activity feed: emit events (contract section 3.13).

"Emit" = insert an ``activity_events`` row (actor = the current user) and set
``ideas.last_activity_at = now()``, in the same transaction as the change, and queue
the event for the notification fan-out, which runs once before that transaction
commits (contract-phase3 section 3.3, :mod:`app.notifications.fanout`)::

    await activity.emit(db, idea, "status_changed", actor=principal, payload={
        "from_status": old, "from_resolution": None, "to_status": new, "to_resolution": None,
    })

Payloads are checked against the exact keys each type stores, so nothing else (and
never a score) can be written into the feed.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from enum import Enum
from typing import Any, Final
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.principal import Principal
from app.models.activity import ActivityEvent
from app.models.base import utcnow
from app.models.idea import Idea
from app.notifications import fanout
from app.schemas.activity import ACTIVITY_TYPES

__all__ = ["OPTIONAL_PAYLOAD_KEYS", "PAYLOAD_KEYS", "emit"]

PAYLOAD_KEYS: Final[Mapping[str, frozenset[str]]] = {
    "idea_created": frozenset(),
    "idea_edited": frozenset({"fields"}),
    "status_changed": frozenset({"from_status", "from_resolution", "to_status", "to_resolution"}),
    "owner_changed": frozenset({"from_owner_id", "to_owner_id", "volunteered"}),
    "evaluator_added": frozenset({"evaluator_id"}),
    "evaluator_removed": frozenset({"evaluator_id"}),
    "evaluation_submitted": frozenset({"evaluator_id"}),
    "evaluation_closed": frozenset(),
    "evaluation_reopened": frozenset(),
    "due_date_changed": frozenset({"from_due_at", "to_due_at"}),
    "comment": frozenset(),
    # Phase 6: the note itself (agent text, untrusted; never score data). Deleting it
    # clears body_md and sources and adds deleted: true (app.ai.notes).
    "ai_research_note": frozenset({"run_id", "agent_id", "body_md", "sources"}),
    # Phase 8b: who does the research and by when (contract-phase8b section 3.6).
    "researcher_changed": frozenset({"from_researcher_id", "to_researcher_id", "handed_back"}),
    "research_due_date_changed": frozenset({"from_due_at", "to_due_at"}),
}
"""The stored payload keys per event type (ids are resolved to users by the API)."""

OPTIONAL_PAYLOAD_KEYS: Final[Mapping[str, frozenset[str]]] = {
    # Phase 8: "Move anyway" past an unfinished research checklist (absent = false), and
    # the project's research step when the move is into or out of Research (public
    # tracking reports Research with the step of the time; never shown in the feed).
    "status_changed": frozenset({"research_overridden", "research_step"}),
}
"""Keys a payload may add to :data:`PAYLOAD_KEYS` (only when they say something)."""

if set(PAYLOAD_KEYS) != set(ACTIVITY_TYPES):  # pragma: no cover - import-time guard
    raise RuntimeError("PAYLOAD_KEYS must cover exactly schemas.activity.ACTIVITY_TYPES")


def _stored(value: object) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list | tuple):
        return [_stored(item) for item in value]
    if isinstance(value, Mapping):
        # A research note's sources: [{title, url}] (strings only).
        if not all(isinstance(key, str) and isinstance(item, str) for key, item in value.items()):
            raise TypeError("activity payload objects hold strings only")
        return dict(value)
    if value is None or isinstance(value, bool | str):
        return value
    raise TypeError(f"activity payloads hold ids, enums, dates, flags and names, not {value!r}")


async def emit(
    db: AsyncSession,
    idea: Idea,
    type_: str,
    *,
    actor: Principal | UUID | None,
    payload: Mapping[str, object] | None = None,
    comment_id: UUID | None = None,
    at: datetime | None = None,
) -> ActivityEvent:
    """Record an event on ``idea`` and bump its ``last_activity_at``."""
    expected = PAYLOAD_KEYS.get(type_)
    if expected is None:
        raise ValueError(f"unknown activity type {type_!r}")
    values = dict(payload or {})
    optional = OPTIONAL_PAYLOAD_KEYS.get(type_, frozenset())
    if not expected <= set(values) <= expected | optional:
        raise ValueError(f"{type_} payload must have exactly {sorted(expected)}")
    if (type_ == "comment") != (comment_id is not None):
        raise ValueError("comment events (and only they) carry comment_id")
    now = at or utcnow()
    event = ActivityEvent(
        id=uuid4(),
        project_id=idea.project_id,
        idea_id=idea.id,
        actor_id=actor.user_id if isinstance(actor, Principal) else actor,
        type=type_,
        comment_id=comment_id,
        payload={key: _stored(value) for key, value in values.items()},
        created_at=now,
    )
    db.add(event)
    idea.last_activity_at = now
    fanout.queue_event(db, event)
    return event
