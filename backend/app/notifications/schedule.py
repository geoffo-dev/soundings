"""The hourly ``notification_schedule`` job: evaluation reminders, then daily digests,
then the cleanup (contract-phase3 sections 3.6, 3.7 and 3.9).

Everything follows the instance time zone (``SOUNDINGS_TIMEZONE``) and takes ``now``
as an argument, so tests drive it with any clock. Both jobs are idempotent: reminders
through their notification ``dedupe_key``, digests through the outbox
``idempotency_key`` (one per person and local date), so two runs in one hour do the
work once.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Final
from uuid import UUID

from sqlalchemy import ColumnElement, and_, delete, exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db import SessionMaker, session_scope
from app.email import outbox
from app.mcp import audit as mcp_audit
from app.models.enums import (
    EmailStatus,
    EmailType,
    EvaluationStatus,
    IdeaStatus,
    NotificationMode,
    NotificationType,
)
from app.models.evaluation import Evaluation
from app.models.idea import Idea, IdeaEvaluator
from app.models.notification import Notification, OutboundEmail
from app.models.project import Project
from app.models.user import User
from app.notifications import access, preferences
from app.notifications.fanout import NotificationWriter, usable_address
from app.public import retention as public_retention
from app.services import brand_assets
from app.services.sql import any_of

__all__ = [
    "DIGEST_WINDOW",
    "EMAIL_RETENTION",
    "FAILED_EMAIL_RETENTION",
    "NOTIFICATION_RETENTION",
    "ScheduleResult",
    "build_digests",
    "cleanup",
    "digest_key",
    "run_schedule",
    "send_reminders",
]

logger = logging.getLogger("soundings.notifications")

DIGEST_WINDOW: Final = timedelta(days=7)
"""Pending digest items older than this are never collected (and the cleanup turns
them off), so nothing is mailed twice and a long outage doesn't send a month of news."""
EMAIL_RETENTION: Final = timedelta(days=30)
FAILED_EMAIL_RETENTION: Final = timedelta(days=90)
NOTIFICATION_RETENTION: Final = timedelta(days=90)


@dataclass(frozen=True, slots=True)
class ScheduleResult:
    reminders: int = 0
    digests: int = 0
    cleaned: bool = False


def digest_key(user_id: UUID, local_date: date) -> str:
    return f"digest:{user_id}:{local_date.isoformat()}"


def _local_hour_start(day: date, hour: int, settings: Settings) -> datetime:
    return datetime.combine(day, time(hour), tzinfo=settings.tz)


# --- Reminders ----------------------------------------------------------------------------
async def send_reminders(db: AsyncSession, settings: Settings, now: datetime) -> int:
    """Today's reminders (section 3.7): for due date *d* and offset *n*, on local day
    ``d - n`` from the digest hour, while ``now`` is before the due time, to pending
    evaluators invited before that hour. Returns how many people were reminded."""
    if not settings.reminder_days:
        return 0
    today = now.astimezone(settings.tz).date()
    fire = _local_hour_start(today, settings.digest_hour, settings)
    if fire > now:
        return 0
    offsets = {today + timedelta(days=n): n for n in settings.reminder_days}
    horizon = _local_hour_start(max(offsets) + timedelta(days=1), 0, settings)
    rows = (
        await db.execute(
            select(Idea, Project)
            .join(Project, Project.id == Idea.project_id)
            .where(
                Idea.evaluation_due_at.is_not(None),
                Idea.evaluation_closed_at.is_(None),
                Idea.status != IdeaStatus.CLOSED,
                Idea.evaluation_due_at > now,
                Idea.evaluation_due_at < horizon,
            )
            .order_by(Idea.evaluation_due_at, Idea.id)
        )
    ).all()
    writer = NotificationWriter(db, settings, now=now)
    reminded = 0
    for idea, project in rows:
        assert idea.evaluation_due_at is not None  # noqa: S101 - filtered above
        due_day = idea.evaluation_due_at.astimezone(settings.tz).date()
        days_before = offsets.get(due_day)
        if days_before is None:
            continue
        pending = list(
            await db.scalars(
                select(IdeaEvaluator.user_id).where(
                    IdeaEvaluator.idea_id == idea.id,
                    IdeaEvaluator.invited_at < fire,
                    ~exists().where(
                        Evaluation.idea_id == IdeaEvaluator.idea_id,
                        Evaluation.evaluator_id == IdeaEvaluator.user_id,
                        Evaluation.status == EvaluationStatus.SUBMITTED,
                    ),
                )
            )
        )
        payload = {"due_at": idea.evaluation_due_at.isoformat(), "days_before": days_before}
        found = await access.recipients(db, idea, project, pending)
        recipients = [
            recipient
            for recipient in found.values()
            if access.applies(
                NotificationType.EVALUATION_REMINDER, recipient, idea, payload=payload, now=now
            )
        ]
        reminded += len(
            await writer.notify(
                NotificationType.EVALUATION_REMINDER,
                idea,
                recipients,
                actor_id=None,
                dedupe_key=f"evaluation_reminder:{idea.id}:{due_day.isoformat()}:{days_before}",
                payload=payload,
            )
        )
    return reminded


# --- Digests ------------------------------------------------------------------------------
def _pending(now: datetime) -> list[ColumnElement[bool]]:
    return [
        Notification.email_mode == NotificationMode.DIGEST,
        Notification.email_id.is_(None),
        Notification.created_at <= now,
        Notification.created_at > now - DIGEST_WINDOW,
    ]


async def build_digests(sessionmaker: SessionMaker, settings: Settings, now: datetime) -> int:
    """Once the local hour has reached the digest hour: one digest per person with
    pending items and no digest yet for the local date (each in its own transaction).
    Returns how many digests were queued."""
    if not settings.smtp_configured:
        return 0
    local = now.astimezone(settings.tz)
    if local.hour < settings.digest_hour:
        return 0
    async with sessionmaker() as db:
        user_ids = list(
            await db.scalars(
                select(Notification.user_id)
                .where(*_pending(now))
                .group_by(Notification.user_id)
                .order_by(Notification.user_id)
            )
        )
        keys = {user_id: digest_key(user_id, local.date()) for user_id in user_ids}
        done = (
            set(
                await db.scalars(
                    select(OutboundEmail.idempotency_key).where(
                        OutboundEmail.idempotency_key.in_(list(keys.values()))
                    )
                )
            )
            if keys
            else set()
        )
    queued = 0
    for user_id in user_ids:
        if keys[user_id] in done:
            continue
        async with session_scope(sessionmaker) as db:
            if await _digest_for(db, settings, user_id, local.date(), now):
                queued += 1
    return queued


async def _digest_for(
    db: AsyncSession, settings: Settings, user_id: UUID, local_date: date, now: datetime
) -> bool:
    user = await db.get(User, user_id)
    items = (
        await db.execute(
            select(Notification, Idea, Project)
            .join(Idea, Idea.id == Notification.idea_id)
            .join(Project, Project.id == Idea.project_id)
            .where(Notification.user_id == user_id, *_pending(now))
            .order_by(Notification.created_at, Notification.id)
            .with_for_update(of=Notification, skip_locked=True)
        )
    ).all()
    if not items:
        return False
    modes = await preferences.all_modes(db, user_id)
    keep: list[UUID] = []
    drop: list[UUID] = []
    deliverable = (
        user is not None
        and user.is_active
        and not user.is_service_account
        and not user.is_break_glass
        and usable_address(user.email)
    )
    viewable: dict[UUID, bool] = {}
    for notification, idea, project in items:
        if not deliverable:
            drop.append(notification.id)
            continue
        if idea.id not in viewable:
            viewable[idea.id] = bool(await access.recipients(db, idea, project, [user_id]))
        if (
            notification.read_at is not None
            or modes[notification.type] is NotificationMode.OFF
            or not viewable[idea.id]
        ):
            drop.append(notification.id)
        else:
            keep.append(notification.id)
    if drop:
        await db.execute(
            update(Notification)
            .where(any_of(Notification.id, drop))
            .values(email_mode=NotificationMode.OFF)
            .execution_options(synchronize_session=False)
        )
    if not keep:
        return False
    ids = await outbox.enqueue(
        db,
        settings,
        [
            outbox.NewEmail(
                type=EmailType.DIGEST,
                recipient_user_id=user_id,
                idempotency_key=digest_key(user_id, local_date),
            )
        ],
        now=now,
    )
    if not ids:
        return False  # another run queued today's digest first
    await db.execute(
        update(Notification)
        .where(any_of(Notification.id, keep))
        .values(email_id=ids[0])
        .execution_options(synchronize_session=False)
    )
    return True


# --- Cleanup ------------------------------------------------------------------------------
async def cleanup(db: AsyncSession, now: datetime) -> None:
    """Hourly, in this order: prune old outbox rows; turn off digest items older than the
    window (including those whose digest row was just pruned); prune old notifications.
    Indexed: ``ix_outbound_email_status_updated_at``, ``ix_notifications_digest_pending``
    and ``ix_notifications_created_at``."""
    await db.execute(
        delete(OutboundEmail).where(
            OutboundEmail.status.in_([EmailStatus.SENT, EmailStatus.CANCELLED]),
            OutboundEmail.updated_at < now - EMAIL_RETENTION,
        )
    )
    await db.execute(
        delete(OutboundEmail).where(
            OutboundEmail.status == EmailStatus.FAILED,
            OutboundEmail.updated_at < now - FAILED_EMAIL_RETENTION,
        )
    )
    await db.execute(
        update(Notification)
        .where(
            and_(
                Notification.email_mode == NotificationMode.DIGEST,
                Notification.email_id.is_(None),
                Notification.created_at <= now - DIGEST_WINDOW,
            )
        )
        .values(email_mode=NotificationMode.OFF)
        .execution_options(synchronize_session=False)
    )
    await db.execute(
        delete(Notification).where(Notification.created_at < now - NOTIFICATION_RETENTION)
    )


# --- The job ------------------------------------------------------------------------------
async def run_schedule(
    sessionmaker: SessionMaker, settings: Settings, now: datetime
) -> ScheduleResult:
    """Reminders, then digests (so a reminder in digest mode makes today's digest), then
    the cleanup. The cleanup runs every hour (it is idempotent, and indexed): tied to
    one hour of the day, a late run or a day whose digest hour falls in a DST gap
    would skip it."""
    async with session_scope(sessionmaker, settings=settings) as db:
        reminders = await send_reminders(db, settings, now)
    digests = await build_digests(sessionmaker, settings, now)
    async with session_scope(sessionmaker) as db:
        await cleanup(db, now)
    async with session_scope(sessionmaker) as db:
        # Phase 4: ALTCHA replay rows, unconfirmed submissions, submitter retention.
        await public_retention.cleanup(db, now)
    async with session_scope(sessionmaker) as db:
        # Phase 4: brand images no profile has used for 24 hours.
        await brand_assets.delete_unreferenced(db, now)
    async with session_scope(sessionmaker) as db:
        # Phase 5: the MCP call trail older than 90 days (other audit entries stay).
        await mcp_audit.delete_expired_calls(db, now)
    if reminders or digests:
        logger.info("notification schedule ran", extra={"reminders": reminders, "digests": digests})
    return ScheduleResult(reminders=reminders, digests=digests, cleaned=True)
