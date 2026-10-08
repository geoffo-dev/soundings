"""Phase 8b: assign an idea's research to a person.

* ``ideas.researcher_id`` (users, ``ON DELETE SET NULL``): the person asked to do the
  idea's research; null = nobody, the idea's owner does it (every existing idea).
  ``ideas.research_assigned_at``: when they were asked (meaningless while
  ``researcher_id`` is null; set whenever it is: ``ck_ideas_researcher_assigned_at``, one
  way only, since ``ON DELETE SET NULL`` clears ``researcher_id`` alone).
  ``ideas.research_due_at``: the optional research due date.
  Indexes: ``ix_ideas_researcher_id_status`` (``researcher_id, status`` where a
  researcher is set: My work's "Research to do", the sidebar count, guest access in
  lists, deactivation clearing the assignments) and ``ix_ideas_research_due_at_open``
  (``research_due_at`` of open ideas: the hourly research reminder scan).
* Two notification types, ``researcher_assigned`` ("Asked to research") and
  ``research_reminder``: the ``CHECK`` constraints of ``notifications.type``,
  ``notification_preferences.type`` and ``outbound_email.type`` are swapped (the columns
  are long enough). Both default to ``immediate`` in code (no rows needed), except that
  **someone who had every existing type off** (the footer's "Unsubscribe from all email",
  or each type switched off) gets ``off`` rows for the two new types too, so an
  "unsubscribe from all" stays all.

Downgrade: the two notification types' notifications, outbox rows and preference rows
are deleted, the ``researcher_changed`` and ``research_due_date_changed`` activity events
are deleted (older code can't read them; audit entries stay: the viewer reads any
action), the ``CHECK`` constraints go back, and the three columns with their indexes are
dropped: **every research assignment and research due date is lost** (the research
itself, the checklist answers, is kept).

Hand-written to match the models exactly (``tests/test_domain_schema.py`` compares
them). See docs/erd.md and docs/api/contract-phase8b.md.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | Sequence[str] | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NOTIFICATION_TYPES_BEFORE = (
    "owner_assigned",
    "evaluator_invited",
    "evaluation_reminder",
    "evaluations_complete",
    "status_changed",
    "comment",
    "mention",
)
NEW_TYPES = ("researcher_assigned", "research_reminder")
NOTIFICATION_TYPES = (*NOTIFICATION_TYPES_BEFORE, *NEW_TYPES)
"""In ``app.models.enums.NotificationType`` order (the ``CHECK`` lists them so)."""
EMAIL_TYPES_BEFORE = (
    *NOTIFICATION_TYPES_BEFORE,
    "digest",
    "test",
    "submission_received",
    "submission_status_changed",
)
EMAIL_TYPES = (
    *NOTIFICATION_TYPES,
    "digest",
    "test",
    "submission_received",
    "submission_status_changed",
)
"""In ``app.models.enums.EmailType`` order."""
NEW_ACTIVITY_TYPES = ("researcher_changed", "research_due_date_changed")

TYPE_CHECKS: tuple[tuple[str, str], ...] = (
    ("notifications", "ck_notifications_type"),
    ("notification_preferences", "ck_notification_preferences_type"),
)


def _values(values: Sequence[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _swap_type_checks(notification_types: Sequence[str], email_types: Sequence[str]) -> None:
    for table, name in TYPE_CHECKS:
        op.drop_constraint(op.f(name), table, type_="check")
        op.create_check_constraint(op.f(name), table, f"type IN ({_values(notification_types)})")
    op.drop_constraint(op.f("ck_outbound_email_type"), "outbound_email", type_="check")
    op.create_check_constraint(
        op.f("ck_outbound_email_type"), "outbound_email", f"type IN ({_values(email_types)})"
    )


def upgrade() -> None:
    op.add_column("ideas", sa.Column("researcher_id", sa.Uuid(), nullable=True))
    op.add_column(
        "ideas", sa.Column("research_assigned_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("ideas", sa.Column("research_due_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        op.f("fk_ideas_researcher_id_users"),
        "ideas",
        "users",
        ["researcher_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        op.f("ck_ideas_researcher_assigned_at"),
        "ideas",
        "researcher_id IS NULL OR research_assigned_at IS NOT NULL",
    )
    op.create_index(
        "ix_ideas_researcher_id_status",
        "ideas",
        ["researcher_id", "status"],
        postgresql_where=sa.text("researcher_id IS NOT NULL"),
    )
    op.create_index(
        "ix_ideas_research_due_at_open",
        "ideas",
        ["research_due_at"],
        postgresql_where=sa.text("research_due_at IS NOT NULL AND status <> 'closed'"),
    )

    _swap_type_checks(NOTIFICATION_TYPES, EMAIL_TYPES)

    # Whoever had every existing type off keeps getting no email for the new ones.
    before = _values(NOTIFICATION_TYPES_BEFORE)  # constants, not input
    for new_type in NEW_TYPES:
        op.execute(
            "INSERT INTO notification_preferences (user_id, type, mode, updated_at) "  # noqa: S608
            f"SELECT user_id, '{new_type}', 'off', now() FROM notification_preferences "
            f"WHERE type IN ({before}) AND mode = 'off' "
            f"GROUP BY user_id HAVING count(*) = {len(NOTIFICATION_TYPES_BEFORE)} "
            "ON CONFLICT (user_id, type) DO NOTHING"
        )


def downgrade() -> None:
    new_types = _values(NEW_TYPES)  # constants, not input
    op.execute(f"DELETE FROM notifications WHERE type IN ({new_types})")  # noqa: S608
    op.execute(f"DELETE FROM outbound_email WHERE type IN ({new_types})")  # noqa: S608
    op.execute(f"DELETE FROM notification_preferences WHERE type IN ({new_types})")  # noqa: S608
    op.execute(
        f"DELETE FROM activity_events WHERE type IN ({_values(NEW_ACTIVITY_TYPES)})"  # noqa: S608
    )
    _swap_type_checks(NOTIFICATION_TYPES_BEFORE, EMAIL_TYPES_BEFORE)

    op.drop_index("ix_ideas_research_due_at_open", table_name="ideas")
    op.drop_index("ix_ideas_researcher_id_status", table_name="ideas")
    op.drop_constraint(op.f("ck_ideas_researcher_assigned_at"), "ideas", type_="check")
    op.drop_constraint(op.f("fk_ideas_researcher_id_users"), "ideas", type_="foreignkey")
    op.drop_column("ideas", "research_due_at")
    op.drop_column("ideas", "research_assigned_at")
    op.drop_column("ideas", "researcher_id")
