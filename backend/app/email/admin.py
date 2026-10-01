"""Admin settings -> Email (contract-phase3 section 3.10): the effective SMTP settings
(credentials as "set" flags only), the test email, the outbox list and retry.

Callers check ``platform.configure_email`` first. Audit entries hold ids and flags,
never addresses (``email.test_send``, ``email.retry``).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Final
from uuid import UUID

from sqlalchemy import and_, func, or_, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.domain.principal import Principal
from app.email import outbox
from app.errors import ConflictProblem, NotFoundProblem, ProblemError
from app.models.base import utcnow
from app.models.enums import EmailStatus, EmailType
from app.models.idea import Idea
from app.models.notification import Notification, OutboundEmail
from app.models.project import Project
from app.notifications.fanout import usable_address
from app.notifications.inbox import decode_time_cursor
from app.notifications.unsubscribe import email_hint
from app.pagination import encode_cursor
from app.schemas.common import FieldError
from app.schemas.email import EmailConfig, OutboxEmail, OutboxEmailPage, OutboxStats
from app.services import audit
from app.services.refs import idea_ref
from app.services.sql import any_of
from app.services.summaries import user_refs

__all__ = [
    "TEST_EMAIL_LIMIT",
    "TEST_EMAIL_WINDOW",
    "email_config",
    "get_outbox_email",
    "list_outbox",
    "retry_all_failed",
    "retry_email",
    "send_test_email",
]

TEST_EMAIL_LIMIT: Final = 5
TEST_EMAIL_WINDOW: Final = timedelta(minutes=10)
_TEST_LOCK_SALT: Final = 0x7E57_E3A1


class SmtpNotConfiguredProblem(ConflictProblem):
    def __init__(self) -> None:
        super().__init__(
            "Email isn't set up: set smtp.host and smtp.from in the Helm values.",
            code="smtp_not_configured",
        )


async def _stats(db: AsyncSession, now: datetime) -> OutboxStats:
    status = OutboundEmail.status
    row = (
        await db.execute(
            select(
                func.count().filter(status == EmailStatus.QUEUED),
                func.count().filter(status == EmailStatus.SENDING),
                func.count().filter(status == EmailStatus.FAILED),
                func.count().filter(
                    status == EmailStatus.SENT, OutboundEmail.sent_at > now - timedelta(hours=24)
                ),
                func.min(OutboundEmail.created_at).filter(status == EmailStatus.QUEUED),
                func.max(OutboundEmail.sent_at),
            )
        )
    ).one()
    return OutboxStats(
        queued=row[0],
        sending=row[1],
        failed=row[2],
        sent_last_24h=row[3],
        oldest_queued_at=row[4],
        last_sent_at=row[5],
    )


async def email_config(db: AsyncSession, settings: Settings) -> EmailConfig:
    return EmailConfig(
        configured=settings.smtp_configured,
        host=settings.smtp_host,
        port=settings.smtp_port,
        security=settings.smtp_security,
        username_set=bool(settings.smtp_username and settings.smtp_username.get_secret_value()),
        password_set=bool(settings.smtp_password and settings.smtp_password.get_secret_value()),
        from_address=settings.smtp_from,
        from_name=settings.smtp_from_name,
        reply_to=settings.smtp_reply_to,
        ca_bundle=str(settings.smtp_ca_bundle) if settings.smtp_ca_bundle else None,
        timeout_seconds=settings.smtp_timeout,
        links_base_url=settings.public_base_url,
        timezone=settings.timezone,
        digest_hour=settings.digest_hour,
        reminder_days=list(settings.reminder_days),
        outbox=await _stats(db, utcnow()),
    )


# --- Outbox rows as the admin sees them ----------------------------------------------------
async def _outbox_items(db: AsyncSession, rows: Sequence[OutboundEmail]) -> list[OutboxEmail]:
    now = utcnow()
    ids = [row.id for row in rows]
    people = await user_refs(
        db, [user for row in rows for user in (row.recipient_user_id, row.requested_by_id)]
    )
    ideas: dict[UUID, tuple[Idea, Project]] = {}
    if ids:
        found = await db.execute(
            select(Notification.email_id, Idea, Project)
            .join(Idea, Idea.id == Notification.idea_id)
            .join(Project, Project.id == Idea.project_id)
            .where(
                any_of(Notification.email_id, ids),
                Notification.email_id.is_not(None),
            )
        )
        for email_id, idea, project in found:
            if email_id is not None:
                ideas.setdefault(email_id, (idea, project))
    items = []
    for row in rows:
        ref = None
        if row.type is not EmailType.DIGEST and row.id in ideas:
            ref = idea_ref(*ideas[row.id])
        items.append(
            OutboxEmail(
                id=row.id,
                type=row.type,
                status=row.status,
                recipient=people.get(row.recipient_user_id) if row.recipient_user_id else None,
                address_hint=email_hint(row.to_address) if row.to_address else None,
                idea=ref,
                requested_by=people.get(row.requested_by_id) if row.requested_by_id else None,
                attempts=row.attempts,
                max_attempts=row.max_attempts,
                next_attempt_at=row.next_attempt_at,
                last_error=row.last_error,
                created_at=row.created_at,
                sent_at=row.sent_at,
                retryable=outbox.retryable(row, now),
            )
        )
    return items


async def list_outbox(
    db: AsyncSession,
    *,
    statuses: Sequence[EmailStatus] | None,
    types: Sequence[EmailType] | None,
    cursor: str | None,
    limit: int,
) -> OutboxEmailPage:
    statement = select(OutboundEmail)
    if statuses:
        statement = statement.where(OutboundEmail.status.in_(list(statuses)))
    if types:
        statement = statement.where(OutboundEmail.type.in_(list(types)))
    if cursor:
        statement = statement.where(
            tuple_(OutboundEmail.created_at, OutboundEmail.id) < decode_time_cursor(cursor)
        )
    rows = list(
        await db.scalars(
            statement.order_by(OutboundEmail.created_at.desc(), OutboundEmail.id.desc()).limit(
                limit + 1
            )
        )
    )
    page = rows[:limit]
    next_cursor = None
    if len(rows) > limit and page:
        next_cursor = encode_cursor({"t": page[-1].created_at, "id": page[-1].id})
    return OutboxEmailPage(items=await _outbox_items(db, page), next_cursor=next_cursor)


async def _load(db: AsyncSession, email_id: UUID, *, for_update: bool = False) -> OutboundEmail:
    statement = select(OutboundEmail).where(OutboundEmail.id == email_id)
    if for_update:
        statement = statement.with_for_update()
    row = await db.scalar(statement)
    if row is None:
        raise NotFoundProblem("No such email (sent and cancelled emails are kept 30 days).")
    return row


async def get_outbox_email(db: AsyncSession, email_id: UUID) -> OutboxEmail:
    [item] = await _outbox_items(db, [await _load(db, email_id)])
    return item


# --- Actions --------------------------------------------------------------------------
def _not_usable(detail: str) -> ProblemError:
    return ProblemError(
        422,
        "validation_error",
        detail=detail,
        errors=[FieldError(loc=["body", "to"], msg=detail, type="value_error")],
    )


async def send_test_email(
    db: AsyncSession, settings: Settings, principal: Principal, to: str | None
) -> OutboxEmail:
    """Queue one test email (one attempt) to ``to`` or the admin's own address."""
    if not settings.smtp_configured:
        raise SmtpNotConfiguredProblem
    if to is None and not usable_address(principal.user.email):
        raise _not_usable(
            "Your account's address can't receive email: enter an address to send it to."
        )
    if to is not None and not usable_address(to):
        raise _not_usable("Enter one plain email address such as ops@example.com.")
    now = utcnow()
    # One admin's test emails, one at a time: the count below can't race.
    await db.execute(
        select(func.pg_advisory_xact_lock(_TEST_LOCK_SALT, func.hashtext(str(principal.user_id))))
    )
    recent = list(
        await db.scalars(
            select(OutboundEmail.created_at)
            .where(
                OutboundEmail.type == EmailType.TEST,
                OutboundEmail.requested_by_id == principal.user_id,
                OutboundEmail.created_at > now - TEST_EMAIL_WINDOW,
            )
            .order_by(OutboundEmail.created_at)
        )
    )
    if len(recent) >= TEST_EMAIL_LIMIT:
        wait = (recent[0] + TEST_EMAIL_WINDOW - now).total_seconds()
        raise ProblemError(
            429,
            "too_many_attempts",
            detail="Too many test emails: wait a few minutes and try again.",
            headers={"Retry-After": str(max(1, math.ceil(wait)))},
        )
    to_self = to is None or to.lower() == principal.user.email.lower()
    [email_id] = await outbox.enqueue(
        db,
        settings,
        [
            outbox.NewEmail(
                type=EmailType.TEST,
                recipient_user_id=principal.user_id if to is None else None,
                to_address=to,
                requested_by_id=principal.user_id,
                max_attempts=1,
            )
        ],
        now=now,
    )
    await audit.record(
        db,
        "email.test_send",
        actor=principal,
        details={"outbound_email_id": email_id, "to_self": to_self},
    )
    return await get_outbox_email(db, email_id)


def _requeue(now: datetime) -> dict[str, object]:
    return {
        "status": EmailStatus.QUEUED,
        "attempts": 0,
        "next_attempt_at": now,
        "last_error": None,
        "updated_at": now,
    }


async def retry_email(
    db: AsyncSession, settings: Settings, principal: Principal, email_id: UUID
) -> OutboxEmail:
    row = await _load(db, email_id, for_update=True)
    if not settings.smtp_configured:
        raise SmtpNotConfiguredProblem
    now = utcnow()
    if not outbox.retryable(row, now):
        raise ConflictProblem(
            "Only failed emails from the last 3 days (digests: 2) can be retried.",
            code="email_not_retryable",
        )
    await db.execute(
        update(OutboundEmail)
        .where(OutboundEmail.id == row.id)
        .values(_requeue(now))
        .execution_options(synchronize_session=False)
    )
    await db.refresh(row)
    await outbox.defer_send(db, [row.id])
    await audit.record(db, "email.retry", actor=principal, details={"outbound_email_id": row.id})
    [item] = await _outbox_items(db, [row])
    return item


async def retry_all_failed(db: AsyncSession, settings: Settings, principal: Principal) -> int:
    """Queue every retryable failed email again; returns how many."""
    if not settings.smtp_configured:
        raise SmtpNotConfiguredProblem
    now = utcnow()
    ids = list(
        await db.scalars(
            update(OutboundEmail)
            .where(
                OutboundEmail.status == EmailStatus.FAILED,
                or_(
                    and_(
                        OutboundEmail.type == EmailType.DIGEST,
                        OutboundEmail.created_at > now - outbox.DIGEST_MAX_AGE,
                    ),
                    and_(
                        OutboundEmail.type != EmailType.DIGEST,
                        OutboundEmail.created_at > now - outbox.MAX_AGE,
                    ),
                ),
            )
            .values(_requeue(now))
            .returning(OutboundEmail.id)
            .execution_options(synchronize_session=False)
        )
    )
    await outbox.defer_send(db, ids)
    if ids:
        await audit.record(db, "email.retry", actor=principal, details={"count": len(ids)})
    return len(ids)
