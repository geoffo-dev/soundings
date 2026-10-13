"""The in-app inbox (contract-phase3 section 3.2): list, unread count, read state.

Only notifications about ideas the caller can view **now** are listed or counted (the
same SQL filter as every list: :func:`app.authz.viewable_ideas`); others are skipped,
not shown as gaps. Items carry the idea's current title and status labels, never
score data. Phase 8b (review S5): about an idea the caller sees only as its guest
researcher (:func:`app.authz.researched_ideas`), only ``RESEARCH_GUEST_NOTIFICATION_TYPES``;
"Asked to research" only while it is the caller's live assignment (review M1). Phase 10:
a bid type only while its call exists and the caller still assesses a section of it
("Asked to assess bids", reminders) or manages it ("Bid assessments complete"), as the
send-time checks (:func:`app.notifications.access.applies`) decide.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID

from sqlalchemy import Uuid, and_, cast, exists, func, or_, select, true, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import researched_ideas, sees_email_trouble, viewable_ideas
from app.config import Settings
from app.domain.labels import status_label
from app.domain.principal import Principal
from app.errors import NotFoundProblem
from app.models.activity import Comment
from app.models.base import utcnow
from app.models.bid import BidCall, BidCallSection, BidSectionAssessor
from app.models.enums import EmailStatus, IdeaStatus, NotificationType, ProjectRole, Resolution
from app.models.idea import Idea
from app.models.notification import Notification, OutboundEmail
from app.models.project import Project, project_effective_roles
from app.notifications.access import parse_time, parse_uuid
from app.notifications.excerpt import comment_excerpt
from app.pagination import InvalidCursorProblem, decode_cursor, encode_cursor
from app.schemas.bid_refs import BidCallRef
from app.schemas.notifications import (
    BID_NOTIFICATION_TYPES,
    RESEARCH_GUEST_NOTIFICATION_TYPES,
    UNREAD_COUNT_CAP,
    AssessmentReminderNotification,
    AssessmentsCompleteNotification,
    AssessorAssignedNotification,
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
    ResearcherAssignedNotification,
    ResearchReminderNotification,
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


_GUEST_TYPES: Final = sorted(type_.value for type_ in RESEARCH_GUEST_NOTIFICATION_TYPES)


_BID_TYPES: Final = sorted(type_.value for type_ in BID_NOTIFICATION_TYPES)
_ASSESSOR_TYPES: Final = sorted(
    type_.value
    for type_ in (NotificationType.ASSESSOR_ASSIGNED, NotificationType.ASSESSMENT_REMINDER)
)
_CALL_ID: Final = cast(Notification.payload["call_id"].astext, Uuid)
_roles = project_effective_roles


def _bid_items(principal: Principal) -> Any:
    """Phase 10: a bid notification only while its call exists and the caller still holds
    the rule its send-time check needs (:func:`app.notifications.access.applies`): assessing
    a section of the call (an assignment; with :func:`viewable_ideas`, c28 for a person) or
    managing it (``bid.view_scores``: a platform admin, a project admin, the idea's owner
    with member or admin). One probe of ``ix_bid_section_assessors_user_id_call_id`` or the
    call's primary key per bid notification."""
    assessor = exists().where(
        BidSectionAssessor.call_id == _CALL_ID,
        BidSectionAssessor.user_id == Notification.user_id,
    )
    if principal.is_platform_admin:
        manager: Any = true()
    else:
        manager = exists().where(
            _roles.c.project_id == Idea.project_id,
            _roles.c.user_id == principal.user_id,
            or_(
                _roles.c.role == ProjectRole.ADMIN,
                and_(Idea.owner_id == principal.user_id, _roles.c.role == ProjectRole.MEMBER),
            ),
        )
    return or_(
        Notification.type.not_in(_BID_TYPES),
        and_(Notification.type.in_(_ASSESSOR_TYPES), assessor),
        and_(
            Notification.type == NotificationType.ASSESSMENTS_COMPLETE,
            exists().where(BidCall.id == _CALL_ID),
            manager,
        ),
    )


def _mine(principal: Principal) -> Any:
    """The caller's notifications about ideas they can view now (joined with ``ideas``);
    "Asked to research" only while it is the idea's live assignment of the caller (Phase
    8b review M1: someone asked and then replaced, or asked again later, keeps no stale
    request); Phase 10's bid types only while they still apply (:func:`_bid_items`)."""
    current_request = or_(
        Notification.type != NotificationType.RESEARCHER_ASSIGNED,
        and_(
            Idea.researcher_id == Notification.user_id,
            Notification.created_at >= Idea.research_assigned_at,
        ),
    )
    return (
        (Notification.user_id == principal.user_id)
        & current_request
        & _bid_items(principal)
        & or_(
            viewable_ideas(principal),
            and_(researched_ideas(principal), Notification.type.in_(_GUEST_TYPES)),
        )
    )


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
    calls, sections = await _bid_context(db, [notification for notification, _, _ in rows])
    items: list[NotificationItem] = []
    for notification, idea, project in rows:
        base: dict[str, Any] = {
            "id": notification.id,
            "created_at": notification.created_at,
            "read_at": notification.read_at,
            "idea": idea_ref(idea, project),
            "actor": actors.get(notification.actor_id) if notification.actor_id else None,
        }
        item = _item(notification, project, base, comments, calls, sections)
        if item is not None:
            items.append(item)
    return items


async def _bid_context(
    db: AsyncSession, notifications: Sequence[Notification]
) -> tuple[dict[UUID, BidCallRef], dict[tuple[UUID, UUID], list[str]]]:
    """Phase 10: the calls the page's bid notifications are about, as they are now, and
    for "Asked to assess bids" the titles of the sections each recipient assesses now (in
    the template's order). At most two statements, none without a bid notification."""
    wanted: set[UUID] = set()
    for notification in notifications:
        if notification.type in BID_NOTIFICATION_TYPES:
            call_id = parse_uuid(notification.payload.get("call_id"))
            if call_id is not None:
                wanted.add(call_id)
    if not wanted:
        return {}, {}
    calls = {
        call.id: BidCallRef(id=call.id, title=call.title, status=call.status)
        for call in await db.scalars(select(BidCall).where(any_of(BidCall.id, wanted)))
    }
    users = {n.user_id for n in notifications if n.type is NotificationType.ASSESSOR_ASSIGNED}
    sections: dict[tuple[UUID, UUID], list[str]] = {}
    if users:
        rows = await db.execute(
            select(BidSectionAssessor.call_id, BidSectionAssessor.user_id, BidCallSection.title)
            .join(BidCallSection, BidCallSection.id == BidSectionAssessor.section_id)
            .where(
                any_of(BidSectionAssessor.call_id, wanted),
                any_of(BidSectionAssessor.user_id, users),
            )
            .order_by(BidCallSection.position, BidCallSection.id)
        )
        for call_id, user_id, title in rows:
            sections.setdefault((call_id, user_id), []).append(title)
    return calls, sections


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
    calls: dict[UUID, BidCallRef],
    sections: dict[tuple[UUID, UUID], list[str]],
) -> NotificationItem | None:
    payload = notification.payload
    call: BidCallRef | None = None
    if notification.type in BID_NOTIFICATION_TYPES:
        call_id = parse_uuid(payload.get("call_id"))
        call = calls.get(call_id) if call_id is not None else None
        if call is None:
            return None  # the call was deleted meanwhile
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
        case NotificationType.RESEARCHER_ASSIGNED:
            return ResearcherAssignedNotification(
                type="researcher_assigned", due_at=parse_time(payload.get("due_at")), **base
            )
        case NotificationType.RESEARCH_REMINDER:
            due_at = parse_time(payload.get("due_at"))
            if due_at is None:
                return None
            return ResearchReminderNotification(
                type="research_reminder",
                due_at=due_at,
                days_before=int(payload.get("days_before") or 0),
                as_owner=bool(payload.get("as_owner")),
                **base,
            )
        case NotificationType.ASSESSOR_ASSIGNED:
            assert call is not None  # noqa: S101 - checked above
            return AssessorAssignedNotification(
                type="assessor_assigned",
                call=call,
                sections=sections.get((call.id, notification.user_id), []),
                due_at=parse_time(payload.get("due_at")),
                **base,
            )
        case NotificationType.ASSESSMENT_REMINDER:
            assert call is not None  # noqa: S101 - checked above
            due_at = parse_time(payload.get("due_at"))
            if due_at is None:
                return None
            return AssessmentReminderNotification(
                type="assessment_reminder",
                call=call,
                due_at=due_at,
                days_before=int(payload.get("days_before") or 0),
                **base,
            )
        case NotificationType.ASSESSMENTS_COMPLETE:
            assert call is not None  # noqa: S101 - checked above
            return AssessmentsCompleteNotification(
                type="assessments_complete",
                call=call,
                bid_count=max(1, int(payload.get("bid_count") or 1)),
                assessment_count=max(1, int(payload.get("assessment_count") or 1)),
                **base,
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
    if settings.smtp_configured and sees_email_trouble(principal):
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
