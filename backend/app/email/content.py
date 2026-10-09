"""What an outbox email says, built from the current data when it is sent.

:func:`prepare` is steps 2-3 of the worker's attempt (contract-phase3 section 3.9):
load the recipient and check the address; cancel mail that is out of date, no longer
applies (``idea.view`` and the type's condition, again, through
:mod:`app.notifications.access`) or that the recipient has turned off; then build the
:class:`~app.email.model.EmailContent` (section 3.11). It never reads score data: an
email shows the idea's key, title, project and status, people's names, dates and
comment excerpts only.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import Rule, can
from app.config import Settings
from app.domain.labels import status_label
from app.email.model import (
    DEFAULT_BRANDING,
    TYPE_LABELS,
    Branding,
    Button,
    EmailContent,
    IdeaInfo,
    Links,
    format_day,
    format_moment,
    plural,
    subject_title,
)
from app.email.outbox import max_age, message_id_domain
from app.models.activity import Comment
from app.models.enums import (
    EmailType,
    IdeaStatus,
    NotificationMode,
    NotificationType,
    Resolution,
)
from app.models.idea import Idea
from app.models.notification import Notification
from app.models.project import Project
from app.models.user import User
from app.notifications import access, preferences
from app.notifications.excerpt import comment_excerpt
from app.notifications.fanout import usable_address
from app.notifications.unsubscribe import make_token
from app.schemas.notifications import UnsubscribeScope
from app.services.refs import idea_key
from app.services.sql import any_of

__all__ = [
    "DIGEST_LINE_LIMIT",
    "NOTHING_LEFT",
    "NO_LONGER_APPLIES",
    "OUT_OF_DATE",
    "TURNED_OFF",
    "UNUSABLE_ADDRESS",
    "Cancelled",
    "OutboxRow",
    "Prepared",
    "prepare",
]

UNUSABLE_ADDRESS: Final = "Not sent: unusable address"
OUT_OF_DATE: Final = "Not sent: out of date"
NO_LONGER_APPLIES: Final = "Not sent: no longer applies"
NOTHING_LEFT: Final = "Not sent: nothing left to send"
TURNED_OFF: Final = "Not sent: turned off by the recipient"

DIGEST_LINE_LIMIT: Final = 50
SOMEONE: Final = "Someone"


@dataclass(frozen=True, slots=True)
class OutboxRow:
    """The claimed row, as the worker read it."""

    id: UUID
    type: EmailType
    attempts: int
    max_attempts: int
    created_at: datetime
    message_id: str
    recipient_user_id: UUID | None = None
    to_address: str | None = None
    requested_by_id: UUID | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)
    idea_id: UUID | None = None
    """Phase 4: the idea a public submitter's email is about (those two types only)."""


@dataclass(frozen=True, slots=True)
class Prepared:
    address: str
    content: EmailContent


@dataclass(frozen=True, slots=True)
class Cancelled:
    reason: str


class _Context:
    def __init__(self, db: AsyncSession, settings: Settings, now: datetime) -> None:
        self.db = db
        self.settings = settings
        self.now = now
        self.links = Links(settings.public_base_url)
        self.host = message_id_domain(settings)

    def day(self, moment: datetime) -> str:
        return format_day(moment, self.settings.tz, now=self.now)

    def moment(self, moment: datetime) -> str:
        return format_moment(moment, self.settings.tz, self.settings.timezone, now=self.now)

    def same_day(self, moment: datetime) -> bool:
        tz = self.settings.tz
        return moment.astimezone(tz).date() == self.now.astimezone(tz).date()

    def idea(self, idea: Idea, project: Project) -> IdeaInfo:
        return IdeaInfo(
            key=idea_key(idea, project),
            title=idea.title,
            project=project.name,
            status=status_label(project.status_labels, idea.status, idea.resolution),
            url=self.links.idea(idea_key(idea, project)),
        )

    async def names(self, user_ids: Sequence[UUID | None]) -> dict[UUID, str]:
        wanted = [user_id for user_id in dict.fromkeys(user_ids) if user_id is not None]
        if not wanted:
            return {}
        rows = await self.db.execute(
            select(User.id, User.display_name).where(any_of(User.id, wanted))
        )
        return dict(rows.all())


async def prepare(
    db: AsyncSession,
    settings: Settings,
    email: OutboxRow,
    *,
    now: datetime,
    branding: Branding = DEFAULT_BRANDING,
) -> Prepared | Cancelled:
    """The email to send now, or why it must not be sent (without contacting SMTP)."""
    context = _Context(db, settings, now)
    user: User | None = None
    if email.recipient_user_id is not None:
        user = await db.get(User, email.recipient_user_id)
        if user is None or not user.is_active or user.is_service_account:
            return Cancelled(NO_LONGER_APPLIES)
        address = user.email
    else:
        address = email.to_address or ""
    if not usable_address(address):
        return Cancelled(UNUSABLE_ADDRESS)
    if now - email.created_at >= max_age(email.type):
        return Cancelled(OUT_OF_DATE)
    result: EmailContent | Cancelled
    match email.type:
        case EmailType.TEST:
            result = await _test(context, email, branding)
        case EmailType.DIGEST:
            assert user is not None  # noqa: S101 - digests are for users
            result = await _digest(context, email, user, branding)
        case EmailType.SUBMISSION_RECEIVED | EmailType.SUBMISSION_STATUS_CHANGED:
            result = await _submission(context, email)
        case _:
            if user is None:
                return Cancelled(NO_LONGER_APPLIES)
            result = await _notification(context, email, user, branding)
    if isinstance(result, Cancelled):
        return result
    return Prepared(address=address, content=result)


# --- One notification -------------------------------------------------------------------
async def _load_idea(db: AsyncSession, idea_id: UUID) -> tuple[Idea, Project] | None:
    row = (
        await db.execute(
            select(Idea, Project)
            .join(Project, Project.id == Idea.project_id)
            .where(Idea.id == idea_id)
        )
    ).first()
    return None if row is None else (row[0], row[1])


async def _notification(
    context: _Context, email: OutboxRow, user: User, branding: Branding
) -> EmailContent | Cancelled:
    db = context.db
    notification = await db.scalar(select(Notification).where(Notification.email_id == email.id))
    if notification is None:
        return Cancelled(NO_LONGER_APPLIES)
    found = await _load_idea(db, notification.idea_id)
    if found is None:
        return Cancelled(NO_LONGER_APPLIES)
    idea, project = found
    comment = await db.get(Comment, notification.comment_id) if notification.comment_id else None
    recipient = (await access.recipients(db, idea, project, [user.id])).get(user.id)
    required_open = await _required_open(db, notification.type, idea)
    if recipient is None or not access.applies(
        notification.type,
        recipient,
        idea,
        payload=notification.payload,
        comment=comment,
        now=context.now,
        required_open=required_open,
    ):
        return Cancelled(NO_LONGER_APPLIES)
    if await preferences.mode_of(db, user.id, notification.type) is NotificationMode.OFF:
        return Cancelled(TURNED_OFF)
    names = await context.names([notification.actor_id])
    actor = names.get(notification.actor_id, SOMEONE) if notification.actor_id else SOMEONE
    info = context.idea(idea, project)
    token = make_token(context.settings, user.id, UnsubscribeScope(notification.type.value))
    base = {
        "preferences_url": context.links.preferences(),
        "unsubscribe_url": context.links.unsubscribe_page(token),
        "unsubscribe_label": TYPE_LABELS[notification.type],
        "unsubscribe_all_url": _unsubscribe_all_url(context, user),
        "list_unsubscribe_url": context.links.unsubscribe_api(token),
        "references": f"<idea-{idea.id}@{context.host}>",
    }
    title = subject_title(idea.title)
    key = info.key
    evaluate = Button("Evaluate", context.links.idea(key, evaluate=True))
    open_idea = Button("Open the idea", info.url)
    payload = notification.payload
    match notification.type:
        case NotificationType.OWNER_ASSIGNED:
            return EmailContent(
                template="owner_assigned",
                subject=f'[{key}] You\'re now the owner of "{title}"',
                preheader=f"{actor} made you the owner of {key}.",
                context={"actor": actor, "idea": info},
                button=open_idea,
                reason=f"You're the owner of {key}.",
                **base,
            )
        case NotificationType.EVALUATOR_INVITED:
            due_at = idea.evaluation_due_at
            by = f" by {context.day(due_at)}" if due_at else ""
            return EmailContent(
                template="evaluator_invited",
                subject=f'[{key}] Please evaluate "{title}"{by}',
                preheader=f"{actor} asked you to evaluate {key}{by}.",
                context={
                    "actor": actor,
                    "idea": info,
                    "due": context.moment(due_at) if due_at else None,
                },
                button=evaluate,
                reason=f"You're evaluating {key}.",
                **base,
            )
        case NotificationType.EVALUATION_REMINDER:
            due_at = access.parse_time(payload.get("due_at"))
            assert due_at is not None  # noqa: S101 - checked by access.applies
            today = context.same_day(due_at)
            day = context.day(due_at)
            when = f"today, {day}" if today else day
            return EmailContent(
                template="evaluation_reminder",
                subject=f'[{key}] Reminder: your evaluation of "{title}" is due {when}',
                preheader=f"Your evaluation of {key} is due {when}.",
                context={
                    "idea": info,
                    "due": context.moment(due_at),
                    "due_day": day,
                    "due_today": today,
                },
                button=evaluate,
                reason=f"You're evaluating {key}.",
                **base,
            )
        case NotificationType.EVALUATIONS_COMPLETE:
            count = max(1, int(payload.get("evaluator_count") or 1))
            headline = "The evaluation is in" if count == 1 else f"All {count} evaluations are in"
            return EmailContent(
                template="evaluations_complete",
                subject=f'[{key}] {headline} for "{title}"',
                preheader=f"{headline} for {key}.",
                context={"idea": info, "count": count},
                button=open_idea,
                reason=f"You're the owner of {key}.",
                **base,
            )
        case NotificationType.STATUS_CHANGED:
            from_label, to_label = _labels(project, payload)
            reason = f"You watch {key}."
            if idea.owner_id == user.id:
                reason = f"You're the owner of {key}."
            elif idea.researcher_id == user.id:  # Phase 8b guest review N3
                reason = f"You're researching {key}."
            elif recipient.resource.idea is not None and recipient.resource.idea.my_evaluation:
                reason = f"You're evaluating {key}."
            return EmailContent(
                template="status_changed",
                subject=f'[{key}] "{title}" moved to {to_label}',
                preheader=f"{actor} moved {key} from {from_label} to {to_label}.",
                context={
                    "actor": actor,
                    "idea": info,
                    "from_label": from_label,
                    "to_label": to_label,
                },
                button=open_idea,
                reason=reason,
                **base,
            )
        case NotificationType.COMMENT | NotificationType.MENTION:
            assert comment is not None  # noqa: S101 - checked by access.applies
            excerpt = comment_excerpt(comment.body_md)
            mention = notification.type is NotificationType.MENTION
            return EmailContent(
                template="mention" if mention else "comment",
                subject=(
                    f'[{key}] {actor} mentioned you on "{title}"'
                    if mention
                    else f'[{key}] {actor} commented on "{title}"'
                ),
                preheader=excerpt[:120],
                context={"actor": actor, "idea": info, "excerpt": excerpt},
                button=Button("Reply", context.links.idea(key, comment_id=comment.id)),
                reason=(
                    f"You were mentioned in a comment on {key}." if mention else f"You watch {key}."
                ),
                **base,
            )
        case NotificationType.RESEARCHER_ASSIGNED:
            # Phase 8b: the research due date now (the request's may have changed since).
            due_at = idea.research_due_at
            by = f" by {context.day(due_at)}" if due_at else ""
            return EmailContent(
                template="researcher_assigned",
                subject=f'[{key}] Please research "{title}"{by}',
                preheader=f"{actor} asked you to research {key}{by}.",
                context={
                    "actor": actor,
                    "idea": info,
                    "due": context.moment(due_at) if due_at else None,
                    # Review S2: the guest line only for column R (no view of the project).
                    "guest": not can(recipient.principal, Rule.PROJECT_VIEW, recipient.resource),
                    # UX review m10: without an owner, a project admin moves it on.
                    "has_owner": idea.owner_id is not None,
                },
                button=Button(
                    "Open the research checklist", context.links.idea(key, research=True)
                ),
                reason=f"You're researching {key}.",
                **base,
            )
        case NotificationType.RESEARCH_REMINDER:
            due_at = access.parse_time(payload.get("due_at"))
            assert due_at is not None  # noqa: S101 - checked by access.applies
            today = context.same_day(due_at)
            day = context.day(due_at)
            when = f"today, {day}" if today else day
            as_owner = bool(payload.get("as_owner"))
            return EmailContent(
                template="research_reminder",
                subject=f'[{key}] Reminder: research for "{title}" is due {when}',
                preheader=f"Research for {key} is due {when}.",
                context={
                    "idea": info,
                    "due": context.moment(due_at),
                    "due_day": day,
                    "due_today": today,
                    "open_items": plural(required_open or 1, "required item"),
                },
                button=Button(
                    "Open the research checklist", context.links.idea(key, research=True)
                ),
                reason=f"You own {key}." if as_owner else f"You're researching {key}.",
                **base,
            )


async def _required_open(db: AsyncSession, type_: NotificationType, idea: Idea) -> int | None:
    """Phase 8b: the idea's open required research items, for a research reminder's
    send-time check (no query for other types)."""
    if type_ is not NotificationType.RESEARCH_REMINDER:
        return None
    from app.services.research import required_open_count

    return await required_open_count(db, idea)


def _unsubscribe_all_url(context: _Context, user: User) -> str:
    """The footer's "Unsubscribe from all email" link: the only token scoped to ``all``
    (a type's or the digest's link can't turn off every email, contract section 3.5)."""
    return context.links.unsubscribe_page(
        make_token(context.settings, user.id, UnsubscribeScope.ALL)
    )


def _labels(project: Project, payload: Mapping[str, Any]) -> tuple[str, str]:
    def label(status: object, resolution: object) -> str:
        return status_label(
            project.status_labels,
            IdeaStatus(str(status)),
            Resolution(str(resolution)) if resolution else None,
        )

    return (
        label(payload.get("from_status"), payload.get("from_resolution")),
        label(payload.get("to_status"), payload.get("to_resolution")),
    )


# --- The daily digest ----------------------------------------------------------------------
def _digest_line(
    context: _Context,
    notification: Notification,
    project: Project,
    actor: str,
    comment: Comment | None,
) -> str:
    payload = notification.payload
    match notification.type:
        case NotificationType.OWNER_ASSIGNED:
            return f"{actor} made you the owner"
        case NotificationType.EVALUATOR_INVITED:
            return f"{actor} asked you to evaluate it"
        case NotificationType.EVALUATION_REMINDER:
            due_at = access.parse_time(payload.get("due_at"))
            return f"Your evaluation is due {context.day(due_at)}" if due_at else "Reminder"
        case NotificationType.EVALUATIONS_COMPLETE:
            count = max(1, int(payload.get("evaluator_count") or 1))
            return "The evaluation is in" if count == 1 else f"All {count} evaluations are in"
        case NotificationType.STATUS_CHANGED:
            from_label, to_label = _labels(project, payload)
            return f"{actor} moved it from {from_label} to {to_label}"
        case NotificationType.COMMENT:
            excerpt = comment_excerpt(comment.body_md) if comment else ""
            return f"{actor} commented: “{excerpt}”"
        case NotificationType.MENTION:
            excerpt = comment_excerpt(comment.body_md) if comment else ""
            return f"{actor} mentioned you: “{excerpt}”"
        case NotificationType.RESEARCHER_ASSIGNED:
            due_at = access.parse_time(payload.get("due_at"))
            due = f" (due {context.day(due_at)})" if due_at else ""
            return f"{actor} asked you to research it{due}"
        case NotificationType.RESEARCH_REMINDER:
            due_at = access.parse_time(payload.get("due_at"))
            return f"Research due {context.day(due_at)}" if due_at else "Research reminder"


async def _digest(
    context: _Context, email: OutboxRow, user: User, branding: Branding
) -> EmailContent | Cancelled:
    db = context.db
    rows = (
        await db.execute(
            select(Notification, Idea, Project)
            .join(Idea, Idea.id == Notification.idea_id)
            .join(Project, Project.id == Idea.project_id)
            .where(Notification.email_id == email.id)
            .order_by(Notification.created_at.desc(), Notification.id.desc())
        )
    ).all()
    modes = await preferences.all_modes(db, user.id)
    comment_ids = [n.comment_id for n, _, _ in rows if n.comment_id is not None]
    comments = (
        {c.id: c for c in await db.scalars(select(Comment).where(any_of(Comment.id, comment_ids)))}
        if comment_ids
        else {}
    )
    by_idea: dict[UUID, list[tuple[Notification, Idea, Project]]] = {}
    for row in rows:
        by_idea.setdefault(row[1].id, []).append(row)
    kept: list[tuple[Notification, Idea, Project]] = []
    for items in by_idea.values():
        idea, project = items[0][1], items[0][2]
        recipient = (await access.recipients(db, idea, project, [user.id])).get(user.id)
        if recipient is None:
            continue
        for notification, _, _ in items:
            comment = comments.get(notification.comment_id) if notification.comment_id else None
            if modes[notification.type] is NotificationMode.OFF:
                continue
            if access.applies(
                notification.type,
                recipient,
                idea,
                payload=notification.payload,
                comment=comment,
                now=context.now,
                required_open=await _required_open(db, notification.type, idea),
            ):
                kept.append((notification, idea, project))
    if not kept:
        return Cancelled(NOTHING_LEFT)
    names = await context.names([n.actor_id for n, _, _ in kept])
    groups: dict[UUID, dict[str, Any]] = {}
    shown = 0
    for notification, idea, project in kept:  # newest first: newest idea activity first
        if shown >= DIGEST_LINE_LIMIT:
            break
        group = groups.setdefault(idea.id, {"idea": context.idea(idea, project), "lines": []})
        lines: list[str] = group["lines"]
        actor = names.get(notification.actor_id, SOMEONE) if notification.actor_id else SOMEONE
        comment = comments.get(notification.comment_id) if notification.comment_id else None
        lines.append(_digest_line(context, notification, project, actor, comment))
        shown += 1
    idea_count = len({idea.id for _, idea, _ in kept})
    summary = f"{plural(len(kept), 'update')} on {plural(idea_count, 'idea')} you follow."
    token = make_token(context.settings, user.id, UnsubscribeScope.DIGEST)
    return EmailContent(
        template="digest",
        subject=(
            f"{branding.product_name} digest: {plural(len(kept), 'update')} on "
            f"{plural(idea_count, 'idea')}"
        ),
        preheader=summary,
        context={
            "groups": list(groups.values()),
            "summary": summary,
            "more": len(kept) - shown,
            "inbox_url": context.links.inbox(),
        },
        button=Button("Open your inbox", context.links.inbox()),
        reason="You get one email a day with updates you chose to receive as a digest.",
        preferences_url=context.links.preferences(),
        unsubscribe_url=context.links.unsubscribe_page(token),
        unsubscribe_label="the daily digest",
        unsubscribe_all_url=_unsubscribe_all_url(context, user),
        list_unsubscribe_url=context.links.unsubscribe_api(token),
    )


# --- Test and (Phase 4) public submitter emails -------------------------------------------
async def _test(context: _Context, email: OutboxRow, branding: Branding) -> EmailContent:
    names = await context.names([email.requested_by_id])
    sent_by = names.get(email.requested_by_id) if email.requested_by_id else None
    return EmailContent(
        template="test",
        subject=f"{branding.product_name} test email",
        preheader=f"Email from {branding.product_name} works.",
        context={
            "base_url": context.settings.public_base_url,
            "sent_by": sent_by,
            "sent_at": context.moment(email.created_at),
        },
        reason="An administrator sent this to check the email settings.",
    )


async def _submission(context: _Context, email: OutboxRow) -> EmailContent | Cancelled:
    """Public submitter emails (contract-phase4 section 3.8): rendered from the idea's
    ``public_submissions`` row now (no notification row, no user preferences), by
    :func:`app.public.emails.submitter_email`."""
    from app.public.emails import submitter_email

    found = await submitter_email(context.db, context.settings, email, now=context.now)
    return Cancelled(found) if isinstance(found, str) else found
