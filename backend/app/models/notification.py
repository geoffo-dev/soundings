"""Notifications: the in-app inbox, email preferences and the email outbox.

One fan-out (contract-phase3 section 3.3) writes, in the same transaction as the event,
a ``notifications`` row per recipient and, for recipients who want it by email now,
an ``outbound_email`` row that the worker sends (ADR 0003). Digests, reminders and
unsubscribe links need no tables of their own:

* **digest bookkeeping:** a notification waits for the daily digest while
  ``email_mode = 'digest'`` and ``email_id`` is null; the digest email claims it by
  setting ``email_id``; one digest per person per local day
  (``outbound_email.idempotency_key``); only items from the last 7 days are collected,
  and the daily cleanup turns older pending items ``off`` (also those whose digest row
  was pruned, which sets ``email_id`` null), so nothing is ever mailed twice;
* **reminder bookkeeping:** each reminder is a notification whose ``dedupe_key`` names
  the idea, the due date and the offset, unique per user;
* **unsubscribe tokens** are signed (HMAC with a key derived from the secret key),
  not stored;
* **@mentions** are parsed from the comment when it is written; each mentioned user
  gets one ``mention`` notification per comment (``dedupe_key``).

Nothing here ever holds a score (role matrix section 3, rule 8).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, utcnow
from app.models.enums import EmailStatus, EmailType, NotificationMode, NotificationType
from app.models.types import str_enum

MAX_EMAIL_ATTEMPTS = 12
"""Attempts before a notification email fails for good (contract-phase3 section 3.9).
A test email gets one attempt."""


class OutboundEmail(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The transactional outbox: one row per email, written in the same transaction
    as the event that causes it, sent by the worker (ADR 0003).

    The row is the source of truth, not the job: the worker claims a ``queued`` row
    whose ``next_attempt_at`` has come (``status = 'sending'``, ``next_attempt_at`` =
    the claim's 5-minute lease; the attempt must finish within 4), sends it, and
    records ``sent`` or the next attempt. Content is **rendered at send time** from the
    notification(s) that point at this row (``notifications.email_id``), after
    re-checking that the recipient may still see it, still wants it and that it isn't
    out of date; only ``payload`` carries what can't be looked up later (Phase 4: the
    sealed tracking link). ``message_id`` is fixed at insert, so a resend after a crash
    has the same Message-ID and mail clients drop the duplicate.

    The recipient is a user (address looked up at send time, so a changed address is
    used and a deactivated user gets nothing) or, for a test email to another address
    and Phase 4's public submitters, ``to_address``. Phase 4 adds the idea reference
    its submitter emails need.
    """

    __tablename__ = "outbound_email"
    __table_args__ = (
        CheckConstraint(
            "(recipient_user_id IS NULL) <> (to_address IS NULL)", name="one_recipient"
        ),
        CheckConstraint("attempts >= 0", name="attempts_non_negative"),
        CheckConstraint("max_attempts BETWEEN 1 AND 20", name="max_attempts_range"),
        CheckConstraint(
            "(status IN ('queued', 'sending')) = (next_attempt_at IS NOT NULL)",
            name="next_attempt_iff_pending",
        ),
        CheckConstraint("(status = 'sent') = (sent_at IS NOT NULL)", name="sent_at_iff_sent"),
        UniqueConstraint("message_id"),
        UniqueConstraint("idempotency_key"),
        # The worker's claim and the sweep: due rows only (a small partial index).
        Index(
            "ix_outbound_email_next_attempt_at_pending",
            "next_attempt_at",
            postgresql_where=text("status IN ('queued', 'sending')"),
        ),
        # Admin outbox, newest first, all or by status; per-status counts; pruning.
        Index("ix_outbound_email_created_at_id", "created_at", "id"),
        Index("ix_outbound_email_status_created_at_id", "status", "created_at", "id"),
        # The hourly cleanup's deletes and the admins' "an email failed lately" banner.
        Index("ix_outbound_email_status_updated_at", "status", "updated_at"),
    )

    type: Mapped[EmailType] = mapped_column(str_enum(EmailType, "type"))
    status: Mapped[EmailStatus] = mapped_column(
        str_enum(EmailStatus, "status"),
        default=EmailStatus.QUEUED,
        server_default=EmailStatus.QUEUED.value,
    )
    recipient_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # Only for recipients who are not users: never shown in full, never logged.
    to_address: Mapped[str | None] = mapped_column(String(320))
    # Who asked for it: the admin who sent a test email (rate limit, "sent by").
    requested_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    # "<uuid@host-of-the-first-base-url>", fixed at insert (the Message-ID header).
    message_id: Mapped[str] = mapped_column(String(255))
    # One email per key: "digest:<user id>:<local date>"; Phase 4 per submission.
    idempotency_key: Mapped[str | None] = mapped_column(String(200))
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(
        SmallInteger, default=MAX_EMAIL_ATTEMPTS, server_default=text(str(MAX_EMAIL_ATTEMPTS))
    )
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    # Sanitised by our code (SMTP code + a fixed phrase); never the server's own text,
    # which can echo addresses.
    last_error: Mapped[str | None] = mapped_column(String(200))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Notification(UUIDPrimaryKeyMixin, Base):
    """One entry in a user's in-app inbox, about one idea.

    ``payload`` holds the type's data (contract-phase3 section 3.3: from/to status,
    due date, reminder offset, submitted count); never scores. ``email_mode`` is the
    recipient's email preference for the type when the notification was created
    (``off`` also when email isn't configured); ``email_id`` is the email that carried
    it (its own immediate email, or the digest that collected it).

    ``dedupe_key`` makes the fan-out idempotent: ``<type>:<activity event id>`` for
    event notifications, ``mention:<comment id>``,
    ``evaluation_reminder:<idea id>:<due date>:<days before>``.
    """

    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("user_id", "dedupe_key"),
        CheckConstraint(
            "(type IN ('comment', 'mention')) = (comment_id IS NOT NULL)",
            name="comment_iff_comment_type",
        ),
        CheckConstraint("email_id IS NULL OR email_mode <> 'off'", name="no_email_when_off"),
        # The inbox, newest first; unread only (filter and the bell's count).
        Index("ix_notifications_user_id_created_at", "user_id", "created_at", "id"),
        # The hourly cleanup prunes notifications older than 90 days.
        Index("ix_notifications_created_at", "created_at"),
        Index(
            "ix_notifications_user_id_unread",
            "user_id",
            "created_at",
            "id",
            postgresql_where=text("read_at IS NULL"),
        ),
        # The daily digest: what is still waiting, per person.
        Index(
            "ix_notifications_digest_pending",
            "user_id",
            "created_at",
            postgresql_where=text("email_mode = 'digest' AND email_id IS NULL"),
        ),
        # The per-author cap on mention emails (contract-phase3 section 3.8).
        Index(
            "ix_notifications_mention_actor",
            "actor_id",
            "created_at",
            postgresql_where=text("type = 'mention'"),
        ),
        # The worker loads an email's notifications; pruning emails sets this null.
        Index(
            "ix_notifications_email_id",
            "email_id",
            postgresql_where=text("email_id IS NOT NULL"),
        ),
        Index(
            "ix_notifications_comment_id",
            "comment_id",
            postgresql_where=text("comment_id IS NOT NULL"),
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    type: Mapped[NotificationType] = mapped_column(str_enum(NotificationType, "type"))
    idea_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ideas.id", ondelete="CASCADE"), index=True
    )
    # Who caused it; null for reminders (the system) and when the user no longer exists.
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    comment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("comments.id", ondelete="CASCADE")
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    dedupe_key: Mapped[str] = mapped_column(String(200))
    email_mode: Mapped[NotificationMode] = mapped_column(str_enum(NotificationMode, "email_mode"))
    email_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("outbound_email.id", ondelete="SET NULL")
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )


class NotificationPreference(Base):
    """A user's email preference for one notification type. Only choices that differ
    from the defaults in code (``app.schemas.notifications.DEFAULT_MODES``) need a row;
    the API resolves the rest."""

    __tablename__ = "notification_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    type: Mapped[NotificationType] = mapped_column(
        str_enum(NotificationType, "type"), primary_key=True
    )
    mode: Mapped[NotificationMode] = mapped_column(str_enum(NotificationMode, "mode"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        server_default=func.now(),
        onupdate=utcnow,
    )


__all__ = [
    "MAX_EMAIL_ATTEMPTS",
    "Notification",
    "NotificationPreference",
    "OutboundEmail",
]
