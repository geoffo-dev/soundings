"""Reading the activity feed (contract sections 3.12 and 3.13).

``activity_events`` rows become the ``ActivityItem`` union: ids in the payload are
resolved to ``UserRef`` (``null`` for users that no longer exist) and comment events
carry their comment with your ``can_edit`` / ``can_delete``. Payloads hold ids and
from/to values only (:mod:`app.services.activity` refuses anything else), so the feed
is the same for everyone who can view the idea, pending evaluators included.

Phase 8b (review M2): a caller without ``evaluation.view_own`` on the idea (a guest
researcher, role matrix column R) gets only ``RESEARCH_GUEST_ACTIVITY_TYPES`` (an
allow-list, filtered in the query so cursors page over it); status sentences carry the
project's labels (``from_label`` / ``to_label``), so no project read is needed.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, tuple_
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import notes
from app.authz import Resource, Rule, can
from app.domain.labels import status_label
from app.domain.principal import Principal
from app.models.activity import ActivityEvent, Comment
from app.models.enums import IdeaStatus, Resolution
from app.pagination import InvalidCursorProblem, decode_cursor, encode_cursor
from app.schemas.activity import (
    AI_RESEARCH_NOTE,
    RESEARCH_GUEST_ACTIVITY_TYPES,
    ActivityItem,
    ActivityPage,
    AiResearchNoteActivity,
    CommentActivity,
    CommentBody,
    DueDateChangedActivity,
    EvaluationClosedActivity,
    EvaluationReopenedActivity,
    EvaluationSubmittedActivity,
    EvaluatorAddedActivity,
    EvaluatorRemovedActivity,
    IdeaCreatedActivity,
    IdeaEditedActivity,
    OwnerChangedActivity,
    ResearchDueDateChangedActivity,
    ResearcherChangedActivity,
    StatusChangedActivity,
)
from app.schemas.ai import ResearchNote
from app.schemas.users import UserRef
from app.services.sql import any_of
from app.services.summaries import user_refs

__all__ = ["activity_items", "comment_body", "latest_activity", "list_activity"]

_USER_KEYS = (
    "from_owner_id",
    "to_owner_id",
    "evaluator_id",
    "from_researcher_id",
    "to_researcher_id",
)

Labels = Mapping[str, str]
"""A project's status label overrides (``projects.status_labels``)."""


def _uuid(value: object) -> UUID | None:
    return UUID(str(value)) if value else None


def _datetime(value: object) -> datetime | None:
    return datetime.fromisoformat(str(value)) if value else None


def comment_body(principal: Principal, comment: Comment, resource: Resource) -> CommentBody:
    """The comment as you see it: your edit/delete rights, or a deleted placeholder."""
    deleted = comment.deleted_at is not None
    own = resource.replace(comment_author_id=comment.author_id)
    can_edit = not deleted and can(principal, Rule.COMMENT_EDIT_OWN, own)
    return CommentBody(
        id=comment.id,
        body_md="" if deleted else comment.body_md,
        edited_at=comment.edited_at,
        deleted=deleted,
        can_edit=can_edit,
        can_delete=not deleted and (can_edit or can(principal, Rule.COMMENT_DELETE_ANY, own)),
    )


def _label(labels: Labels | None, status: object, resolution: object) -> str | None:
    if labels is None:
        return None
    return status_label(
        labels, IdeaStatus(str(status)), Resolution(str(resolution)) if resolution else None
    )


def _item(
    event: ActivityEvent,
    users: Mapping[UUID, UserRef],
    comment: CommentBody | None,
    note: ResearchNote | None = None,
    labels: Labels | None = None,
) -> ActivityItem | None:
    payload = event.payload
    base: dict[str, Any] = {
        "id": event.id,
        "idea_id": event.idea_id,
        "created_at": event.created_at,
        "actor": users.get(event.actor_id) if event.actor_id else None,
    }

    def user(key: str) -> UserRef | None:
        user_id = _uuid(payload.get(key))
        return users.get(user_id) if user_id else None

    match event.type:
        case "comment":
            return (
                None
                if comment is None
                else CommentActivity(type="comment", comment=comment, **base)
            )
        case "idea_created":
            return IdeaCreatedActivity(type="idea_created", **base)
        case "idea_edited":
            return IdeaEditedActivity(type="idea_edited", fields=payload["fields"], **base)
        case "status_changed":
            return StatusChangedActivity(
                type="status_changed",
                from_status=payload["from_status"],
                from_resolution=payload["from_resolution"],
                to_status=payload["to_status"],
                to_resolution=payload["to_resolution"],
                research_overridden=bool(payload.get("research_overridden", False)),
                from_label=_label(labels, payload["from_status"], payload["from_resolution"]),
                to_label=_label(labels, payload["to_status"], payload["to_resolution"]),
                **base,
            )
        case "owner_changed":
            return OwnerChangedActivity(
                type="owner_changed",
                from_owner=user("from_owner_id"),
                to_owner=user("to_owner_id"),
                volunteered=bool(payload["volunteered"]),
                **base,
            )
        case "evaluator_added":
            return EvaluatorAddedActivity(
                type="evaluator_added", evaluator=user("evaluator_id"), **base
            )
        case "evaluator_removed":
            return EvaluatorRemovedActivity(
                type="evaluator_removed", evaluator=user("evaluator_id"), **base
            )
        case "evaluation_submitted":
            return EvaluationSubmittedActivity(
                type="evaluation_submitted", evaluator=user("evaluator_id"), **base
            )
        case "evaluation_closed":
            return EvaluationClosedActivity(type="evaluation_closed", **base)
        case "evaluation_reopened":
            return EvaluationReopenedActivity(type="evaluation_reopened", **base)
        case "due_date_changed":
            return DueDateChangedActivity(
                type="due_date_changed",
                from_due_at=_datetime(payload["from_due_at"]),
                to_due_at=_datetime(payload["to_due_at"]),
                **base,
            )
        case "ai_research_note":
            return (
                None
                if note is None
                else AiResearchNoteActivity(type="ai_research_note", note=note, **base)
            )
        case "researcher_changed":
            return ResearcherChangedActivity(
                type="researcher_changed",
                from_researcher=user("from_researcher_id"),
                to_researcher=user("to_researcher_id"),
                handed_back=bool(payload["handed_back"]),
                **base,
            )
        case "research_due_date_changed":
            return ResearchDueDateChangedActivity(
                type="research_due_date_changed",
                from_due_at=_datetime(payload["from_due_at"]),
                to_due_at=_datetime(payload["to_due_at"]),
                **base,
            )
    return None  # a type from a later phase: clients skip it too


def event_user_ids(events: Sequence[ActivityEvent]) -> set[UUID]:
    """The people ``events`` name (actors and payload users), for :func:`activity_items`."""
    user_ids: set[UUID | None] = {event.actor_id for event in events}
    for event in events:
        user_ids.update(_uuid(event.payload.get(key)) for key in _USER_KEYS)
    return {user_id for user_id in user_ids if user_id is not None}


async def activity_items(
    db: AsyncSession,
    principal: Principal,
    events: Sequence[ActivityEvent],
    resource_for: Callable[[UUID], Resource],
    *,
    users: Mapping[UUID, UserRef] | None = None,
    labels_for: Callable[[UUID], Labels | None] | None = None,
) -> list[ActivityItem]:
    """Feed items for ``events`` (users and comments loaded in batches);
    ``resource_for(idea_id)`` gives the facts for comment permissions. ``users``: the
    people already loaded for :func:`event_user_ids` (My work), else loaded here.
    ``labels_for(idea_id)``: the idea's project's status labels (``from_label`` /
    ``to_label``; Phase 8b)."""
    if users is None:
        users = await user_refs(db, event_user_ids(events))
    comment_ids = [event.comment_id for event in events if event.comment_id is not None]
    comments: dict[UUID, Comment] = {}
    if comment_ids:
        found = await db.scalars(select(Comment).where(any_of(Comment.id, comment_ids)))
        comments = {comment.id: comment for comment in found}
    agents = (
        await notes.agent_refs(db, notes.note_agent_ids(events))
        if any(event.type == AI_RESEARCH_NOTE for event in events)
        else {}
    )
    items = []
    for event in events:
        comment = comments.get(event.comment_id) if event.comment_id else None
        body = (
            comment_body(principal, comment, resource_for(comment.idea_id))
            if comment is not None
            else None
        )
        note = (
            notes.note_out(principal, event, agents, resource_for(event.idea_id))
            if event.type == AI_RESEARCH_NOTE and event.idea_id is not None
            else None
        )
        labels = labels_for(event.idea_id) if labels_for and event.idea_id else None
        item = _item(event, users, body, note, labels)
        if item is not None:
            items.append(item)
    return items


async def list_activity(
    db: AsyncSession,
    principal: Principal,
    idea_id: UUID,
    resource: Resource,
    *,
    cursor: str | None,
    limit: int,
    labels: Labels | None = None,
) -> ActivityPage:
    """The idea's feed, newest first (``idea.view`` is checked by the caller).

    Without ``evaluation.view_own`` on the idea (a guest researcher), only the allow-list
    ``RESEARCH_GUEST_ACTIVITY_TYPES`` (review M2), filtered before paging."""
    statement = select(ActivityEvent).where(ActivityEvent.idea_id == idea_id)
    if not can(principal, Rule.EVALUATION_VIEW_OWN, resource):
        statement = statement.where(ActivityEvent.type.in_(sorted(RESEARCH_GUEST_ACTIVITY_TYPES)))
    if cursor:
        after = decode_cursor(cursor)
        try:
            if set(after) != {"t", "id"}:
                raise ValueError("foreign cursor")
            created = datetime.fromisoformat(str(after["t"]))
            if created.tzinfo is None:
                raise ValueError("no offset")
            created.astimezone(UTC)  # OverflowError out of range (unsigned cursor)
            position = (created, UUID(str(after["id"])))
        except (ValueError, TypeError, OverflowError) as exc:
            raise InvalidCursorProblem from exc
        statement = statement.where(tuple_(ActivityEvent.created_at, ActivityEvent.id) < position)
    events = list(
        await db.scalars(
            statement.order_by(ActivityEvent.created_at.desc(), ActivityEvent.id.desc()).limit(
                limit + 1
            )
        )
    )
    page = events[:limit]
    next_cursor = None
    if len(events) > limit and page:
        next_cursor = encode_cursor({"t": page[-1].created_at, "id": page[-1].id})
    items = await activity_items(
        db, principal, page, lambda _: resource, labels_for=lambda _: labels
    )
    return ActivityPage(items=items, next_cursor=next_cursor)


async def latest_events(db: AsyncSession, idea_ids: Sequence[UUID]) -> list[ActivityEvent]:
    """The newest event of each idea (My work, "recent"), for :func:`latest_activity`."""
    if not idea_ids:
        return []
    return list(
        await db.scalars(
            select(ActivityEvent)
            .where(any_of(ActivityEvent.idea_id, idea_ids))
            .ext(distinct_on(ActivityEvent.idea_id))
            .order_by(
                ActivityEvent.idea_id, ActivityEvent.created_at.desc(), ActivityEvent.id.desc()
            )
        )
    )


async def latest_activity(
    db: AsyncSession,
    principal: Principal,
    events: Sequence[ActivityEvent],
    resource_for: Callable[[UUID], Resource],
    *,
    users: Mapping[UUID, UserRef] | None = None,
    labels_for: Callable[[UUID], Labels | None] | None = None,
) -> dict[UUID, ActivityItem]:
    """The feed item of each of :func:`latest_events`, by idea."""
    items = await activity_items(
        db, principal, events, resource_for, users=users, labels_for=labels_for
    )
    return {item.idea_id: item for item in items}
