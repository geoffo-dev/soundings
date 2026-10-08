"""Phase 8 review: indexes for My work's owned groups and the cards' counts.

* ``ix_ideas_owner_id_status_last_activity_at`` on ``ideas (owner_id, status,
  last_activity_at, id)``, replacing ``ix_ideas_owner_id``: My work reads each owned
  group's first page (``-updated``) with one range scan per status that stops after the
  page, instead of combining the owner and project/status indexes and sorting (an owner
  of 225 ideas among 12,000: 14.5 -> 8.9 ms for the groups' statement). Its first column
  serves every plain ``owner_id`` lookup the old index did.
* ``ix_evaluations_idea_id_status`` on ``evaluations (idea_id, status)`` and
  ``ix_comments_idea_id_live`` on ``comments (idea_id) WHERE deleted_at IS NULL``: every
  card's "submitted" and comment counts become index-only counts (another 8.9 -> 7.0 ms
  for the groups; lists and boards gain the same per card). Not a partial index on
  ``status = 'submitted'``: the status is a bound parameter, so the generic plan of a
  prepared statement could never use it.

Hand-written to match the models exactly (``tests/test_domain_schema.py`` compares
them).

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_ideas_owner_id_status_last_activity_at",
        "ideas",
        ["owner_id", "status", "last_activity_at", "id"],
    )
    op.drop_index("ix_ideas_owner_id", table_name="ideas")
    op.create_index("ix_evaluations_idea_id_status", "evaluations", ["idea_id", "status"])
    op.create_index(
        "ix_comments_idea_id_live",
        "comments",
        ["idea_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_comments_idea_id_live", table_name="comments")
    op.drop_index("ix_evaluations_idea_id_status", table_name="evaluations")
    op.create_index("ix_ideas_owner_id", "ideas", ["owner_id"])
    op.drop_index("ix_ideas_owner_id_status_last_activity_at", table_name="ideas")
