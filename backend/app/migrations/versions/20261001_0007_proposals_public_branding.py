"""Phase 4: proposals, public submission and branding.

* ``proposals`` (one per idea), ``proposal_sections`` (one Markdown text per fixed
  template section, each with its own ``version`` for optimistic concurrency),
  ``proposal_threads`` (margin comment threads anchored to a section, resolvable) and
  ``proposal_comments`` (flat replies, soft-deleted).
* ``public_submissions``: the public submitter of an idea (optional name and email,
  confirmation, opt-in to updates, the tracking token hashed and sealed, a copy of the
  title and summary they sent, erasure);
  ``altcha_used_challenges``: solved ALTCHA challenges until they expire (replay
  protection).
* ``ideas.held_for`` (``email_verification`` | ``moderation``; null = visible) with
  partial indexes for the moderation queue and the cleanup of unconfirmed submissions.
* ``projects``: ``public_require_email_verification``, ``public_moderation_required``
  (default true) and ``public_intro_md`` next to Phase 1's ``public_submission_enabled``.
* ``outbound_email.idea_id`` for public-submitter emails (required for the two
  submission types and only for them; they go to ``to_address``), with partial indexes
  for an idea's emails and for the per-address limit (sub-addresses folded). Submitter
  emails queued before 0007 (none outside tests: Phase 3 had no producer) are deleted
  first: they name no idea and can't be rendered any more.
* ``branding_profiles`` (the global profile has ``project_id`` null, at most one row:
  ``UNIQUE NULLS NOT DISTINCT``; hex colours and the font key are checked) and
  ``brand_assets`` (logos and favicons as PNG or SVG bytes, at most 1 MiB).

Downgrade deletes ideas still held (an older app can't hide them) and submitter
emails (an older worker can't render them), then drops everything above. Proposals,
branding, uploaded images and submitter details are lost; public ideas stay as
anonymous ideas.

Hand-written to match the models exactly (``tests/test_domain_schema.py`` compares
them). See docs/erd.md and docs/api/contract-phase4.md.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-01
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
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
HOLD_REASONS = ("email_verification", "moderation")
BRAND_FONTS = ("inter", "ibm_plex_sans", "source_serif_4", "atkinson_hyperlegible")
ASSET_KINDS = ("logo", "favicon")
SUBMISSION_EMAIL_TYPES = ("submission_received", "submission_status_changed")
HEX_COLOR = "^#[0-9a-f]{6}$"
# app.models.notification.SUBMITTER_ADDRESS_KEY_SQL as of this revision.
SUBMITTER_ADDRESS_KEY = r"lower(regexp_replace(to_address, '\+[^@]*@', '@'))"


def _id() -> sa.Column[Any]:
    return sa.Column("id", sa.Uuid(), nullable=False)


def _timestamp(name: str) -> sa.Column[Any]:
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def _values(values: Sequence[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _enum_check(column: str, values: Sequence[str], name: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(f"{column} IN ({_values(values)})", name=op.f(name))


def _fk(column: str, target: str, name: str, ondelete: str = "CASCADE") -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint([column], [target], name=op.f(name), ondelete=ondelete)


def _length(values: Sequence[str]) -> int:
    return max(len(value) for value in values)


def _proposals() -> None:
    op.create_table(
        "proposals",
        _id(),
        sa.Column("idea_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        _fk("idea_id", "ideas.id", "fk_proposals_idea_id_ideas"),
        _fk("created_by_id", "users.id", "fk_proposals_created_by_id_users", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_proposals")),
        sa.UniqueConstraint("idea_id", name=op.f("uq_proposals_idea_id")),
    )
    op.create_table(
        "proposal_sections",
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=_length(SECTION_KEYS)), nullable=False),
        sa.Column("body_md", sa.Text(), server_default="", nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("updated_by_id", sa.Uuid(), nullable=True),
        _timestamp("updated_at"),
        _enum_check("key", SECTION_KEYS, "ck_proposal_sections_key"),
        sa.CheckConstraint("version >= 1", name=op.f("ck_proposal_sections_version_positive")),
        _fk("proposal_id", "proposals.id", "fk_proposal_sections_proposal_id_proposals"),
        _fk("updated_by_id", "users.id", "fk_proposal_sections_updated_by_id_users", "SET NULL"),
        sa.PrimaryKeyConstraint("proposal_id", "key", name=op.f("pk_proposal_sections")),
    )
    op.create_table(
        "proposal_threads",
        _id(),
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column("section_key", sa.String(length=_length(SECTION_KEYS)), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by_id", sa.Uuid(), nullable=True),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        _enum_check("section_key", SECTION_KEYS, "ck_proposal_threads_section_key"),
        _fk("proposal_id", "proposals.id", "fk_proposal_threads_proposal_id_proposals"),
        _fk("created_by_id", "users.id", "fk_proposal_threads_created_by_id_users", "SET NULL"),
        _fk("resolved_by_id", "users.id", "fk_proposal_threads_resolved_by_id_users", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_proposal_threads")),
    )
    op.create_index(
        "ix_proposal_threads_proposal_id_created_at",
        "proposal_threads",
        ["proposal_id", "created_at"],
    )
    op.create_table(
        "proposal_comments",
        _id(),
        sa.Column("thread_id", sa.Uuid(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=True),
        sa.Column("body_md", sa.Text(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        _fk("thread_id", "proposal_threads.id", "fk_proposal_comments_thread_id_proposal_threads"),
        _fk("author_id", "users.id", "fk_proposal_comments_author_id_users", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_proposal_comments")),
    )
    op.create_index(
        "ix_proposal_comments_thread_id_created_at",
        "proposal_comments",
        ["thread_id", "created_at"],
    )
    op.create_index(op.f("ix_proposal_comments_author_id"), "proposal_comments", ["author_id"])


def _public_submission() -> None:
    op.add_column(
        "ideas",
        sa.Column("held_for", sa.String(length=_length(HOLD_REASONS)), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_ideas_held_for"), "ideas", f"held_for IN ({_values(HOLD_REASONS)})"
    )
    op.create_index(
        "ix_ideas_project_id_created_at_moderation",
        "ideas",
        ["project_id", "created_at", "id"],
        postgresql_where=sa.text("held_for = 'moderation'"),
    )
    op.create_index(
        "ix_ideas_created_at_email_verification",
        "ideas",
        ["created_at"],
        postgresql_where=sa.text("held_for = 'email_verification'"),
    )

    op.add_column(
        "projects",
        sa.Column(
            "public_require_email_verification",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column(
        "projects",
        sa.Column(
            "public_moderation_required",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
    )
    op.add_column(
        "projects", sa.Column("public_intro_md", sa.Text(), server_default="", nullable=False)
    )

    op.create_table(
        "public_submissions",
        _id(),
        sa.Column("idea_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=True),
        sa.Column("email", sa.String(length=254), nullable=True),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("wants_updates", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("tracking_token_hash", sa.String(length=64), nullable=True),
        sa.Column("tracking_token_sealed", sa.String(length=255), nullable=True),
        sa.Column("submitted_title", sa.String(length=200), nullable=True),
        sa.Column("submitted_summary", sa.String(length=500), nullable=True),
        sa.Column("erased_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("erased_by_id", sa.Uuid(), nullable=True),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.CheckConstraint(
            "email IS NOT NULL OR email_verified_at IS NULL",
            name=op.f("ck_public_submissions_verified_needs_email"),
        ),
        sa.CheckConstraint(
            "email IS NOT NULL OR NOT wants_updates",
            name=op.f("ck_public_submissions_updates_need_email"),
        ),
        sa.CheckConstraint(
            "(tracking_token_hash IS NULL) = (tracking_token_sealed IS NULL)",
            name=op.f("ck_public_submissions_tracking_token_pair"),
        ),
        sa.CheckConstraint(
            "erased_at IS NULL OR (name IS NULL AND email IS NULL AND tracking_token_hash IS NULL"
            " AND submitted_title IS NULL AND submitted_summary IS NULL)",
            name=op.f("ck_public_submissions_erased_is_empty"),
        ),
        sa.CheckConstraint(
            "erased_at IS NOT NULL"
            " OR (submitted_title IS NOT NULL AND submitted_summary IS NOT NULL)",
            name=op.f("ck_public_submissions_submitted_copy_until_erased"),
        ),
        _fk("idea_id", "ideas.id", "fk_public_submissions_idea_id_ideas"),
        _fk("project_id", "projects.id", "fk_public_submissions_project_id_projects"),
        _fk("erased_by_id", "users.id", "fk_public_submissions_erased_by_id_users", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_public_submissions")),
        sa.UniqueConstraint("idea_id", name=op.f("uq_public_submissions_idea_id")),
        sa.UniqueConstraint(
            "tracking_token_hash", name=op.f("uq_public_submissions_tracking_token_hash")
        ),
    )
    op.create_index(
        "ix_public_submissions_project_id_created_at",
        "public_submissions",
        ["project_id", "created_at"],
    )
    op.create_index(
        "ix_public_submissions_created_at_unconfirmed",
        "public_submissions",
        ["created_at"],
        postgresql_where=sa.text("email IS NOT NULL AND email_verified_at IS NULL"),
    )

    op.create_table(
        "altcha_used_challenges",
        sa.Column("signature", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("signature", name=op.f("pk_altcha_used_challenges")),
    )
    op.create_index(
        op.f("ix_altcha_used_challenges_expires_at"), "altcha_used_challenges", ["expires_at"]
    )

    submission_types = _values(SUBMISSION_EMAIL_TYPES)  # constants, not input
    op.execute(f"DELETE FROM outbound_email WHERE type IN ({submission_types})")  # noqa: S608
    op.add_column("outbound_email", sa.Column("idea_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_outbound_email_idea_id_ideas"),
        "outbound_email",
        "ideas",
        ["idea_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_check_constraint(
        op.f("ck_outbound_email_idea_iff_submission_type"),
        "outbound_email",
        f"(idea_id IS NOT NULL) = (type IN ({_values(SUBMISSION_EMAIL_TYPES)}))",
    )
    op.create_check_constraint(
        op.f("ck_outbound_email_submission_to_address"),
        "outbound_email",
        "idea_id IS NULL OR to_address IS NOT NULL",
    )
    op.create_index(
        "ix_outbound_email_idea_id",
        "outbound_email",
        ["idea_id", "created_at"],
        postgresql_where=sa.text("idea_id IS NOT NULL"),
    )
    op.create_index(
        "ix_outbound_email_submission_address",
        "outbound_email",
        [sa.literal_column(SUBMITTER_ADDRESS_KEY), "created_at"],
        postgresql_where=sa.text("type = 'submission_received'"),
    )


def _branding() -> None:
    op.create_table(
        "brand_assets",
        _id(),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=_length(ASSET_KINDS)), nullable=False),
        sa.Column("content_type", sa.String(length=20), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        _timestamp("created_at"),
        _enum_check("kind", ASSET_KINDS, "ck_brand_assets_kind"),
        sa.CheckConstraint(
            "content_type IN ('image/png', 'image/svg+xml')",
            name=op.f("ck_brand_assets_content_type"),
        ),
        sa.CheckConstraint(
            "byte_size BETWEEN 1 AND 1048576", name=op.f("ck_brand_assets_byte_size_range")
        ),
        sa.CheckConstraint(
            "octet_length(data) = byte_size", name=op.f("ck_brand_assets_byte_size_matches")
        ),
        sa.CheckConstraint(
            "(width IS NULL OR width BETWEEN 1 AND 4096)"
            " AND (height IS NULL OR height BETWEEN 1 AND 4096)",
            name=op.f("ck_brand_assets_dimensions_range"),
        ),
        _fk("project_id", "projects.id", "fk_brand_assets_project_id_projects"),
        _fk("created_by_id", "users.id", "fk_brand_assets_created_by_id_users", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_brand_assets")),
    )
    op.create_index(
        "ix_brand_assets_project_id_created_at", "brand_assets", ["project_id", "created_at"]
    )

    op.create_table(
        "branding_profiles",
        _id(),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("app_name", sa.String(length=40), nullable=True),
        sa.Column("primary_color", sa.String(length=7), nullable=True),
        sa.Column("accent_color", sa.String(length=7), nullable=True),
        sa.Column("font", sa.String(length=_length(BRAND_FONTS)), nullable=True),
        sa.Column("email_footer", sa.String(length=500), nullable=True),
        sa.Column("logo_asset_id", sa.Uuid(), nullable=True),
        sa.Column("favicon_asset_id", sa.Uuid(), nullable=True),
        sa.Column("updated_by_id", sa.Uuid(), nullable=True),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.CheckConstraint(
            f"primary_color ~ '{HEX_COLOR}'", name=op.f("ck_branding_profiles_primary_color_hex")
        ),
        sa.CheckConstraint(
            f"accent_color ~ '{HEX_COLOR}'", name=op.f("ck_branding_profiles_accent_color_hex")
        ),
        sa.CheckConstraint(
            "char_length(app_name) BETWEEN 1 AND 40",
            name=op.f("ck_branding_profiles_app_name_length"),
        ),
        _enum_check("font", BRAND_FONTS, "ck_branding_profiles_font"),
        _fk("project_id", "projects.id", "fk_branding_profiles_project_id_projects"),
        _fk(
            "logo_asset_id",
            "brand_assets.id",
            "fk_branding_profiles_logo_asset_id_brand_assets",
            "SET NULL",
        ),
        _fk(
            "favicon_asset_id",
            "brand_assets.id",
            "fk_branding_profiles_favicon_asset_id_brand_assets",
            "SET NULL",
        ),
        _fk("updated_by_id", "users.id", "fk_branding_profiles_updated_by_id_users", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_branding_profiles")),
        sa.UniqueConstraint(
            "project_id",
            name=op.f("uq_branding_profiles_project_id"),
            postgresql_nulls_not_distinct=True,
        ),
    )


def upgrade() -> None:
    _proposals()
    _public_submission()
    _branding()


def downgrade() -> None:
    op.drop_table("branding_profiles")
    op.drop_table("brand_assets")  # its index goes with it

    # An older app can't hide held ideas or render submitter emails: remove them.
    op.execute("DELETE FROM ideas WHERE held_for IS NOT NULL")
    op.execute("DELETE FROM outbound_email WHERE idea_id IS NOT NULL")
    op.drop_index("ix_outbound_email_submission_address", table_name="outbound_email")
    op.drop_index("ix_outbound_email_idea_id", table_name="outbound_email")
    op.drop_constraint(
        op.f("ck_outbound_email_submission_to_address"), "outbound_email", type_="check"
    )
    op.drop_constraint(
        op.f("ck_outbound_email_idea_iff_submission_type"), "outbound_email", type_="check"
    )
    op.drop_constraint(
        op.f("fk_outbound_email_idea_id_ideas"), "outbound_email", type_="foreignkey"
    )
    op.drop_column("outbound_email", "idea_id")
    op.drop_table("altcha_used_challenges")
    op.drop_table("public_submissions")
    op.drop_column("projects", "public_intro_md")
    op.drop_column("projects", "public_moderation_required")
    op.drop_column("projects", "public_require_email_verification")
    op.drop_index("ix_ideas_created_at_email_verification", table_name="ideas")
    op.drop_index("ix_ideas_project_id_created_at_moderation", table_name="ideas")
    op.drop_constraint(op.f("ck_ideas_held_for"), "ideas", type_="check")
    op.drop_column("ideas", "held_for")

    op.drop_table("proposal_comments")
    op.drop_table("proposal_threads")
    op.drop_table("proposal_sections")
    op.drop_table("proposals")
