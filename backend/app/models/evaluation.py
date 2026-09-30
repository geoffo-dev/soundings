"""Evaluations and their per-criterion scores."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import EvaluationStatus, Recommendation
from app.models.types import str_enum


class Evaluation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One evaluator's evaluation of one idea (created when they first save).

    References the assignment ``(idea_id, evaluator_id)``, so an evaluation cannot
    exist without an assignment and disappears with it.
    """

    __tablename__ = "evaluations"
    __table_args__ = (
        UniqueConstraint("idea_id", "evaluator_id"),
        ForeignKeyConstraint(
            ["idea_id", "evaluator_id"],
            ["idea_evaluators.idea_id", "idea_evaluators.user_id"],
            name="fk_evaluations_idea_id_evaluator_id_idea_evaluators",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "status <> 'submitted' OR (recommendation IS NOT NULL AND submitted_at IS NOT NULL)",
            name="submitted_complete",
        ),
    )

    idea_id: Mapped[uuid.UUID] = mapped_column()
    evaluator_id: Mapped[uuid.UUID] = mapped_column(index=True)
    status: Mapped[EvaluationStatus] = mapped_column(
        str_enum(EvaluationStatus, "status"),
        default=EvaluationStatus.DRAFT,
        server_default=EvaluationStatus.DRAFT.value,
    )
    recommendation: Mapped[Recommendation | None] = mapped_column(
        str_enum(Recommendation, "recommendation")
    )
    comment: Mapped[str] = mapped_column(Text, default="", server_default="")
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Last time the evaluator saved again after the first submission (null if never):
    # shown as "edited after submission". Kept apart from updated_at, which also
    # changes for bookkeeping such as include_in_aggregate.
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Phase 6: AI evaluations (evaluator is a service account, users.is_service_account)
    # are excluded from the aggregate by default; the owner can include them.
    include_in_aggregate: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true")
    )


class EvaluationScore(Base):
    """A 1-5 score for one criterion. ``score`` may be null only in a draft."""

    __tablename__ = "evaluation_scores"
    __table_args__ = (CheckConstraint("score BETWEEN 1 AND 5", name="score_range"),)

    evaluation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evaluations.id", ondelete="CASCADE"), primary_key=True
    )
    # NO ACTION, checked at commit (DEFERRABLE INITIALLY DEFERRED): deleting a scored
    # criterion fails (archive it instead), while deleting a project, which cascades
    # to both the criteria and the scores, succeeds. The error surfaces at commit.
    criterion_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("rubric_criteria.id", deferrable=True, initially="DEFERRED"),
        primary_key=True,
        index=True,
    )
    score: Mapped[int | None] = mapped_column(SmallInteger)
    comment: Mapped[str] = mapped_column(String(1000), default="", server_default="")
