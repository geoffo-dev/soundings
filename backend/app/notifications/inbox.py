"""The in-app inbox (contract-phase3 section 3.2): list, unread count, read state.

Only notifications about ideas the caller can view **now** are listed or counted (the
same SQL filter as every list: :func:`app.authz.viewable_ideas`); others are skipped,
not shown as gaps. Items carry the idea's current title and status labels, never
score data.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID

from sqlalchemy import exists, func, or_, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import viewable_ideas
from app.config import Settings
from app.domain.labels import status_label
from app.domain.principal import Principal
from app.errors import NotFoundProblem
from app.models.activity import Comment
from app.models.base import utcnow
from app.models.enums import EmailStatus, IdeaStatus, NotificationType, Resolution
from app.models.idea import Idea
from app.models.notification import Notification, OutboundEmail
from app.models.project import Project
from app.notifications.access import parse_time
from app.notifications.excerpt import comment_excerpt
from app.pagination import InvalidCursorProblem, decode_cursor, encode_cursor
from app.schemas.notifications import (
    UNREAD_COUNT_CAP,
    CommentExcerpt,
    CommentNotification,
    EvaluationReminderNotification,
    EvaluationsCompleteNotification,
    EvaluatorInvitedNotification,
    MentionNotification,
    NotificationItem,
    NotificationPage,
    NotificationSummary,
    OwnerAssignedNotification,
    StatusChangedNotification,
)
from app.services.refs import idea_ref
from app.services.sql import any_of
from app.services.summaries import user_refs

__all__ = [
    "EMAIL_STUCK_AFTER",
    "EMAIL_TROUBLE_WINDOW",
    "decode_time_cursor",
    "email_trouble",
    "list_notifications",
    "mark_all_read",
    "mark_read",
    "summary",
]

EMAIL_TROUBLE_WINDOW: Final = timedelta(hours=24)
EMAIL_STUCK_AFTER: Final = timedelta(minutes=15)


def decode_time_cursor(cursor: str) -> tuple[datetime, UUID]:
    """A ``{"t": <created_at>, "id": <id>}`` keyset cursor; 400 if it isn't one."""
    after = decode_cursor(cursor)
    try:
        if set(after) != {"t", "id"}:
            raise ValueError("foreign cursor")
        created = datetime.fromisoformat(str(after["t"]))
        if created.tzinfo is None:
            raise ValueError("no offset")
        created.astimezone(UTC)  # OverflowError out of range (unsigned cursor)
        return created, UUID(str(after["id"]))
    except (ValueError, TypeError, OverflowError) as exc:
        raise InvalidCursorProblem from exc


def _mine(principal: Principal) -> Any:
    return (Notification.user_id == principal.user_id) & viewable_ideas(principal)


async def list_notifications(
    db: AsyncSession, principal: Principal, *, unread: bool, cursor: str | None, limit: int
) -> NotificationPage:
    statement = (
        select(Notification, Idea, Project)
        .join(Idea, Idea.id == Notification.idea_id)
        .join(Project, Project.id == Idea.project_id)
        .where(_mine(principal))
    )
    if unread:
        statement = statement.where(Notification.read_at.is_(None))
    if cursor:
        statement = statement.where(
            tuple_(Notification.created_at, Notification.id) < decode_time_cursor(cursor)
        )
    rows = (
        await db.execute(
            statement.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(
                limit + 1
            )
        )
    ).all()
    page = list(rows[:limit])
    next_cursor = None
    if len(rows) > limit and page:
        last = page[-1][0]
        next_cursor = encode_cursor({"t": last.created_at, "id": last.id})
    return NotificationPage(items=await _items(db, page), next_cursor=next_cursor)


async def _items(
    db: AsyncSession, rows: Sequence[tuple[Notification, Idea, Project]]
) -> list[NotificationItem]:
    actors = await user_refs(db, (notification.actor_id for notification, _, _ in rows))
    comment_ids = [n.comment_id for n, _, _ in rows if n.comment_id is not None]
    comments = {
        comment.id: comment
        for comment in (
            await db.scalars(select(Comment).where(any_of(Comment.id, comment_ids)))
            if comment_ids
            else []
        )
    }
    items: list[NotificationItem] = []
    for notification, idea, project in rows:
        base: dict[str, Any] = {
            "id": notification.id,
            "created_at": notification.created_at,
            "read_at": notification.read_at,
            "idea": idea_ref(idea, project),
            "actor": actors.get(notification.actor_id) if notification.actor_id else None,
        }
        item = _item(notification, project, base, comments)
        if item is not None:
            items.append(item)
    return items


def _excerpt(comment_id: UUID | None, comments: dict[UUID, Comment]) -> CommentExcerpt:
    assert comment_id is not None  # noqa: S101 - ck_notifications_comment_iff_comment_type
    comment = comments.get(comment_id)
    if comment is None or comment.deleted_at is not None:
        return CommentExcerpt(id=comment_id, excerpt="", deleted=True)
    return CommentExcerpt(id=comment_id, excerpt=comment_excerpt(comment.body_md), deleted=False)


def _item(
    notification: Notification,
    project: Project,
    base: dict[str, Any],
    comments: dict[UUID, Comment],
) -> NotificationItem | None:
    payload = notification.payload
    match notification.type:
        case NotificationType.OWNER_ASSIGNED:
            return OwnerAssignedNotification(type="owner_assigned", **base)
        case NotificationType.EVALUATOR_INVITED:
            return EvaluatorInvitedNotification(
                type="evaluator_invited", due_at=parse_time(payload.get("due_at")), **base
            )
        case NotificationType.EVALUATION_REMINDER:
            due_at = parse_time(payload.get("due_at"))
            if due_at is None:
                return None
            return EvaluationReminderNotification(
                type="evaluation_reminder",
                due_at=due_at,
                days_before=int(payload.get("days_before") or 0),
                **base,
            )
        case NotificationType.EVALUATIONS_COMPLETE:
            return EvaluationsCompleteNotification(
                type="evaluations_complete",
                evaluator_count=max(1, int(payload.get("evaluator_count") or 1)),
                **base,
            )
        case NotificationType.STATUS_CHANGED:
            labels = project.status_labels
            from_status = IdeaStatus(payload["from_status"])
            to_status = IdeaStatus(payload["to_status"])
            from_resolution = _resolution(payload.get("from_resolution"))
            to_resolution = _resolution(payload.get("to_resolution"))
            return StatusChangedNotification(
                type="status_changed",
                from_status=from_status,
                from_resolution=from_resolution,
                from_label=status_label(labels, from_status, from_resolution),
                to_status=to_status,
                to_resolution=to_resolution,
                to_label=status_label(labels, to_status, to_resolution),
                **base,
            )
        case NotificationType.COMMENT:
            return CommentNotification(
                type="comment", comment=_excerpt(notification.comment_id, comments), **base
            )
        case NotificationType.MENTION:
            return MentionNotification(
                type="mention", comment=_excerpt(notification.comment_id, comments), **base
            )


def _resolution(value: object) -> Resolution | None:
    return Resolution(str(value)) if value else None


# --- Counts and the email banners ---------------------------------------------------------
async def _unread_count(db: AsyncSession, principal: Principal) -> int:
    capped = (
        select(Notification.id)
        .join(Idea, Idea.id == Notification.idea_id)
        .where(_mine(principal), Notification.read_at.is_(None))
        .limit(UNREAD_COUNT_CAP)
        .subquery()
    )
    return int(await db.scalar(select(func.count()).select_from(capped)) or 0)


async def email_trouble(db: AsyncSession, now: datetime | None = None) -> bool:
    """An email failed in the last 24 hours, or one has been queued over 15 minutes."""
    now = now or utcnow()
    failed = exists().where(
        OutboundEmail.status == EmailStatus.FAILED,
        OutboundEmail.updated_at > now - EMAIL_TROUBLE_WINDOW,
    )
    stuck = exists().where(
        OutboundEmail.status == EmailStatus.QUEUED,
        OutboundEmail.created_at < now - EMAIL_STUCK_AFTER,
    )
    return bool(await db.scalar(select(or_(failed, stuck))))


async def summary(
    db: AsyncSession, settings: Settings, principal: Principal
) -> NotificationSummary:
    trouble = False
    if settings.smtp_configured and principal.is_platform_admin:
        trouble = await email_trouble(db)
    return NotificationSummary(
        unread_count=await _unread_count(db, principal),
        email_available=settings.smtp_configured,
        email_trouble=trouble,
    )


# --- Read state ---------------------------------------------------------------------------
async def mark_read(db: AsyncSession, principal: Principal, notification_id: UUID) -> None:
    """Idempotent; 404 unless it is the caller's, about an idea they can view."""
    found = await db.scalar(
        select(Notification)
        .join(Idea, Idea.id == Notification.idea_id)
        .where(Notification.id == notification_id, _mine(principal))
    )
    if found is None:
        raise NotFoundProblem
    if found.read_at is None:
        found.read_at = utcnow()
        await db.flush()


async def mark_all_read(
    db: AsyncSession, settings: Settings, principal: Principal, idea_id: UUID | None
) -> NotificationSummary:
    """Every unread notification of the caller (viewable or not), or those about one idea
    (checked by the caller with ``idea.view``)."""
    statement = (
        update(Notification)
        .where(Notification.user_id == principal.user_id, Notification.read_at.is_(None))
        .values(read_at=utcnow())
        .execution_options(synchronize_session=False)
    )
    if idea_id is not None:
        statement = statement.where(Notification.idea_id == idea_id)
    await db.execute(statement)
    return await summary(db, settings, principal)
