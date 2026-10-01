"""Phase 3, email: the outbox, in-app notifications and email preferences.

* ``outbound_email``: the transactional outbox (ADR 0003). One row per email, written
  in the same transaction as the event, sent by the worker with retries and capped
  exponential backoff; status ``queued | sending | sent | failed | cancelled``; a
  Message-ID fixed at insert; an optional idempotency key (one digest per person per
  day). Content is rendered at send time, so no bodies are stored. (Phase 4 adds the
  idea reference of public-submitter emails.)
* ``notifications``: the in-app inbox (one row per recipient and event, unique per
  ``(user_id, dedupe_key)``), which also records how the notification is emailed
  (``email_mode``) and by which email (``email_id``): digest and reminder bookkeeping
  need no tables of their own. A partial index on ``(actor_id, created_at)`` for
  mentions serves the per-author cap on mention emails.
* ``notification_preferences``: per user and notification type, ``immediate``,
  ``digest`` or ``off``; only choices that differ from the defaults in code.

Downgrade drops the three tables (queued email is lost; email jobs still in the queue
fail in an older worker as unknown tasks, which is harmless).

Hand-written to match the models exactly (``tests/test_domain_schema.py`` compares
them). See docs/erd.md and docs/api/contract-phase3.md.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-01
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NOTIFICATION_TYPES = (
    "owner_assigned",
    "evaluator_invited",
    "evaluation_reminder",
    "evaluations_complete",
    "status_changed",
    "comment",
    "mention",
)
EMAIL_TYPES = (
    *NOTIFICATION_TYPES,
    "digest",
    "test",
    "submission_received",
    "submission_status_changed",
)
EMAIL_STATUSES = ("queued", "sending", "sent", "failed", "cancelled")
NOTIFICATION_MODES = ("immediate", "digest", "off")


def _id() -> sa.Column[Any]:
    return sa.Column("id", sa.Uuid(), nullable=False)


def _timestamp(name: str) -> sa.Column[Any]:
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def _payload() -> sa.Column[Any]:
    return sa.Column(
        "payload",
        postgresql.JSONB(astext_type=sa.Text()),
        server_default=sa.text("'{}'::jsonb"),
        nullable=False,
    )


def _enum_check(column: str, values: Sequence[str], name: str) -> sa.CheckConstraint:
    allowed = ", ".join(f"'{value}'" for value in values)
    return sa.CheckConstraint(f"{column} IN ({allowed})", name=op.f(name))


def _fk(column: str, target: str, name: str, ondelete: str = "CASCADE") -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint([column], [target], name=op.f(name), ondelete=ondelete)


def _length(values: Sequence[str]) -> int:
    return max(len(value) for value in values)


def upgrade() -> None:
    op.create_table(
        "outbound_email",
        _id(),
        sa.Column("type", sa.String(length=_length(EMAIL_TYPES)), nullable=False),
        sa.Column(
            "status",
            sa.String(length=_length(EMAIL_STATUSES)),
            server_default="queued",
            nullable=False,
        ),
        sa.Column("recipient_user_id", sa.Uuid(), nullable=True),
        sa.Column("to_address", sa.String(length=320), nullable=True),
        sa.Column("requested_by_id", sa.Uuid(), nullable=True),
        _payload(),
        sa.Column("message_id", sa.String(length=255), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=True),
        sa.Column("attempts", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_attempts", sa.SmallInteger(), server_default=sa.text("12"), nullable=False),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("last_error", sa.String(length=200), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.CheckConstraint(
            "(recipient_user_id IS NULL) <> (to_address IS NULL)",
            name=op.f("ck_outbound_email_one_recipient"),
        ),
        sa.CheckConstraint("attempts >= 0", name=op.f("ck_outbound_email_attempts_non_negative")),
        sa.CheckConstraint(
            "max_attempts BETWEEN 1 AND 20", name=op.f("ck_outbound_email_max_attempts_range")
        ),
        sa.CheckConstraint(
            "(status IN ('queued', 'sending')) = (next_attempt_at IS NOT NULL)",
            name=op.f("ck_outbound_email_next_attempt_iff_pending"),
        ),
        sa.CheckConstraint(
            "(status = 'sent') = (sent_at IS NOT NULL)",
            name=op.f("ck_outbound_email_sent_at_iff_sent"),
        ),
        _enum_check("type", EMAIL_TYPES, "ck_outbound_email_type"),
        _enum_check("status", EMAIL_STATUSES, "ck_outbound_email_status"),
        _fk("recipient_user_id", "users.id", "fk_outbound_email_recipient_user_id_users"),
        _fk(
            "requested_by_id",
            "users.id",
            "fk_outbound_email_requested_by_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_outbound_email")),
        sa.UniqueConstraint("message_id", name=op.f("uq_outbound_email_message_id")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_outbound_email_idempotency_key")),
    )
    op.create_index(
        "ix_outbound_email_next_attempt_at_pending",
        "outbound_email",
        ["next_attempt_at"],
        postgresql_where=sa.text("status IN ('queued', 'sending')"),
    )
    op.create_index("ix_outbound_email_created_at_id", "outbound_email", ["created_at", "id"])
    op.create_index(
        "ix_outbound_email_status_created_at_id", "outbound_email", ["status", "created_at", "id"]
    )
    op.create_index(
        op.f("ix_outbound_email_recipient_user_id"), "outbound_email", ["recipient_user_id"]
    )

    op.create_table(
        "notifications",
        _id(),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=_length(NOTIFICATION_TYPES)), nullable=False),
        sa.Column("idea_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("comment_id", sa.Uuid(), nullable=True),
        _payload(),
        sa.Column("dedupe_key", sa.String(length=200), nullable=False),
        sa.Column("email_mode", sa.String(length=_length(NOTIFICATION_MODES)), nullable=False),
        sa.Column("email_id", sa.Uuid(), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        _timestamp("created_at"),
        sa.CheckConstraint(
            "(type IN ('comment', 'mention')) = (comment_id IS NOT NULL)",
            name=op.f("ck_notifications_comment_iff_comment_type"),
        ),
        sa.CheckConstraint(
            "email_id IS NULL OR email_mode <> 'off'",
            name=op.f("ck_notifications_no_email_when_off"),
        ),
        _enum_check("type", NOTIFICATION_TYPES, "ck_notifications_type"),
        _enum_check("email_mode", NOTIFICATION_MODES, "ck_notifications_email_mode"),
        _fk("user_id", "users.id", "fk_notifications_user_id_users"),
        _fk("idea_id", "ideas.id", "fk_notifications_idea_id_ideas"),
        _fk("actor_id", "users.id", "fk_notifications_actor_id_users", ondelete="SET NULL"),
        _fk("comment_id", "comments.id", "fk_notifications_comment_id_comments"),
        _fk(
            "email_id",
            "outbound_email.id",
            "fk_notifications_email_id_outbound_email",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
        sa.UniqueConstraint(
            "user_id", "dedupe_key", name=op.f("uq_notifications_user_id_dedupe_key")
        ),
    )
    op.create_index(
        "ix_notifications_user_id_created_at", "notifications", ["user_id", "created_at", "id"]
    )
    op.create_index(
        "ix_notifications_user_id_unread",
        "notifications",
        ["user_id", "created_at", "id"],
        postgresql_where=sa.text("read_at IS NULL"),
    )
    op.create_index(
        "ix_notifications_digest_pending",
        "notifications",
        ["user_id", "created_at"],
        postgresql_where=sa.text("email_mode = 'digest' AND email_id IS NULL"),
    )
    op.create_index(
        "ix_notifications_mention_actor",
        "notifications",
        ["actor_id", "created_at"],
        postgresql_where=sa.text("type = 'mention'"),
    )
    op.create_index(
        "ix_notifications_email_id",
        "notifications",
        ["email_id"],
        postgresql_where=sa.text("email_id IS NOT NULL"),
    )
    op.create_index(
        "ix_notifications_comment_id",
        "notifications",
        ["comment_id"],
        postgresql_where=sa.text("comment_id IS NOT NULL"),
    )
    op.create_index(op.f("ix_notifications_idea_id"), "notifications", ["idea_id"])

    op.create_table(
        "notification_preferences",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=_length(NOTIFICATION_TYPES)), nullable=False),
        sa.Column("mode", sa.String(length=_length(NOTIFICATION_MODES)), nullable=False),
        _timestamp("updated_at"),
        _enum_check("type", NOTIFICATION_TYPES, "ck_notification_preferences_type"),
        _enum_check("mode", NOTIFICATION_MODES, "ck_notification_preferences_mode"),
        _fk("user_id", "users.id", "fk_notification_preferences_user_id_users"),
        sa.PrimaryKeyConstraint("user_id", "type", name=op.f("pk_notification_preferences")),
    )


def downgrade() -> None:
    op.drop_table("notification_preferences")
    op.drop_table("notifications")  # its indexes go with it; it references outbound_email
    op.drop_table("outbound_email")
