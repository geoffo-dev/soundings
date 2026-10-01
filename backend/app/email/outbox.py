"""The transactional outbox (ADR 0003, contract-phase3 section 3.9).

An email is an ``outbound_email`` row inserted in the same transaction as the event
that causes it, plus a ``send_email`` job deferred **on the same psycopg connection**:
commit keeps both, rollback drops both. No ``queueing_lock`` on these defers (a lock
conflict would abort the caller's transaction). The row is the source of truth; the
job only wakes the worker (:mod:`app.email.delivery`).
"""

from __future__ import annotations

import random
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Final
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import psycopg
from procrastinate.types import JSONValue
from sqlalchemy import Table, bindparam, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.base import utcnow
from app.models.enums import EmailStatus, EmailType
from app.models.notification import MAX_EMAIL_ATTEMPTS, Notification, OutboundEmail
from app.worker import procrastinate_app

__all__ = [
    "ATTEMPT_DEADLINE",
    "BACKOFF_BASE",
    "BACKOFF_CAP",
    "DIGEST_MAX_AGE",
    "LEASE",
    "MAX_AGE",
    "SEND_EMAIL_TASK",
    "SWEEP_BATCH",
    "NewEmail",
    "backoff",
    "defer_send",
    "enqueue",
    "enqueue_for_notifications",
    "max_age",
    "new_message_id",
    "psycopg_connection",
    "retryable",
]

SEND_EMAIL_TASK: Final = "send_email"
LEASE: Final = timedelta(minutes=5)
"""A claimed (``sending``) row belongs to its worker this long; then the sweep may
re-queue it."""
ATTEMPT_DEADLINE: Final = timedelta(minutes=4)
"""One attempt (load, render, the SMTP conversation) must finish within this, so it is
recorded before the lease can expire."""
MAX_AGE: Final = timedelta(days=3)
DIGEST_MAX_AGE: Final = timedelta(days=2)
SWEEP_BATCH: Final = 500
BACKOFF_BASE: Final = timedelta(seconds=30)
BACKOFF_CAP: Final = timedelta(hours=1)
BACKOFF_JITTER: Final = 0.1


def backoff(attempt: int, *, rng: random.Random | None = None) -> timedelta:
    """Wait after failed attempt number ``attempt`` (1-based): 30 s doubling to an hour,
    plus up to 10 % jitter."""
    base = min(BACKOFF_BASE * (1 << min(max(attempt - 1, 0), 16)), BACKOFF_CAP)
    jitter: float = (rng or random).uniform(0, BACKOFF_JITTER)
    return base * (1 + jitter)


def max_age(type_: EmailType) -> timedelta:
    """Mail older than this is cancelled at send time and can't be retried."""
    return DIGEST_MAX_AGE if type_ is EmailType.DIGEST else MAX_AGE


def retryable(email: OutboundEmail, now: datetime) -> bool:
    return email.status is EmailStatus.FAILED and now - email.created_at < max_age(email.type)


def new_message_id(settings: Settings) -> str:
    """``<uuid4-hex@host-of-the-first-base-url>``, fixed for the row's life."""
    host = urlsplit(settings.public_base_url).hostname or "soundings.invalid"
    return f"<{uuid4().hex}@{host}>"


async def psycopg_connection(db: AsyncSession) -> psycopg.AsyncConnection[Any]:
    """The psycopg connection under the session's current transaction."""
    raw = await (await db.connection()).get_raw_connection()
    connection = raw.driver_connection
    assert isinstance(connection, psycopg.AsyncConnection)  # noqa: S101 - psycopg only
    return connection


async def defer_send(
    db: AsyncSession, email_ids: Sequence[UUID], *, schedule_at: datetime | None = None
) -> None:
    """Defer ``send_email`` for each row on the session's connection (atomic with the
    caller's transaction)."""
    if not email_ids:
        return
    connection = await psycopg_connection(db)
    deferrer = procrastinate_app.configure_task(
        SEND_EMAIL_TASK, connection=connection, schedule_at=schedule_at
    )
    jobs: list[dict[str, JSONValue]] = [{"email_id": str(email_id)} for email_id in email_ids]
    await deferrer.batch_defer_async(*jobs)


@dataclass(frozen=True, slots=True)
class NewEmail:
    """One email to queue: for a user (address looked up when sent) or an address."""

    type: EmailType
    recipient_user_id: UUID | None = None
    to_address: str | None = None
    requested_by_id: UUID | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)
    idempotency_key: str | None = None
    max_attempts: int = MAX_EMAIL_ATTEMPTS


async def enqueue(
    db: AsyncSession, settings: Settings, emails: Iterable[NewEmail], *, now: datetime | None = None
) -> list[UUID]:
    """Insert queued rows and defer their jobs, in the caller's transaction.

    Rows with an ``idempotency_key`` that already exists are skipped (``ON CONFLICT DO
    NOTHING``); returns the ids actually inserted, in order.
    """
    now = now or utcnow()
    values: list[dict[str, Any]] = [
        {
            "id": uuid4(),
            "type": email.type,
            "status": EmailStatus.QUEUED,
            "recipient_user_id": email.recipient_user_id,
            "to_address": email.to_address,
            "requested_by_id": email.requested_by_id,
            "payload": dict(email.payload),
            "message_id": new_message_id(settings),
            "idempotency_key": email.idempotency_key,
            "attempts": 0,
            "max_attempts": email.max_attempts,
            "next_attempt_at": now,
            "created_at": now,
            "updated_at": now,
        }
        for email in emails
    ]
    if not values:
        return []
    result = await db.execute(
        insert(OutboundEmail)
        .values(values)
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
        .returning(OutboundEmail.id)
    )
    inserted = set(result.scalars())
    ids: list[UUID] = [value["id"] for value in values if value["id"] in inserted]
    await defer_send(db, ids)
    return ids


async def enqueue_for_notifications(
    db: AsyncSession,
    settings: Settings,
    type_: EmailType,
    notifications: Sequence[tuple[UUID, UUID]],
    *,
    now: datetime | None = None,
) -> list[UUID]:
    """One immediate email per ``(notification id, user id)``; links each notification
    to its email (``notifications.email_id``)."""
    if not notifications:
        return []
    ids = await enqueue(
        db,
        settings,
        [NewEmail(type=type_, recipient_user_id=user_id) for _, user_id in notifications],
        now=now,
    )
    table = Notification.__table__
    assert isinstance(table, Table)  # noqa: S101 - a mapped table
    await db.execute(
        update(table)
        .where(table.c.id == bindparam("notification_id"))
        .values(email_id=bindparam("new_email_id")),
        [
            {"notification_id": notification_id, "new_email_id": email_id}
            for (notification_id, _), email_id in zip(notifications, ids, strict=True)
        ],
    )
    return ids
