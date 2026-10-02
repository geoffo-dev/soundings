"""Phase 5: API keys and proposal suggestions.

* ``api_keys``: personal API keys (and, from Phase 6, agents' service-account keys).
  Only the public ``lookup_id`` (12 base62 characters, unique) and the SHA-256 of the
  whole key (``secret_hash``) are stored. ``scopes`` is a ``varchar[]`` of
  ``read | write | evaluate | mcp`` (1-4); ``project_ids`` a ``uuid[]`` project
  restriction (null = every project the owner can access, else 1-50 ids, none NULL).
  ``write`` and ``evaluate`` keys always have ``read``. ``created_auth_method`` is the
  sign-in method of the session that created the key (it works only while that method
  is available). Names are unique per owner, any case, among keys that aren't revoked
  (partial unique index); revoked keys keep their row (``revoked_at``,
  ``revoked_by_id``).
* ``proposal_suggestions``: suggested text for one proposal section (REST or the MCP
  tool ``propose_proposal_section``), ``pending`` until the owner or an admin accepts
  or discards it; at most one pending suggestion per author per section (partial
  unique index).

The audit log needs no change: the new actions (``api_key.create``, ``api_key.revoke``,
``mcp.call``) are rows like any other.

Downgrade drops both tables: every API key stops working and suggestions are lost.

Hand-written to match the models exactly (``tests/test_domain_schema.py`` compares
them). See docs/erd.md and docs/api/contract-phase5.md.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-02
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SECTION_KEYS = (
    "summary",
    "problem",
    "solution",
    "market",
    "cost",
    "benefits",
    "risks",
    "next_steps",
)
SUGGESTION_SOURCES = ("api", "mcp", "ai")
SUGGESTION_STATUSES = ("pending", "accepted", "discarded")
AUTH_METHODS = ("dev_login", "sso", "break_glass")
API_KEY_SCOPES = "ARRAY['read', 'write', 'evaluate', 'mcp']::varchar[]"


def _id() -> sa.Column[Any]:
    return sa.Column("id", sa.Uuid(), nullable=False)


def _created_at() -> sa.Column[Any]:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def _values(values: Sequence[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _enum_check(column: str, values: Sequence[str], name: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(f"{column} IN ({_values(values)})", name=op.f(name))


def _fk(column: str, target: str, name: str, ondelete: str = "CASCADE") -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint([column], [target], name=op.f(name), ondelete=ondelete)


def _length(values: Sequence[str]) -> int:
    return max(len(value) for value in values)


def _api_keys() -> None:
    op.create_table(
        "api_keys",
        _id(),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("lookup_id", sa.String(length=12), nullable=False),
        sa.Column("secret_hash", sa.String(length=64), nullable=False),
        sa.Column("scopes", postgresql.ARRAY(sa.String(length=16)), nullable=False),
        sa.Column("project_ids", postgresql.ARRAY(sa.Uuid()), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("created_auth_method", sa.String(length=_length(AUTH_METHODS)), nullable=False),
        _created_at(),
        sa.CheckConstraint(
            "lookup_id ~ '^[A-Za-z0-9]{12}$'", name=op.f("ck_api_keys_lookup_id_format")
        ),
        sa.CheckConstraint(
            "secret_hash ~ '^[0-9a-f]{64}$'", name=op.f("ck_api_keys_secret_hash_format")
        ),
        sa.CheckConstraint("length(name) > 0", name=op.f("ck_api_keys_name_not_empty")),
        sa.CheckConstraint(
            f"cardinality(scopes) BETWEEN 1 AND 4 AND scopes <@ {API_KEY_SCOPES}",
            name=op.f("ck_api_keys_scopes"),
        ),
        sa.CheckConstraint(
            "'read' = ANY (scopes) OR NOT (scopes && ARRAY['write', 'evaluate']::varchar[])",
            name=op.f("ck_api_keys_scopes_include_read"),
        ),
        sa.CheckConstraint(
            "project_ids IS NULL OR (cardinality(project_ids) BETWEEN 1 AND 50"
            " AND array_position(project_ids, NULL) IS NULL)",
            name=op.f("ck_api_keys_project_ids_not_empty"),
        ),
        _enum_check("created_auth_method", AUTH_METHODS, "ck_api_keys_created_auth_method"),
        sa.CheckConstraint(
            "revoked_by_id IS NULL OR revoked_at IS NOT NULL",
            name=op.f("ck_api_keys_revoked_by_needs_revoked"),
        ),
        _fk("user_id", "users.id", "fk_api_keys_user_id_users"),
        _fk("revoked_by_id", "users.id", "fk_api_keys_revoked_by_id_users", "SET NULL"),
        _fk("created_by_id", "users.id", "fk_api_keys_created_by_id_users", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_keys")),
        sa.UniqueConstraint("lookup_id", name=op.f("uq_api_keys_lookup_id")),
    )
    op.create_index(op.f("ix_api_keys_user_id"), "api_keys", ["user_id"])
    op.create_index(
        "uq_api_keys_user_id_name_lower",
        "api_keys",
        ["user_id", sa.literal_column("lower(name)")],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index(
        "ix_api_keys_created_at_id_unrevoked",
        "api_keys",
        ["created_at", "id"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )


def _proposal_suggestions() -> None:
    op.create_table(
        "proposal_suggestions",
        _id(),
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column("section_key", sa.String(length=_length(SECTION_KEYS)), nullable=False),
        sa.Column("body_md", sa.Text(), nullable=False),
        sa.Column("base_version", sa.Integer(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=True),
        sa.Column("source", sa.String(length=_length(SUGGESTION_SOURCES)), nullable=False),
        sa.Column(
            "status",
            sa.String(length=_length(SUGGESTION_STATUSES)),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("decided_by_id", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        _enum_check("section_key", SECTION_KEYS, "ck_proposal_suggestions_section_key"),
        _enum_check("source", SUGGESTION_SOURCES, "ck_proposal_suggestions_source"),
        _enum_check("status", SUGGESTION_STATUSES, "ck_proposal_suggestions_status"),
        sa.CheckConstraint(
            "base_version >= 1", name=op.f("ck_proposal_suggestions_base_version_positive")
        ),
        sa.CheckConstraint(
            "length(body_md) > 0", name=op.f("ck_proposal_suggestions_body_not_empty")
        ),
        sa.CheckConstraint(
            "(status = 'pending') = (decided_at IS NULL)",
            name=op.f("ck_proposal_suggestions_decided_iff_not_pending"),
        ),
        _fk("proposal_id", "proposals.id", "fk_proposal_suggestions_proposal_id_proposals"),
        _fk("author_id", "users.id", "fk_proposal_suggestions_author_id_users", "SET NULL"),
        _fk(
            "decided_by_id",
            "users.id",
            "fk_proposal_suggestions_decided_by_id_users",
            "SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_proposal_suggestions")),
    )
    op.create_index(
        op.f("ix_proposal_suggestions_proposal_id"), "proposal_suggestions", ["proposal_id"]
    )
    op.create_index(
        op.f("ix_proposal_suggestions_author_id"), "proposal_suggestions", ["author_id"]
    )
    op.create_index(
        "uq_proposal_suggestions_pending_author_section",
        "proposal_suggestions",
        ["proposal_id", "section_key", "author_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_proposal_suggestions_proposal_id_created_at_pending",
        "proposal_suggestions",
        ["proposal_id", "created_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )


def upgrade() -> None:
    _api_keys()
    _proposal_suggestions()


def downgrade() -> None:
    op.drop_table("proposal_suggestions")
    op.drop_table("api_keys")
