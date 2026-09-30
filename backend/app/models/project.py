"""Projects, their members, rubric and tags."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    TableClause,
    Text,
    Uuid,
    column,
    func,
    table,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, utcnow
from app.models.enums import ProjectRole, ProjectVisibility
from app.models.types import str_enum

SLUG_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"
"""Lower-case words joined by single hyphens, e.g. ``customer-innovation``."""

KEY_PATTERN = r"^[A-Z][A-Z0-9]{1,5}$"
"""Idea-key prefix: 2-6 upper-case letters/digits starting with a letter, e.g. ``CUST``."""


class Project(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A space for ideas. ``slug`` (URLs) and ``key`` (idea keys) never change."""

    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint(f"slug ~ '{SLUG_PATTERN}' AND length(slug) BETWEEN 2 AND 48", name="slug"),
        CheckConstraint(f"key ~ '{KEY_PATTERN}'", name="key"),
        CheckConstraint("default_evaluation_days BETWEEN 1 AND 90", name="evaluation_days"),
        CheckConstraint("next_idea_number >= 1", name="next_idea_number"),
    )

    slug: Mapped[str] = mapped_column(String(48), unique=True)
    key: Mapped[str] = mapped_column(String(6), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    visibility: Mapped[ProjectVisibility] = mapped_column(
        str_enum(ProjectVisibility, "visibility"),
        default=ProjectVisibility.PRIVATE,
        server_default=ProjectVisibility.PRIVATE.value,
    )
    allow_volunteer_owners: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true")
    )
    # Phase 4 (public submission form at /{slug}/submit); not exposed by the Phase 1 API.
    public_submission_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    # Label overrides only, e.g. {"shortlisted": "Short list"}; keys are IdeaStatus and
    # Resolution values. Missing keys use the default labels.
    status_labels: Mapped[dict[str, str]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    default_evaluation_days: Mapped[int] = mapped_column(
        Integer, default=7, server_default=text("7")
    )
    # Next idea number (CUST-<n>); allocate with UPDATE ... RETURNING to stay race-free.
    next_idea_number: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProjectMember(TimestampMixin, Base):
    """A user's direct role in a project.

    Extension point (Phase 2): group-based grants live in their own table
    (``project_group_grants``: project_id, group_id, role). A user's effective role
    is the highest of their direct role and their groups' roles; queries read it from
    the ``project_effective_roles`` view (below), never from this table, so Phase 2
    only redefines the view. This table stays "direct membership only".
    """

    __tablename__ = "project_members"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    role: Mapped[ProjectRole] = mapped_column(str_enum(ProjectRole, "role"))


class RubricCriterion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One rubric criterion. 3-6 active (non-archived) criteria per project.

    Criteria that already have scores are archived, not deleted, when removed from
    the rubric, so old evaluations keep their meaning.
    """

    __tablename__ = "rubric_criteria"
    __table_args__ = (
        CheckConstraint("weight > 0", name="weight_positive"),
        Index("ix_rubric_criteria_project_id_position", "project_id", "position"),
        # Active criterion names are unique per project, case-insensitively.
        Index(
            "uq_rubric_criteria_project_id_name_lower",
            "project_id",
            func.lower(text("name")),
            unique=True,
            postgresql_where=text("archived_at IS NULL"),
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(String(200), default="", server_default="")
    weight: Mapped[Decimal] = mapped_column(
        Numeric(4, 2), default=Decimal("1.00"), server_default=text("1.00")
    )
    # Inverted criteria (Effort, Risk): a high score is bad, the aggregate uses 6 - score.
    inverted: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    # Hover hints per score, e.g. {"1": "No clear benefit", "5": "Transformational"}.
    guidance: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Tag(UUIDPrimaryKeyMixin, Base):
    """A per-project tag, created on first use. Names are unique case-insensitively."""

    __tablename__ = "tags"
    __table_args__ = (
        Index("uq_tags_project_id_name_lower", "project_id", func.lower(text("name")), unique=True),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )


project_effective_roles: TableClause = table(
    "project_effective_roles",
    column("project_id", Uuid()),
    column("user_id", Uuid()),
    column("role", str_enum(ProjectRole, "role")),
)
"""Read-only view: each user's *effective* role per project, one row per pair.

Phase 1 it mirrors ``project_members``; Phase 2 redefines it (``CREATE OR REPLACE
VIEW``, same columns) as the highest of the direct and group-granted roles. Every
query that needs a project role (listing projects, member-only filters, My work,
assignment eligibility c4, last-admin c11, authz) joins this view instead of
``project_members``. A lightweight ``table()``, not a model, so it stays out of
``Base.metadata`` (Alembic must not try to create it as a table).
"""
