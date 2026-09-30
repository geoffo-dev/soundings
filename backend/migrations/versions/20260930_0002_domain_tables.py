"""Domain tables for Phase 1: users, projects, ideas, evaluations, activity.

Hand-reviewed from autogenerate. Enum columns are ``VARCHAR`` + one named ``CHECK``
constraint (``app.models.types.str_enum``). ``pg_trgm`` backs the idea search
indexes: it is a trusted extension, so a user with CREATE on the database can
install it, and the downgrade leaves it installed (it may predate us or be shared).
The ``project_effective_roles`` view is the one place queries read project roles
from (Phase 2 redefines it to include group grants). See docs/erd.md.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-30
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _id() -> sa.Column[Any]:
    return sa.Column("id", sa.Uuid(), nullable=False)


def _timestamp(name: str) -> sa.Column[Any]:
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def _flag(name: str, *, default: bool) -> sa.Column[Any]:
    return sa.Column(
        name, sa.Boolean(), server_default=sa.text(str(default).lower()), nullable=False
    )


def _jsonb(name: str) -> sa.Column[Any]:
    return sa.Column(
        name,
        postgresql.JSONB(astext_type=sa.Text()),
        server_default=sa.text("'{}'::jsonb"),
        nullable=False,
    )


def _enum_check(column: str, values: Sequence[str], name: str) -> sa.CheckConstraint:
    allowed = ", ".join(f"'{value}'" for value in values)
    return sa.CheckConstraint(f"{column} IN ({allowed})", name=op.f(name))


def _fk(
    column: str, target: str, name: str, ondelete: str | None = "CASCADE", **kwargs: Any
) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint([column], [target], name=op.f(name), ondelete=ondelete, **kwargs)


# Phase 1: effective role = direct role. Phase 2 replaces the body (same columns, in
# the same order) with the highest of direct and group-granted roles.
EFFECTIVE_ROLES_VIEW = """
CREATE VIEW project_effective_roles AS
SELECT project_id, user_id, role FROM project_members
"""


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # --- users & sessions ---------------------------------------------------------
    op.create_table(
        "users",
        _id(),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column("avatar_url", sa.String(length=2048), nullable=True),
        _flag("is_platform_admin", default=False),
        _flag("is_active", default=True),
        _flag("is_service_account", default=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_index(
        "uq_users_email_lower", "users", [sa.literal_column("lower(email)")], unique=True
    )

    op.create_table(
        "user_sessions",
        _id(),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("csrf_token", sa.String(length=64), nullable=False),
        _timestamp("created_at"),
        _timestamp("last_seen_at"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_agent", sa.String(length=200), nullable=True),
        _fk("user_id", "users.id", "fk_user_sessions_user_id_users"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_user_sessions_token_hash")),
    )
    op.create_index(op.f("ix_user_sessions_user_id"), "user_sessions", ["user_id"])
    op.create_index(op.f("ix_user_sessions_expires_at"), "user_sessions", ["expires_at"])

    # --- projects -----------------------------------------------------------------
    op.create_table(
        "projects",
        _id(),
        sa.Column("slug", sa.String(length=48), nullable=False),
        sa.Column("key", sa.String(length=6), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("visibility", sa.String(length=8), server_default="private", nullable=False),
        _flag("allow_volunteer_owners", default=True),
        _flag("public_submission_enabled", default=False),
        _jsonb("status_labels"),
        sa.Column(
            "default_evaluation_days", sa.Integer(), server_default=sa.text("7"), nullable=False
        ),
        sa.Column("next_idea_number", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.CheckConstraint(
            "slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$' AND length(slug) BETWEEN 2 AND 48",
            name=op.f("ck_projects_slug"),
        ),
        sa.CheckConstraint("key ~ '^[A-Z][A-Z0-9]{1,5}$'", name=op.f("ck_projects_key")),
        _enum_check("visibility", ["private", "internal"], "ck_projects_visibility"),
        sa.CheckConstraint(
            "default_evaluation_days BETWEEN 1 AND 90", name=op.f("ck_projects_evaluation_days")
        ),
        sa.CheckConstraint("next_idea_number >= 1", name=op.f("ck_projects_next_idea_number")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_projects")),
        sa.UniqueConstraint("slug", name=op.f("uq_projects_slug")),
        sa.UniqueConstraint("key", name=op.f("uq_projects_key")),
    )

    op.create_table(
        "project_members",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=6), nullable=False),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        _enum_check("role", ["admin", "member", "viewer"], "ck_project_members_role"),
        _fk("project_id", "projects.id", "fk_project_members_project_id_projects"),
        _fk("user_id", "users.id", "fk_project_members_user_id_users"),
        sa.PrimaryKeyConstraint("project_id", "user_id", name=op.f("pk_project_members")),
    )
    op.create_index(op.f("ix_project_members_user_id"), "project_members", ["user_id"])
    op.execute(EFFECTIVE_ROLES_VIEW)

    op.create_table(
        "rubric_criteria",
        _id(),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=40), nullable=False),
        sa.Column("description", sa.String(length=200), server_default="", nullable=False),
        sa.Column(
            "weight",
            sa.Numeric(precision=4, scale=2),
            server_default=sa.text("1.00"),
            nullable=False,
        ),
        _flag("inverted", default=False),
        _jsonb("guidance"),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.CheckConstraint("weight > 0", name=op.f("ck_rubric_criteria_weight_positive")),
        _fk("project_id", "projects.id", "fk_rubric_criteria_project_id_projects"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rubric_criteria")),
    )
    op.create_index(
        "ix_rubric_criteria_project_id_position", "rubric_criteria", ["project_id", "position"]
    )
    op.create_index(
        "uq_rubric_criteria_project_id_name_lower",
        "rubric_criteria",
        ["project_id", sa.literal_column("lower(name)")],
        unique=True,
        postgresql_where=sa.text("archived_at IS NULL"),
    )

    op.create_table(
        "tags",
        _id(),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=32), nullable=False),
        _timestamp("created_at"),
        _fk("project_id", "projects.id", "fk_tags_project_id_projects"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tags")),
    )
    op.create_index(
        "uq_tags_project_id_name_lower",
        "tags",
        ["project_id", sa.literal_column("lower(name)")],
        unique=True,
    )

    # --- ideas --------------------------------------------------------------------
    op.create_table(
        "ideas",
        _id(),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("summary", sa.String(length=500), server_default="", nullable=False),
        sa.Column("description_md", sa.Text(), server_default="", nullable=False),
        sa.Column("status", sa.String(length=11), server_default="new", nullable=False),
        sa.Column("resolution", sa.String(length=8), nullable=True),
        sa.Column("owner_id", sa.Uuid(), nullable=True),
        sa.Column("submitted_by_id", sa.Uuid(), nullable=True),
        sa.Column("evaluation_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evaluation_closed_at", sa.DateTime(timezone=True), nullable=True),
        _timestamp("last_activity_at"),
        sa.Column("vote_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("aggregate_score", sa.Numeric(precision=2, scale=1), nullable=True),
        sa.Column("aggregate_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        _flag("high_disagreement", default=False),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        _enum_check(
            "status",
            ["new", "evaluating", "shortlisted", "proposal", "closed"],
            "ck_ideas_status",
        ),
        _enum_check("resolution", ["accepted", "rejected", "parked"], "ck_ideas_resolution"),
        sa.CheckConstraint(
            "(status = 'closed') = (resolution IS NOT NULL)",
            name=op.f("ck_ideas_resolution_iff_closed"),
        ),
        sa.CheckConstraint("number >= 1", name=op.f("ck_ideas_number_positive")),
        sa.CheckConstraint("vote_count >= 0", name=op.f("ck_ideas_vote_count_non_negative")),
        sa.CheckConstraint(
            "aggregate_score IS NULL OR aggregate_score BETWEEN 1 AND 5",
            name=op.f("ck_ideas_aggregate_range"),
        ),
        _fk("project_id", "projects.id", "fk_ideas_project_id_projects"),
        _fk("owner_id", "users.id", "fk_ideas_owner_id_users", "SET NULL"),
        _fk("submitted_by_id", "users.id", "fk_ideas_submitted_by_id_users", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ideas")),
        sa.UniqueConstraint("project_id", "number", name=op.f("uq_ideas_project_id_number")),
    )
    op.create_index(
        "ix_ideas_project_id_last_activity_at", "ideas", ["project_id", "last_activity_at", "id"]
    )
    op.create_index(
        "ix_ideas_project_id_status_last_activity_at",
        "ideas",
        ["project_id", "status", "last_activity_at", "id"],
    )
    op.create_index(
        "ix_ideas_project_id_aggregate_score", "ideas", ["project_id", "aggregate_score"]
    )
    op.create_index(
        "ix_ideas_evaluation_due_at_open",
        "ideas",
        ["evaluation_due_at"],
        postgresql_where=sa.text(
            "evaluation_due_at IS NOT NULL AND evaluation_closed_at IS NULL AND status <> 'closed'"
        ),
    )
    op.create_index(op.f("ix_ideas_last_activity_at"), "ideas", ["last_activity_at"])
    op.create_index(op.f("ix_ideas_owner_id"), "ideas", ["owner_id"])
    op.create_index(op.f("ix_ideas_submitted_by_id"), "ideas", ["submitted_by_id"])
    for column in ("title", "summary"):
        op.create_index(
            f"ix_ideas_{column}_trgm",
            "ideas",
            [column],
            postgresql_using="gin",
            postgresql_ops={column: "gin_trgm_ops"},
        )

    op.create_table(
        "idea_tags",
        sa.Column("idea_id", sa.Uuid(), nullable=False),
        sa.Column("tag_id", sa.Uuid(), nullable=False),
        _fk("idea_id", "ideas.id", "fk_idea_tags_idea_id_ideas"),
        _fk("tag_id", "tags.id", "fk_idea_tags_tag_id_tags"),
        sa.PrimaryKeyConstraint("idea_id", "tag_id", name=op.f("pk_idea_tags")),
    )
    op.create_index(op.f("ix_idea_tags_tag_id"), "idea_tags", ["tag_id"])

    op.create_table(
        "idea_evaluators",
        sa.Column("idea_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("invited_by_id", sa.Uuid(), nullable=True),
        _timestamp("invited_at"),
        _fk("idea_id", "ideas.id", "fk_idea_evaluators_idea_id_ideas"),
        _fk("user_id", "users.id", "fk_idea_evaluators_user_id_users"),
        _fk("invited_by_id", "users.id", "fk_idea_evaluators_invited_by_id_users", "SET NULL"),
        sa.PrimaryKeyConstraint("idea_id", "user_id", name=op.f("pk_idea_evaluators")),
    )
    op.create_index(op.f("ix_idea_evaluators_user_id"), "idea_evaluators", ["user_id"])

    for table in ("idea_votes", "idea_watchers"):
        op.create_table(
            table,
            sa.Column("idea_id", sa.Uuid(), nullable=False),
            sa.Column("user_id", sa.Uuid(), nullable=False),
            _timestamp("created_at"),
            _fk("idea_id", "ideas.id", f"fk_{table}_idea_id_ideas"),
            _fk("user_id", "users.id", f"fk_{table}_user_id_users"),
            sa.PrimaryKeyConstraint("idea_id", "user_id", name=op.f(f"pk_{table}")),
        )
        op.create_index(op.f(f"ix_{table}_user_id"), table, ["user_id"])

    # --- evaluations --------------------------------------------------------------
    op.create_table(
        "evaluations",
        _id(),
        sa.Column("idea_id", sa.Uuid(), nullable=False),
        sa.Column("evaluator_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=9), server_default="draft", nullable=False),
        sa.Column("recommendation", sa.String(length=5), nullable=True),
        sa.Column("comment", sa.Text(), server_default="", nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        _flag("include_in_aggregate", default=True),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        _enum_check("status", ["draft", "submitted"], "ck_evaluations_status"),
        _enum_check("recommendation", ["go", "maybe", "no"], "ck_evaluations_recommendation"),
        sa.CheckConstraint(
            "status <> 'submitted' OR (recommendation IS NOT NULL AND submitted_at IS NOT NULL)",
            name=op.f("ck_evaluations_submitted_complete"),
        ),
        sa.ForeignKeyConstraint(
            ["idea_id", "evaluator_id"],
            ["idea_evaluators.idea_id", "idea_evaluators.user_id"],
            name="fk_evaluations_idea_id_evaluator_id_idea_evaluators",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evaluations")),
        sa.UniqueConstraint(
            "idea_id", "evaluator_id", name=op.f("uq_evaluations_idea_id_evaluator_id")
        ),
    )
    op.create_index(op.f("ix_evaluations_evaluator_id"), "evaluations", ["evaluator_id"])

    op.create_table(
        "evaluation_scores",
        sa.Column("evaluation_id", sa.Uuid(), nullable=False),
        sa.Column("criterion_id", sa.Uuid(), nullable=False),
        sa.Column("score", sa.SmallInteger(), nullable=True),
        sa.Column("comment", sa.String(length=1000), server_default="", nullable=False),
        sa.CheckConstraint("score BETWEEN 1 AND 5", name=op.f("ck_evaluation_scores_score_range")),
        _fk("evaluation_id", "evaluations.id", "fk_evaluation_scores_evaluation_id_evaluations"),
        # NO ACTION checked at commit: a scored criterion can't be deleted (archive it),
        # but deleting its project, which cascades to the scores too, works.
        _fk(
            "criterion_id",
            "rubric_criteria.id",
            "fk_evaluation_scores_criterion_id_rubric_criteria",
            None,
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.PrimaryKeyConstraint("evaluation_id", "criterion_id", name=op.f("pk_evaluation_scores")),
    )
    op.create_index(
        op.f("ix_evaluation_scores_criterion_id"), "evaluation_scores", ["criterion_id"]
    )

    # --- comments, activity, audit ------------------------------------------------
    op.create_table(
        "comments",
        _id(),
        sa.Column("idea_id", sa.Uuid(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=True),
        sa.Column("body_md", sa.Text(), nullable=False),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        _fk("idea_id", "ideas.id", "fk_comments_idea_id_ideas"),
        _fk("author_id", "users.id", "fk_comments_author_id_users", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_comments")),
    )
    op.create_index("ix_comments_idea_id_created_at", "comments", ["idea_id", "created_at"])
    op.create_index(op.f("ix_comments_author_id"), "comments", ["author_id"])

    op.create_table(
        "activity_events",
        _id(),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("idea_id", sa.Uuid(), nullable=True),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("type", sa.String(length=40), nullable=False),
        sa.Column("comment_id", sa.Uuid(), nullable=True),
        _jsonb("payload"),
        _timestamp("created_at"),
        _fk("project_id", "projects.id", "fk_activity_events_project_id_projects"),
        _fk("idea_id", "ideas.id", "fk_activity_events_idea_id_ideas"),
        _fk("actor_id", "users.id", "fk_activity_events_actor_id_users", "SET NULL"),
        _fk("comment_id", "comments.id", "fk_activity_events_comment_id_comments"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_activity_events")),
    )
    op.create_index(
        "ix_activity_events_idea_id_created_at",
        "activity_events",
        ["idea_id", "created_at", "id"],
    )
    op.create_index(
        "ix_activity_events_project_id_created_at", "activity_events", ["project_id", "created_at"]
    )
    op.create_index(op.f("ix_activity_events_actor_id"), "activity_events", ["actor_id"])
    op.create_index(op.f("ix_activity_events_comment_id"), "activity_events", ["comment_id"])

    op.create_table(
        "audit_log",
        _id(),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("target_type", sa.String(length=40), nullable=True),
        sa.Column("target_id", sa.Uuid(), nullable=True),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        _jsonb("details"),
        _timestamp("created_at"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
    )
    op.create_index(op.f("ix_audit_log_created_at"), "audit_log", ["created_at"])
    op.create_index(op.f("ix_audit_log_actor_id"), "audit_log", ["actor_id"])
    op.create_index("ix_audit_log_project_id_created_at", "audit_log", ["project_id", "created_at"])
    op.create_index("ix_audit_log_target_type_target_id", "audit_log", ["target_type", "target_id"])


def downgrade() -> None:
    op.execute("DROP VIEW project_effective_roles")
    # Reverse dependency order; indexes and constraints go with their tables.
    for table in (
        "audit_log",
        "activity_events",
        "comments",
        "evaluation_scores",
        "evaluations",
        "idea_watchers",
        "idea_votes",
        "idea_evaluators",
        "idea_tags",
        "ideas",
        "tags",
        "rubric_criteria",
        "project_members",
        "projects",
        "user_sessions",
        "users",
    ):
        op.drop_table(table)
    # pg_trgm stays installed: it may have been there before this revision.
