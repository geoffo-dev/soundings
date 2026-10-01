"""The notification fan-out (contract-phase3 section 3.3).

Services queue what happened: :func:`queue_event` for each activity event (called by
:func:`app.services.activity.emit`) and :func:`queue_mentions` for people newly
@mentioned in a comment. The fan-out runs **once per unit of work, after its last write
and before commit** (a before-commit hook of :func:`app.db.session_scope`), so the
event, its notifications, their outbox rows and jobs commit or roll back together, and
every check and payload reads the state after all of the request's writes (an
invitation carries the due date the same request set).

Per candidate recipient: drop the actor, inactive users, service accounts, the
break-glass account and anyone failing ``idea.view`` (:func:`.access.recipients`);
check the type's condition (:func:`.access.applies`); insert the notification
(``ON CONFLICT (user_id, dedupe_key) DO NOTHING``); resolve the email mode
(preference; ``off`` without SMTP, for an unusable address, or past the mention cap)
and, for ``immediate``, queue the email in the same transaction.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.headerregistry import Address
from typing import Any, Final
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, is_mail_address
from app.db import before_commit, session_settings
from app.email import outbox
from app.models.activity import ActivityEvent, Comment
from app.models.base import utcnow
from app.models.enums import EmailType, NotificationMode, NotificationType
from app.models.idea import Idea, IdeaWatcher
from app.models.notification import Notification
from app.models.project import Project
from app.notifications import access, preferences
from app.notifications.access import Recipient
from app.schemas.admin_users import is_reserved_email

__all__ = [
    "MENTION_EMAIL_CAP",
    "MENTION_EMAIL_WINDOW",
    "NotificationWriter",
    "fan_out",
    "queue_event",
    "queue_mentions",
    "usable_address",
]

MENTION_EMAIL_CAP: Final = 50
"""Mention notifications of one author emailed per rolling hour; beyond: in-app only."""
MENTION_EMAIL_WINDOW: Final = timedelta(hours=1)

_EVENTS: Final = "soundings.notify.events"
_MENTIONS: Final = "soundings.notify.mentions"
_HOOK: Final = "notifications"


@dataclass(frozen=True, slots=True)
class _Mentions:
    comment_id: UUID
    author_id: UUID | None
    user_ids: tuple[UUID, ...]


def queue_event(db: AsyncSession, event: ActivityEvent) -> None:
    """Notify about ``event`` when the unit of work commits."""
    db.info.setdefault(_EVENTS, []).append(event)
    before_commit(db, _HOOK, _hook)


def queue_mentions(
    db: AsyncSession, comment: Comment, author_id: UUID | None, user_ids: Iterable[UUID]
) -> None:
    """Notify people newly mentioned in ``comment`` when the unit of work commits."""
    wanted = tuple(dict.fromkeys(user_ids))
    if wanted:
        db.info.setdefault(_MENTIONS, []).append(_Mentions(comment.id, author_id, wanted))
        before_commit(db, _HOOK, _hook)


async def _hook(db: AsyncSession) -> None:
    await fan_out(db, settings=session_settings(db))


def usable_address(address: str) -> bool:
    """One plain ASCII address that can receive mail (not ``.invalid``) and that the
    email package reads back exactly (contract-phase3 section 3.9 step 2)."""
    if not is_mail_address(address) or is_reserved_email(address):
        return False
    try:
        return Address(addr_spec=address).addr_spec == address
    except (ValueError, IndexError, TypeError):
        return False


class NotificationWriter:
    """Inserts notifications and their immediate emails for one unit of work.

    ``settings`` ``None`` (or SMTP not configured) records every notification with
    ``email_mode = off`` and queues nothing (in-app only).
    """

    def __init__(
        self, db: AsyncSession, settings: Settings | None, *, now: datetime | None = None
    ) -> None:
        self.db = db
        self.settings = settings
        self.email = settings is not None and settings.smtp_configured
        self.now = now or utcnow()
        self._mention_budget: dict[UUID, int] = {}

    async def _mention_allowance(self, author_id: UUID | None) -> int:
        if author_id is None:
            return MENTION_EMAIL_CAP
        if author_id not in self._mention_budget:
            emailed = await self.db.scalar(
                select(func.count())
                .select_from(Notification)
                .where(
                    Notification.type == NotificationType.MENTION,
                    Notification.actor_id == author_id,
                    Notification.created_at > self.now - MENTION_EMAIL_WINDOW,
                    Notification.email_mode != NotificationMode.OFF,
                )
            )
            self._mention_budget[author_id] = max(0, MENTION_EMAIL_CAP - int(emailed or 0))
        return self._mention_budget[author_id]

    async def _modes(
        self, type_: NotificationType, recipients: list[Recipient], actor_id: UUID | None
    ) -> dict[UUID, NotificationMode]:
        if not self.email:
            return dict.fromkeys((r.id for r in recipients), NotificationMode.OFF)
        chosen = await preferences.modes_for(self.db, (r.id for r in recipients), type_)
        modes: dict[UUID, NotificationMode] = {}
        for recipient in recipients:
            mode = chosen[recipient.id]
            if not usable_address(recipient.user.email):
                mode = NotificationMode.OFF
            modes[recipient.id] = mode
        if type_ is NotificationType.MENTION:
            allowance = await self._mention_allowance(actor_id)
            for user_id, mode in modes.items():
                if mode is NotificationMode.OFF:
                    continue
                if allowance <= 0:
                    modes[user_id] = NotificationMode.OFF
                else:
                    allowance -= 1
            if actor_id is not None:
                self._mention_budget[actor_id] = allowance
        return modes

    async def notify(
        self,
        type_: NotificationType,
        idea: Idea,
        recipients: Iterable[Recipient],
        *,
        actor_id: UUID | None,
        dedupe_key: str,
        payload: Mapping[str, Any] | None = None,
        comment_id: UUID | None = None,
    ) -> list[UUID]:
        """Insert one notification per recipient (skipping existing dedupe keys) and
        queue the immediate emails; returns who was newly notified."""
        people = list({r.id: r for r in recipients}.values())
        if not people:
            return []
        modes = await self._modes(type_, people, actor_id)
        rows = [
            {
                "id": uuid4(),
                "user_id": recipient.id,
                "type": type_,
                "idea_id": idea.id,
                "actor_id": actor_id,
                "comment_id": comment_id,
                "payload": dict(payload or {}),
                "dedupe_key": dedupe_key,
                "email_mode": modes[recipient.id],
                "created_at": self.now,
            }
            for recipient in people
        ]
        result = await self.db.execute(
            insert(Notification)
            .values(rows)
            .on_conflict_do_nothing(index_elements=["user_id", "dedupe_key"])
            .returning(Notification.id, Notification.user_id)
        )
        inserted = dict(result.all())  # notification id -> user id
        immediate = [
            (notification_id, user_id)
            for notification_id, user_id in inserted.items()
            if modes[user_id] is NotificationMode.IMMEDIATE
        ]
        if immediate:
            assert self.settings is not None  # noqa: S101 - immediate needs email on
            await outbox.enqueue_for_notifications(
                self.db, self.settings, EmailType(type_.value), immediate, now=self.now
            )
        return list(inserted.values())


# --- The fan-out ---------------------------------------------------------------------------
async def fan_out(
    db: AsyncSession, *, settings: Settings | None, now: datetime | None = None
) -> None:
    """Notify about everything queued in this unit of work (then forget it)."""
    events: list[ActivityEvent] = db.info.pop(_EVENTS, [])
    mentions: list[_Mentions] = db.info.pop(_MENTIONS, [])
    if not events and not mentions:
        return
    await db.flush()
    writer = NotificationWriter(db, settings, now=now)
    mentioned: dict[UUID, set[UUID]] = {}
    for request in mentions:
        mentioned.setdefault(request.comment_id, set()).update(
            await _notify_mentions(writer, request)
        )
    for event in events:
        await _notify_event(writer, event, mentioned)


async def _idea(db: AsyncSession, idea_id: UUID | None) -> tuple[Idea, Project] | None:
    if idea_id is None:
        return None
    row = (
        await db.execute(
            select(Idea, Project)
            .join(Project, Project.id == Idea.project_id)
            .where(Idea.id == idea_id)
        )
    ).first()
    return None if row is None else (row[0], row[1])


async def _watchers(db: AsyncSession, idea_id: UUID) -> list[UUID]:
    return list(
        await db.scalars(
            select(IdeaWatcher.user_id)
            .where(IdeaWatcher.idea_id == idea_id)
            .order_by(IdeaWatcher.created_at, IdeaWatcher.user_id)
        )
    )


async def _candidates(
    writer: NotificationWriter,
    type_: NotificationType,
    idea: Idea,
    project: Project,
    user_ids: Iterable[UUID],
    *,
    actor_id: UUID | None,
    payload: Mapping[str, Any],
    comment: Comment | None = None,
) -> list[Recipient]:
    """Steps 1-2: not the actor, notifiable, ``idea.view``, the type's condition."""
    found = await access.recipients(
        writer.db, idea, project, (user_id for user_id in user_ids if user_id != actor_id)
    )
    return [
        recipient
        for recipient in found.values()
        if access.applies(type_, recipient, idea, payload=payload, comment=comment, now=writer.now)
    ]


async def _notify_mentions(writer: NotificationWriter, request: _Mentions) -> set[UUID]:
    """``mention`` notifications for people with a role in the idea's project."""
    db = writer.db
    comment = await db.get(Comment, request.comment_id)
    if comment is None or comment.deleted_at is not None:
        return set()
    found = await _idea(db, comment.idea_id)
    if found is None:
        return set()
    idea, project = found
    candidates = await _candidates(
        writer,
        NotificationType.MENTION,
        idea,
        project,
        request.user_ids,
        actor_id=request.author_id,
        payload={},
        comment=comment,
    )
    with_role = [recipient for recipient in candidates if recipient.resource.role is not None]
    await writer.notify(
        NotificationType.MENTION,
        idea,
        with_role,
        actor_id=request.author_id,
        dedupe_key=f"mention:{comment.id}",
        comment_id=comment.id,
    )
    # Everyone who has (now or from an earlier edit) a mention for this comment gets
    # no separate "comment" notification.
    return {recipient.id for recipient in with_role}


async def _notify_event(
    writer: NotificationWriter, event: ActivityEvent, mentioned: Mapping[UUID, set[UUID]]
) -> None:
    db = writer.db
    found = await _idea(db, event.idea_id)
    if found is None:
        return
    idea, project = found
    payload = event.payload
    actor_id = event.actor_id

    async def notify(
        type_: NotificationType,
        user_ids: Iterable[UUID],
        data: Mapping[str, Any],
        *,
        comment: Comment | None = None,
    ) -> None:
        recipients = await _candidates(
            writer,
            type_,
            idea,
            project,
            user_ids,
            actor_id=actor_id,
            payload=data,
            comment=comment,
        )
        await writer.notify(
            type_,
            idea,
            recipients,
            actor_id=actor_id,
            dedupe_key=f"{type_.value}:{event.id}",
            payload=data,
            comment_id=comment.id if comment is not None else None,
        )

    match event.type:
        case "owner_changed":
            new_owner = access.parse_uuid(payload.get("to_owner_id"))
            if new_owner is not None:
                await notify(NotificationType.OWNER_ASSIGNED, [new_owner], {})
        case "evaluator_added":
            evaluator = access.parse_uuid(payload.get("evaluator_id"))
            if evaluator is not None:
                due_at = idea.evaluation_due_at
                await notify(
                    NotificationType.EVALUATOR_INVITED,
                    [evaluator],
                    {"due_at": due_at.isoformat() if due_at else None},
                )
        case "evaluation_submitted" | "evaluator_removed":
            assigned, submitted = await access.submitted_count(db, idea.id)
            if assigned >= 1 and submitted == assigned and idea.owner_id is not None:
                await notify(
                    NotificationType.EVALUATIONS_COMPLETE,
                    [idea.owner_id],
                    {"evaluator_count": submitted},
                )
        case "status_changed":
            # The owner and evaluators always; watchers while they watch.
            people = [
                *([idea.owner_id] if idea.owner_id else []),
                *await access.evaluator_ids(db, idea.id),
                *await _watchers(db, idea.id),
            ]
            data = {
                key: payload.get(key)
                for key in ("from_status", "from_resolution", "to_status", "to_resolution")
            }
            await notify(NotificationType.STATUS_CHANGED, people, data)
            # Phase 4: an opted-in public submitter gets a submission_status_changed
            # email here (outbox row with to_address, no notification row).
        case "comment":
            comment = await db.get(Comment, event.comment_id) if event.comment_id else None
            if comment is not None:
                skip = mentioned.get(comment.id, set())
                watchers = [user for user in await _watchers(db, idea.id) if user not in skip]
                await notify(NotificationType.COMMENT, watchers, {}, comment=comment)
        case _:
            # idea created or edited, due date changed, evaluation closed or reopened:
            # no notifications (contract-phase3 section 3.3 notes).
            return
