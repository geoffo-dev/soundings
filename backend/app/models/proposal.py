"""Proposals: one per idea, written over a fixed template, with margin comment threads.

A proposal is created by the idea's owner (or an admin) once the idea is Shortlisted
or in Proposal (c7); creating one moves a Shortlisted idea to Proposal. Its body is
one Markdown text per template section (``proposal_sections``, one row per
:class:`~app.models.enums.ProposalSectionKey`, all created with the proposal), each
with its own ``version`` for optimistic concurrency: two people editing different
sections never conflict, and a save based on an older version of the same section is
refused (409 ``proposal_conflict``). Margin comments are threads anchored to one
section (``proposal_threads``), with flat replies (``proposal_comments``); a thread
can be resolved and reopened. See docs/api/contract-phase4.md section 3.1-3.3.
Suggested text for a section (Phase 5, ``proposal_suggestions``) waits for the owner to
accept or discard it (docs/api/contract-phase5.md section 3.4).

Nothing here ever holds a score: exports add the aggregate only for people who may
see it (role matrix section E).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, utcnow
from app.models.enums import ProposalSectionKey, SuggestionSource, SuggestionStatus
from app.models.types import str_enum

__all__ = [
    "Proposal",
    "ProposalComment",
    "ProposalSection",
    "ProposalSuggestion",
    "ProposalThread",
]


class Proposal(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An idea's proposal (at most one per idea). ``updated_at`` follows section saves."""

    __tablename__ = "proposals"

    idea_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ideas.id", ondelete="CASCADE"), unique=True
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class ProposalSection(Base):
    """One template section's Markdown. ``version`` starts at 1 and goes up by one with
    every save that changes the text (``UPDATE ... WHERE version = :base_version``)."""

    __tablename__ = "proposal_sections"
    __table_args__ = (CheckConstraint("version >= 1", name="version_positive"),)

    proposal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("proposals.id", ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[ProposalSectionKey] = mapped_column(
        str_enum(ProposalSectionKey, "key"), primary_key=True
    )
    body_md: Mapped[str] = mapped_column(Text, default="", server_default="")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    # Who saved it last; null for a section nobody has written (or a deleted user).
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )


class ProposalThread(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A margin comment thread on one section. Its comments are ``proposal_comments``
    (the first one opens it). ``resolved_at`` set = resolved (collapsed in the UI)."""

    __tablename__ = "proposal_threads"
    __table_args__ = (
        Index("ix_proposal_threads_proposal_id_created_at", "proposal_id", "created_at"),
    )

    proposal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("proposals.id", ondelete="CASCADE"))
    section_key: Mapped[ProposalSectionKey] = mapped_column(
        str_enum(ProposalSectionKey, "section_key")
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class ProposalComment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One comment in a thread (flat: replies all belong to the thread). Deleting sets
    ``deleted_at`` and clears ``body_md`` (the thread shows a stub); a thread whose
    comments are all deleted is no longer listed."""

    __tablename__ = "proposal_comments"
    __table_args__ = (
        Index("ix_proposal_comments_thread_id_created_at", "thread_id", "created_at"),
    )

    thread_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("proposal_threads.id", ondelete="CASCADE")
    )
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    body_md: Mapped[str] = mapped_column(Text)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProposalSuggestion(UUIDPrimaryKeyMixin, Base):
    """Suggested text for one section (``proposal.suggest_section``): the whole new
    text of the section, which the owner or an admin accepts (a normal versioned section
    save, ``proposal.write``) or discards (contract-phase5 section 3.4).

    ``base_version`` is the section version the author read: when the section has
    changed since, the editor says so. One author has at most one pending suggestion
    per section (a newer one replaces it: the older is discarded with ``decided_by``
    the author). Suggestions hold no score data; deleting the idea deletes them.
    """

    __tablename__ = "proposal_suggestions"
    __table_args__ = (
        CheckConstraint("base_version >= 1", name="base_version_positive"),
        CheckConstraint("length(body_md) > 0", name="body_not_empty"),
        CheckConstraint(
            "(status = 'pending') = (decided_at IS NULL)", name="decided_iff_not_pending"
        ),
        Index(
            "uq_proposal_suggestions_pending_author_section",
            "proposal_id",
            "section_key",
            "author_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        # The pending list (template order is applied in Python) and the per-proposal cap.
        Index(
            "ix_proposal_suggestions_proposal_id_created_at_pending",
            "proposal_id",
            "created_at",
            postgresql_where=text("status = 'pending'"),
        ),
    )

    proposal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("proposals.id", ondelete="CASCADE"), index=True
    )
    section_key: Mapped[ProposalSectionKey] = mapped_column(
        str_enum(ProposalSectionKey, "section_key")
    )
    # The proposed text of the whole section, kept verbatim (like section saves).
    body_md: Mapped[str] = mapped_column(Text)
    base_version: Mapped[int] = mapped_column(Integer)
    # A person or a service account; null if the user no longer exists.
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    source: Mapped[SuggestionSource] = mapped_column(str_enum(SuggestionSource, "source"))
    status: Mapped[SuggestionStatus] = mapped_column(
        str_enum(SuggestionStatus, "status"),
        default=SuggestionStatus.PENDING,
        server_default=SuggestionStatus.PENDING.value,
    )
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
