"""The research step (Phase 8, product owner 2026-10-07; contract-phase8 section 3): a
project's research checklist and each idea's answers.

* ``research_checklist_items``: the project's checklist, edited by project admins like
  the rubric (``project.edit_research``): 1-10 active items in ``position`` order, each
  with a title, a one-line hint (what to write) and ``required``. Removing an item
  **archives** it when an idea has answered it (the answers are kept, hidden; restoring
  the item shows them again), else deletes it. Active titles are unique per project, any
  case. The checklist is used only while ``projects.research_step`` is on, but it is kept
  while the step is off.
* ``research_answers``: one free-text answer per idea and item (1-2,000 characters,
  stored as typed; for consultations, the department or team and what they said), who
  wrote it first and when (``answered_by_id``, ``answered_at``) and who changed it last
  (``updated_by_id``, ``updated_at``). Clearing an item deletes its answer. The idea's
  owner and project or platform admins answer (``idea.answer_research``); everyone who
  can view the idea reads them (they hold no score data).

The **gate**: while a required active item has no answer, an idea can't cross into the
statuses after Research (409 ``research_incomplete``; admins may override, audited
``idea.research_override``). The rule is ``app.schemas.research`` (``crosses_gate``,
``starts_evaluation``), applied by the services; changing the checklist never moves an
idea.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, utcnow

__all__ = ["RESEARCH_ANSWER_MAX_LENGTH", "ResearchAnswer", "ResearchChecklistItem"]

RESEARCH_ANSWER_MAX_LENGTH = 2_000
"""Characters in one answer (``length()``, as the API counts them)."""


class ResearchChecklistItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One item of a project's research checklist."""

    __tablename__ = "research_checklist_items"
    __table_args__ = (
        CheckConstraint("length(title) > 0", name="title_not_empty"),
        CheckConstraint("position >= 0", name="position_non_negative"),
        Index("ix_research_checklist_items_project_id_position", "project_id", "position"),
        # Active item titles are unique per project, case-insensitively.
        Index(
            "uq_research_checklist_items_project_id_title_lower",
            "project_id",
            func.lower(text("title")),
            unique=True,
            postgresql_where=text("archived_at IS NULL"),
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    # 0-based order among the active items; an archived item keeps its last one.
    position: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(80))
    # One line under the title: what to write.
    hint: Mapped[str] = mapped_column(String(200), default="", server_default="")
    # Required items gate the statuses after Research; optional ones only guide.
    required: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ResearchAnswer(Base):
    """An idea's answer to one checklist item (no row = unanswered)."""

    __tablename__ = "research_answers"
    __table_args__ = (
        CheckConstraint(
            f"length(answer) BETWEEN 1 AND {RESEARCH_ANSWER_MAX_LENGTH}", name="answer_length"
        ),
    )

    idea_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ideas.id", ondelete="CASCADE"), primary_key=True
    )
    # NO ACTION: an answered item is archived, never deleted (its project still can be:
    # the cascade from projects removes the answers' ideas in the same statement).
    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("research_checklist_items.id"), primary_key=True, index=True
    )
    # Plain text as typed (no Markdown; line breaks kept). Never score data.
    answer: Mapped[str] = mapped_column(Text)
    # Who answered first, and when; null if the user no longer exists.
    answered_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    answered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    # Who changed it last, and when (the first answer sets both to the answer's).
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
