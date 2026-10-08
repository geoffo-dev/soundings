"""Phase 8 build: trigram GiST indexes for "Similar ideas".

* ``ix_ideas_title_trgm_gist`` on ``ideas USING gist (title gist_trgm_ops)``
* ``ix_ideas_summary_trgm_gist`` on ``ideas USING gist (summary gist_trgm_ops)``

"Similar ideas" (contract-phase8 section 3.8) takes the nearest ideas by title and by
summary with ``<->`` (trigram distance), which only a GiST index serves in order: the
existing GIN indexes (``ix_ideas_*_trgm``, for search's ``ILIKE``) answer ``%`` but
return every match unordered, and on a project of near-identical summaries that was
every idea (1.3 s at 12,000 ideas; 5 ms with these).

Hand-written to match the models exactly (``tests/test_domain_schema.py`` compares
them).

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-07
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_ideas_title_trgm_gist",
        "ideas",
        ["title"],
        postgresql_using="gist",
        postgresql_ops={"title": "gist_trgm_ops"},
    )
    op.create_index(
        "ix_ideas_summary_trgm_gist",
        "ideas",
        ["summary"],
        postgresql_using="gist",
        postgresql_ops={"summary": "gist_trgm_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_ideas_summary_trgm_gist", table_name="ideas")
    op.drop_index("ix_ideas_title_trgm_gist", table_name="ideas")
