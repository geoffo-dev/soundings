"""Phase 4 UX review: when a public idea reached the team.

* ``public_submissions.reached_team_at`` (nullable): when the idea stopped being held
  (at submission when nothing held it, else the confirmation or the approval that
  released it), for the tracking page's "With the team" step
  (``TrackedSubmission.reached_team_at``). Null while the idea is held.

Backfill for ideas no longer held: the approval's audit entry (``submission.approve``)
when there is one, else the submission time. (An idea released by its submitter's
confirmation alone, before this revision, gets the submission time: the exact moment
wasn't recorded.)

Hand-written to match the models exactly (``tests/test_domain_schema.py`` compares
them).

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "public_submissions",
        sa.Column("reached_team_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        """
        UPDATE public_submissions AS s
        SET reached_team_at = COALESCE(
            (
                SELECT min(a.created_at) FROM audit_log AS a
                WHERE a.action = 'submission.approve'
                  AND a.target_type = 'idea'
                  AND a.target_id = s.idea_id
            ),
            s.created_at
        )
        FROM ideas AS i
        WHERE i.id = s.idea_id AND i.held_for IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("public_submissions", "reached_team_at")
