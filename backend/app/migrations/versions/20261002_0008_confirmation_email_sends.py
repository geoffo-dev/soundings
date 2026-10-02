"""Phase 4 review: the per-address limit on confirmation emails counts its own rows.

* ``confirmation_email_sends``: one row per confirmation email queued to an address,
  by ``address_key`` (HMAC-SHA256 hex of the canonical address with a key derived from
  the secret key; no address is stored), indexed by ``(address_key, created_at)`` for
  the limit and by ``created_at`` for the hourly cleanup, which deletes rows after 24
  hours. Nothing else deletes them: the limit used to count ``outbound_email`` rows,
  which erasure, rejection and the retention rules delete (code review M1).
* ``ix_outbound_email_submission_address`` is dropped: nothing counts those rows any
  more.

Sends before this revision aren't carried over (the key needs the secret key): the
limit starts from zero for at most a day.

Hand-written to match the models exactly (``tests/test_domain_schema.py`` compares
them).

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# app.models.notification.SUBMITTER_ADDRESS_KEY_SQL as of revision 0007 (downgrade).
SUBMITTER_ADDRESS_KEY = r"lower(regexp_replace(to_address, '\+[^@]*@', '@'))"


def upgrade() -> None:
    op.create_table(
        "confirmation_email_sends",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("address_key", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_confirmation_email_sends")),
    )
    op.create_index(
        "ix_confirmation_email_sends_address_key_created_at",
        "confirmation_email_sends",
        ["address_key", "created_at"],
    )
    op.create_index(
        op.f("ix_confirmation_email_sends_created_at"),
        "confirmation_email_sends",
        ["created_at"],
    )
    op.drop_index("ix_outbound_email_submission_address", table_name="outbound_email")


def downgrade() -> None:
    op.create_index(
        "ix_outbound_email_submission_address",
        "outbound_email",
        [sa.literal_column(SUBMITTER_ADDRESS_KEY), "created_at"],
        postgresql_where=sa.text("type = 'submission_received'"),
    )
    op.drop_table("confirmation_email_sends")  # its indexes go with it
