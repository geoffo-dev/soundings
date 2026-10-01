"""The transactional outbox (ADR 0003, contract-phase3 section 3.9).

An email is an ``outbound_email`` row inserted in the same transaction as the event
that causes it, plus a ``send_email`` job deferred **on the same psycopg connection**:
commit keeps both, rollback drops both. No ``queueing_lock`` on these defers (a lock
conflict would abort the caller's transaction). The row is the source of truth; the
job only wakes the worker (:mod:`app.email.delivery`).
"""

from __future__ import annotations

import ipaddress
import random
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Final
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import psycopg
from procrastinate.types import JSONValue
from sqlalchemy import DateTime, SmallInteger, String, Uuid, bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.base import utcnow
from app.models.enums import EmailStatus, EmailType
from app.models.notification import MAX_EMAIL_ATTEMPTS, OutboundEmail
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
    "max_age",
    "message_id_domain",
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


def message_id_domain(settings: Settings) -> str:
    """The right side of our Message-IDs and References: the first base URL's host
    name, or an address literal (``[192.0.2.1]``, ``[IPv6:2001:db8::1]``) for an IP."""
    host = urlsplit(settings.public_base_url).hostname or "soundings.invalid"
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host
    return f"[IPv6:{address}]" if address.version == 6 else f"[{address}]"


def new_message_id(settings: Settings) -> str:
    """``<uuid4-hex@domain>`` (:func:`message_id_domain`), fixed for the row's life."""
    return f"<{uuid4().hex}@{message_id_domain(settings)}>"


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
    """One email to queue: for a user (address looked up when sent) or an address.

    ``idea_id``: the idea a public submitter's email is about; required for the two
    submission types and refused for every other type (the database checks it)."""

    type: EmailType
    recipient_user_id: UUID | None = None
    to_address: str | None = None
    requested_by_id: UUID | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)
    idempotency_key: str | None = None
    max_attempts: int = MAX_EMAIL_ATTEMPTS
    idea_id: UUID | None = None


_INSERT_EMAILS: Final = text(
    """
    INSERT INTO outbound_email
        (id, type, status, recipient_user_id, to_address, requested_by_id, payload,
         message_id, idempotency_key, attempts, max_attempts, next_attempt_at,
         created_at, updated_at, idea_id)
    SELECT row.id, row.type, 'queued', row.recipient_user_id, row.to_address,
           row.requested_by_id, row.payload, row.message_id, row.idempotency_key, 0,
           row.max_attempts, :now, :now, :now, row.idea_id
      FROM unnest(
               :ids, :types, :recipient_user_ids, :to_addresses, :requested_by_ids,
               :payloads, :message_ids, :idempotency_keys, :max_attempts, :idea_ids
           ) AS row(id, type, recipient_user_id, to_address, requested_by_id, payload,
                    message_id, idempotency_key, max_attempts, idea_id)
    ON CONFLICT (idempotency_key) DO NOTHING
    RETURNING id
    """
).bindparams(
    bindparam("ids", type_=ARRAY(Uuid())),
    bindparam("types", type_=ARRAY(String())),
    bindparam("recipient_user_ids", type_=ARRAY(Uuid())),
    bindparam("to_addresses", type_=ARRAY(String())),
    bindparam("requested_by_ids", type_=ARRAY(Uuid())),
    bindparam("payloads", type_=ARRAY(JSONB())),
    bindparam("message_ids", type_=ARRAY(String())),
    bindparam("idempotency_keys", type_=ARRAY(String())),
    bindparam("max_attempts", type_=ARRAY(SmallInteger())),
    bindparam("idea_ids", type_=ARRAY(Uuid())),
    bindparam("now", type_=DateTime(timezone=True)),
)
"""Queued rows: one statement with an array per column, however many emails."""


async def enqueue(
    db: AsyncSession, settings: Settings, emails: Iterable[NewEmail], *, now: datetime | None = None
) -> list[UUID]:
    """Insert queued rows and defer their jobs, in the caller's transaction.

    Rows with an ``idempotency_key`` that already exists are skipped (``ON CONFLICT DO
    NOTHING``); returns the ids actually inserted, in order (all of them when no
    email has a key).
    """
    now = now or utcnow()
    wanted = list(emails)
    if not wanted:
        return []
    ids = [uuid4() for _ in wanted]
    result = await db.execute(
        _INSERT_EMAILS,
        {
            "ids": ids,
            "types": [email.type.value for email in wanted],
            "recipient_user_ids": [email.recipient_user_id for email in wanted],
            "to_addresses": [email.to_address for email in wanted],
            "requested_by_ids": [email.requested_by_id for email in wanted],
            "payloads": [dict(email.payload) for email in wanted],
            "message_ids": [new_message_id(settings) for _ in wanted],
            "idempotency_keys": [email.idempotency_key for email in wanted],
            "max_attempts": [email.max_attempts for email in wanted],
            "idea_ids": [email.idea_id for email in wanted],
            "now": now,
        },
    )
    inserted: set[UUID] = set(result.scalars())
    queued = [email_id for email_id in ids if email_id in inserted]
    await defer_send(db, queued)
    return queued
