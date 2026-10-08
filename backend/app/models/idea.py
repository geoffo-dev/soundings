"""Ideas and their per-idea relations: tags, evaluators, votes and watchers."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, utcnow
from app.models.enums import HoldReason, IdeaStatus, Resolution
from app.models.types import str_enum


class Idea(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An idea. Its key is ``<project.key>-<number>``, e.g. ``CUST-12``.

    ``aggregate_score``, ``aggregate_count`` and ``high_disagreement`` cache the
    aggregate over submitted evaluations (see docs/api/contract-phase1.md) so lists
    can sort and filter by them. The backend recomputes them in the same transaction
    whenever an evaluation, an evaluator or the rubric changes. They are *raw*
    values: blind-visibility filtering happens when responses are built.

    Public submissions (Phase 4) keep ``submitted_by_id`` null; the submitter's
    contact details and tracking link live in ``public_submissions``. ``held_for`` is
    set while a public submission waits for its submitter's email confirmation or for
    moderation: held ideas are in no list, board, search, count, My work or
    notification, and only project and platform admins can open one held for
    moderation (c12; contract-phase4 section 3.6).

    Phase 8b (product owner, 2026-10-08; contract-phase8b): ``researcher_id`` is the
    person asked to do the idea's research (null = nobody: the idea's owner does it, as
    in Phase 8), ``research_assigned_at`` when they were asked (the reminders' "already
    told" check; set whenever ``researcher_id`` is, ``ck_ideas_researcher_assigned_at``;
    meaningless while ``researcher_id`` is null, cleared with it) and
    ``research_due_at`` the optional research due date (kept when the researcher
    changes or hands it back: it then applies to the owner). The researcher is any
    active person, a member of the project or not; deactivation, closing the idea and
    turning the project's research step off clear the assignment (review S8).
    A researcher without a role in a private project sees this one idea as its guest
    (role matrix column R).
    """

    __tablename__ = "ideas"
    __table_args__ = (
        UniqueConstraint("project_id", "number"),
        CheckConstraint("number >= 1", name="number_positive"),
        CheckConstraint(
            "(status = 'closed') = (resolution IS NOT NULL)", name="resolution_iff_closed"
        ),
        CheckConstraint("vote_count >= 0", name="vote_count_non_negative"),
        CheckConstraint(
            "aggregate_score IS NULL OR aggregate_score BETWEEN 1 AND 5", name="aggregate_range"
        ),
        # Phase 8b: a researcher always has the time they were asked (the reminders'
        # "already told" check). One way only: ON DELETE SET NULL clears researcher_id
        # alone (users are deactivated, never deleted, in the app).
        CheckConstraint(
            "researcher_id IS NULL OR research_assigned_at IS NOT NULL",
            name="researcher_assigned_at",
        ),
        # Keyset pages in the default order (-updated), overall and per board column /
        # status filter; the status index also serves the board's per-status counts.
        Index("ix_ideas_project_id_last_activity_at", "project_id", "last_activity_at", "id"),
        Index(
            "ix_ideas_project_id_status_last_activity_at",
            "project_id",
            "status",
            "last_activity_at",
            "id",
        ),
        Index("ix_ideas_project_id_aggregate_score", "project_id", "aggregate_score"),
        # My work's owned groups and /me/owned-ideas: an owner's ideas per status in the
        # default order (-updated), a range scan that stops after a page (migration 0014;
        # it replaced the plain owner_id index, which its first column also serves).
        Index(
            "ix_ideas_owner_id_status_last_activity_at",
            "owner_id",
            "status",
            "last_activity_at",
            "id",
        ),
        # Phase 3 reminder scan: open evaluations with a due date.
        Index(
            "ix_ideas_evaluation_due_at_open",
            "evaluation_due_at",
            postgresql_where=text(
                "evaluation_due_at IS NOT NULL AND evaluation_closed_at IS NULL"
                " AND status <> 'closed'"
            ),
        ),
        # Phase 8b: a researcher's ideas by status (My work's "Research to do", the
        # sidebar count, guest access in lists, deactivation clearing the assignments).
        Index(
            "ix_ideas_researcher_id_status",
            "researcher_id",
            "status",
            postgresql_where=text("researcher_id IS NOT NULL"),
        ),
        # Phase 8b: the research reminder scan (open ideas with a research due date).
        Index(
            "ix_ideas_research_due_at_open",
            "research_due_at",
            postgresql_where=text("research_due_at IS NOT NULL AND status <> 'closed'"),
        ),
        # Phase 4: the moderation queue (oldest first) and the cleanup of submissions
        # nobody confirmed (contract-phase4 section 3.6).
        Index(
            "ix_ideas_project_id_created_at_moderation",
            "project_id",
            "created_at",
            "id",
            postgresql_where=text("held_for = 'moderation'"),
        ),
        Index(
            "ix_ideas_created_at_email_verification",
            "created_at",
            postgresql_where=text("held_for = 'email_verification'"),
        ),
        # "Search ideas": ILIKE '%q%' on title/summary served by trigram indexes.
        Index(
            "ix_ideas_title_trgm",
            "title",
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
        ),
        Index(
            "ix_ideas_summary_trgm",
            "summary",
            postgresql_using="gin",
            postgresql_ops={"summary": "gin_trgm_ops"},
        ),
        # "Similar ideas": the nearest titles and summaries by trigram distance (<->).
        Index(
            "ix_ideas_title_trgm_gist",
            "title",
            postgresql_using="gist",
            postgresql_ops={"title": "gist_trgm_ops"},
        ),
        Index(
            "ix_ideas_summary_trgm_gist",
            "summary",
            postgresql_using="gist",
            postgresql_ops={"summary": "gist_trgm_ops"},
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(String(500), default="", server_default="")
    description_md: Mapped[str] = mapped_column(Text, default="", server_default="")
    status: Mapped[IdeaStatus] = mapped_column(
        str_enum(IdeaStatus, "status"),
        default=IdeaStatus.NEW,
        server_default=IdeaStatus.NEW.value,
    )
    resolution: Mapped[Resolution | None] = mapped_column(str_enum(Resolution, "resolution"))
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    submitted_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    evaluation_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    evaluation_closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), index=True
    )
    vote_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    aggregate_score: Mapped[Decimal | None] = mapped_column(Numeric(2, 1))
    aggregate_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    high_disagreement: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    # Phase 4: a public submission not visible yet (null = visible; HoldReason).
    held_for: Mapped[HoldReason | None] = mapped_column(str_enum(HoldReason, "held_for"))
    # Phase 8b: who does the research (null = the owner), since when, and by when.
    researcher_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    research_assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    research_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IdeaTag(Base):
    __tablename__ = "idea_tags"

    idea_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ideas.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class IdeaEvaluator(Base):
    """An evaluator assignment. The evaluation itself (if any) is in ``evaluations``.

    AI evaluators (Phase 6) are service-account users, so no extra column is needed:
    ``is_ai`` in the API is ``users.is_service_account``.
    """

    __tablename__ = "idea_evaluators"

    idea_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ideas.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    invited_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    invited_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )


class IdeaVote(Base):
    """One upvote per user per idea; ``ideas.vote_count`` caches the count."""

    __tablename__ = "idea_votes"

    idea_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ideas.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )


class IdeaWatcher(Base):
    """Users notified about an idea (Phase 3). Submitter, owner, evaluators and
    commenters are added automatically; anyone who can view may watch/unwatch."""

    __tablename__ = "idea_watchers"

    idea_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ideas.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
