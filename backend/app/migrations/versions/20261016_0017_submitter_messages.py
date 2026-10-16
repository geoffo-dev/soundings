"""Phase 11: talking to public submitters (messages between the team and a submitter, the
tracking-link email, "The submitter replied").

Expand only (``scripts/lib/check-migrations.py``): one new table, one new unique constraint,
one new partial index and swapped ``CHECK`` constraints that accept more values; nothing the
previous release reads is dropped, renamed or retyped.

* ``submission_messages``: the conversation of a public submission (team messages with
  their author, the submitter's replies without one; plain text, 1-4,000 characters;
  ``emailed`` for team messages that were emailed). Its ``(submission_id, idea_id)``
  references ``public_submissions (id, idea_id)`` (the new ``uq_public_submissions_id_idea_id``)
  with ``ON DELETE CASCADE``: a message always names its own idea's submission, and
  deleting or rejecting the idea deletes the conversation with the submission. Indexes for
  the conversation (and its size, the per-submission limits and retention rule 4's latest
  message) and for the per-person limit.
* The notification type ``submitter_replied``: the ``CHECK`` constraints of
  ``notifications.type``, ``notification_preferences.type`` and ``outbound_email.type`` are
  swapped (the columns are long enough: 20 and 25 characters); it defaults to
  ``immediate`` in code, and someone who had every existing type off gets an ``off`` row for
  it, so "Unsubscribe from all email" stays all. ``ix_notifications_submitter_replied``
  (partial) serves the hourly coalescing of its emails.
* Two submitter email types, ``submission_link`` and ``submission_message``:
  ``ck_outbound_email_type`` and ``ck_outbound_email_idea_iff_submission_type`` (submitter
  emails, and only they, name their idea) accept them.
* Nothing is backfilled: submitters who confirmed their address before this release get no
  tracking-link email (contract-phase11 section 2).

Downgrade (below 0017 there is no conversation): every message is **deleted**, with the
outbox rows of the three new email types and the ``submitter_replied`` notifications and
preferences; the constraints, the index and the unique constraint go back.

Hand-written to match the models exactly (``tests/test_domain_schema.py`` compares them).
See docs/erd.md and docs/api/contract-phase11.md.

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | Sequence[str] | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# --- Values, spelled out (a migration must not import app code that may change) ---------
DIRECTIONS = ("team", "submitter")
BODY_MAX = 4_000

NOTIFICATION_TYPES_BEFORE = (
    "owner_assigned",
    "evaluator_invited",
    "evaluation_reminder",
    "evaluations_complete",
    "status_changed",
    "comment",
    "mention",
    "researcher_assigned",
    "research_reminder",
    "assessor_assigned",
    "assessment_reminder",
    "assessments_complete",
)
NEW_TYPES = ("submitter_replied",)
NOTIFICATION_TYPES = (*NOTIFICATION_TYPES_BEFORE, *NEW_TYPES)
"""In ``app.models.enums.NotificationType`` order (the ``CHECK`` lists them so)."""
SUBMITTER_EMAILS_BEFORE = ("submission_received", "submission_status_changed")
NEW_SUBMITTER_EMAILS = ("submission_link", "submission_message")
SUBMITTER_EMAILS = (*SUBMITTER_EMAILS_BEFORE, *NEW_SUBMITTER_EMAILS)
"""``app.models.enums.SUBMITTER_EMAIL_TYPES``."""
EMAIL_TYPES_BEFORE = (*NOTIFICATION_TYPES_BEFORE, "digest", "test", *SUBMITTER_EMAILS_BEFORE)
EMAIL_TYPES = (*NOTIFICATION_TYPES, "digest", "test", *SUBMITTER_EMAILS)
"""In ``app.models.enums.EmailType`` order."""

TYPE_CHECKS: tuple[tuple[str, str], ...] = (
    ("notifications", "ck_notifications_type"),
    ("notification_preferences", "ck_notification_preferences_type"),
)


def _values(values: Sequence[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _swap_check(table: str, name: str, sql: str) -> None:
    op.drop_constraint(op.f(name), table, type_="check")
    op.create_check_constraint(op.f(name), table, sql)


def _swap_type_checks(
    notification_types: Sequence[str], email_types: Sequence[str], submitter: Sequence[str]
) -> None:
    for table, name in TYPE_CHECKS:
        _swap_check(table, name, f"type IN ({_values(notification_types)})")
    _swap_check("outbound_email", "ck_outbound_email_type", f"type IN ({_values(email_types)})")
    _swap_check(
        "outbound_email",
        "ck_outbound_email_idea_iff_submission_type",
        f"(idea_id IS NOT NULL) = (type IN ({_values(submitter)}))",
    )


# --- Upgrade ---------------------------------------------------------------------------------
def _messages() -> None:
    op.create_unique_constraint(
        op.f("uq_public_submissions_id_idea_id"), "public_submissions", ["id", "idea_id"]
    )
    op.create_table(
        "submission_messages",
        sa.Column("submission_id", sa.Uuid(), nullable=False),
        sa.Column("idea_id", sa.Uuid(), nullable=False),
        sa.Column(
            "direction", sa.String(length=max(len(value) for value in DIRECTIONS)), nullable=False
        ),
        sa.Column("author_id", sa.Uuid(), nullable=True),
        sa.Column("body", sa.String(length=BODY_MAX), nullable=False),
        sa.Column("emailed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            f"direction IN ({_values(DIRECTIONS)})", name=op.f("ck_submission_messages_direction")
        ),
        sa.CheckConstraint(
            f"length(body) BETWEEN 1 AND {BODY_MAX}",
            name=op.f("ck_submission_messages_body_length"),
        ),
        sa.CheckConstraint(
            "direction = 'team' OR author_id IS NULL",
            name=op.f("ck_submission_messages_author_only_for_team"),
        ),
        sa.CheckConstraint(
            "direction = 'team' OR NOT emailed",
            name=op.f("ck_submission_messages_emailed_only_for_team"),
        ),
        sa.ForeignKeyConstraint(
            ["author_id"],
            ["users.id"],
            name=op.f("fk_submission_messages_author_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["submission_id", "idea_id"],
            ["public_submissions.id", "public_submissions.idea_id"],
            name=op.f("fk_submission_messages_submission_id_public_submissions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_submission_messages")),
    )
    op.create_index(
        "ix_submission_messages_submission_id_created_at",
        "submission_messages",
        ["submission_id", "created_at", "id"],
    )
    op.create_index(
        "ix_submission_messages_author_id_created_at",
        "submission_messages",
        ["author_id", "created_at"],
        postgresql_where=sa.text("author_id IS NOT NULL"),
    )


def _notification_types() -> None:
    _swap_type_checks(NOTIFICATION_TYPES, EMAIL_TYPES, SUBMITTER_EMAILS)
    op.create_index(
        "ix_notifications_submitter_replied",
        "notifications",
        ["user_id", "idea_id", "created_at"],
        postgresql_where=sa.text("type = 'submitter_replied'"),
    )
    # Whoever had every existing type off keeps getting no email for the new one.
    before = _values(NOTIFICATION_TYPES_BEFORE)  # constants, not input
    for new_type in NEW_TYPES:
        op.execute(
            "INSERT INTO notification_preferences (user_id, type, mode, updated_at) "  # noqa: S608
            f"SELECT user_id, '{new_type}', 'off', now() FROM notification_preferences "
            f"WHERE type IN ({before}) AND mode = 'off' "
            f"GROUP BY user_id HAVING count(*) = {len(NOTIFICATION_TYPES_BEFORE)} "
            "ON CONFLICT (user_id, type) DO NOTHING"
        )


def upgrade() -> None:
    _messages()
    _notification_types()


# --- Downgrade -------------------------------------------------------------------------------
def downgrade() -> None:
    new_types = _values(NEW_TYPES)  # constants, not input
    op.execute(f"DELETE FROM notifications WHERE type IN ({new_types})")  # noqa: S608
    op.execute(f"DELETE FROM notification_preferences WHERE type IN ({new_types})")  # noqa: S608
    new_emails = _values((*NEW_TYPES, *NEW_SUBMITTER_EMAILS))
    op.execute(f"DELETE FROM outbound_email WHERE type IN ({new_emails})")  # noqa: S608
    op.drop_index("ix_notifications_submitter_replied", table_name="notifications")
    _swap_type_checks(NOTIFICATION_TYPES_BEFORE, EMAIL_TYPES_BEFORE, SUBMITTER_EMAILS_BEFORE)

    op.drop_index("ix_submission_messages_author_id_created_at", table_name="submission_messages")
    op.drop_index(
        "ix_submission_messages_submission_id_created_at", table_name="submission_messages"
    )
    op.drop_table("submission_messages")
    op.drop_constraint(
        op.f("uq_public_submissions_id_idea_id"), "public_submissions", type_="unique"
    )
