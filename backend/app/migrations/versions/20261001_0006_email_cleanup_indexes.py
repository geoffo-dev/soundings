"""Phase 3 review: indexes for the hourly cleanup and the admins' email banner.

* ``ix_outbound_email_status_updated_at`` on ``outbound_email (status, updated_at)``:
  the cleanup's deletes (sent and cancelled rows after 30 days, failed rows after 90)
  and the "an email failed in the last 24 hours" check behind the admins' banner
  (``email_trouble``) no longer scan the table.
* ``ix_notifications_created_at`` on ``notifications (created_at)``: pruning
  notifications older than 90 days.

The cleanup now runs every hour (not only in the digest hour), so it must be cheap.

Hand-written to match the models exactly (``tests/test_domain_schema.py`` compares
them).

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-01
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_outbound_email_status_updated_at", "outbound_email", ["status", "updated_at"]
    )
    op.create_index("ix_notifications_created_at", "notifications", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_notifications_created_at", table_name="notifications")
    op.drop_index("ix_outbound_email_status_updated_at", table_name="outbound_email")
