"""Bid evaluation (Phase 10, product owner 2026-10-13; contract-phase10, ADR 0018): an
idea's call for bids, its evaluation template, the bids the team enters with their
documents and must-have results, the section assessors and their assessments, and the AI
assessor's assessments with quoted evidence.

* ``bid_templates``: a project's **default** bid evaluation template as one JSON document
  (``app.schemas.bids.BidTemplateIn``: scale anchors, 1-8 weighted sections of 1-15
  questions, 0-20 must-haves). Nothing refers to it: a call **copies** it when it is
  created, so editing it never touches an existing call. Every project has a row
  (migration 0016 writes the default for existing projects); a project without one (made
  by an older release during a rollback) reads as the built-in default.
* ``bid_calls``: one call per idea (``idea_id`` unique), started from an idea in Proposal
  with a proposal. ``draft -> open -> assessing -> awarded | cancelled`` (back from
  assessing to open only while no assessment is submitted). Its copy of the template is
  ``bid_call_sections`` / ``bid_call_questions`` / ``bid_call_must_haves`` (rows with ids:
  assessments, assessors, must-have results and document links refer to them), editable
  until the first assessment (human or AI) is submitted.
* ``bids``: entered by a call manager while the call is open (P1: no bidder accounts);
  ``status`` is kept by the service: ``received`` until every must-have is met
  (``qualified``), ``rejected`` (one click and a reason; reinstating undoes it until the
  award), ``awarded`` / ``unsuccessful`` at the award. ``bid_must_have_results`` holds one
  row per bid and must-have (``missing`` for a required document without a file,
  ``unchecked`` for a confirmation nobody decided, ``met`` / ``not_met``).
* ``bid_documents`` (metadata), ``bid_document_contents`` (the bytes, ``bytea``) and
  ``bid_document_texts`` (the text the worker extracted in a child process): stored in
  PostgreSQL (ADR 0018), allowed by their bytes (``BidDocumentType``), at most 25 MiB each,
  30 per bid and 500 MiB per call, the same file once per bid (``sha256``). Extracted text
  is **untrusted** (prompt injection) wherever it flows.
* ``bid_section_assessors``: who assesses which section of the call (P3), and
  ``bid_assessments`` / ``bid_assessment_answers``: one assessment per bid, section and
  assessor (a draft, then submitted; it references the assignment, so removing an assessor
  from a section deletes their assessments of it, as removing an evaluator does).
* ``bid_ai_assessments`` / ``bid_ai_scores`` / ``bid_ai_findings``: the AI assessor's
  assessment of a bid (one per bid and agent; a re-submission replaces it), a score with a
  rationale and quoted evidence (``[{document_id, quote, found}]``, the server checking each
  quote against the document's text) for every score question, and a finding for every
  must-have, which is only a suggestion. ``included`` (false by default, and again after a
  re-submission that changes a score) puts its scores in the totals for that bid.

Blind assessment (role matrix section 3a): nothing here is filtered; the services apply
the policy. Score data never leaves through notifications, emails, the feed or My work,
and prices only reach call managers and the assessors of the section holding the price
question.
"""

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
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, utcnow
from app.models.enums import (
    AiMustHaveFinding,
    BidCallStatus,
    BidDocumentType,
    BidQuestionType,
    BidStatus,
    EvaluationStatus,
    ExtractionError,
    ExtractionState,
    MustHaveKind,
    MustHaveResult,
)
from app.models.types import str_enum

__all__ = [
    "BID_CALL_DESCRIPTION_MAX_LENGTH",
    "BID_COMMENT_MAX_LENGTH",
    "BID_DOCUMENT_MAX_BYTES",
    "BID_EVIDENCE_MAX",
    "BID_NOTES_MAX_LENGTH",
    "BID_RATIONALE_MAX_LENGTH",
    "BID_REASON_MAX_LENGTH",
    "BID_SCALE_POINTS",
    "BID_SCORE_MAX",
    "BID_TEXT_MAX_CHARS",
    "Bid",
    "BidAiAssessment",
    "BidAiFinding",
    "BidAiScore",
    "BidAssessment",
    "BidAssessmentAnswer",
    "BidCall",
    "BidCallMustHave",
    "BidCallQuestion",
    "BidCallSection",
    "BidDocument",
    "BidDocumentContent",
    "BidDocumentText",
    "BidMustHaveResult",
    "BidSectionAssessor",
    "BidTemplate",
]

BID_SCORE_MAX = 5
"""Scores are whole numbers 0-5 (0 = no response or unacceptable)."""
BID_SCALE_POINTS = BID_SCORE_MAX + 1
"""A template's scale has one anchor label per score, 0 to 5."""
BID_DOCUMENT_MAX_BYTES = 25 * 1024 * 1024
"""25 MiB per uploaded document (the upload route's own body limit)."""
BID_TEXT_MAX_CHARS = 2_000_000
"""Extracted text kept per document (characters); longer text is cut (``text_truncated``)."""
BID_EVIDENCE_MAX = 3
"""Quotes the AI assessor may give per score or finding."""
BID_CALL_DESCRIPTION_MAX_LENGTH = 2_000
BID_NOTES_MAX_LENGTH = 2_000
BID_REASON_MAX_LENGTH = 500
"""Rejection, award and cancellation reasons."""
BID_COMMENT_MAX_LENGTH = 2_000
BID_RATIONALE_MAX_LENGTH = 1_000

_SHA256 = "^[0-9a-f]{64}$"


def _evidence_array(column: str) -> CheckConstraint:
    return CheckConstraint(
        f"CASE WHEN jsonb_typeof({column}) = 'array'"
        f" THEN jsonb_array_length({column}) <= {BID_EVIDENCE_MAX} ELSE false END",
        name=f"{column}_array",
    )


class BidTemplate(Base):
    """A project's default bid evaluation template (the JSON of ``BidTemplateIn``)."""

    __tablename__ = "bid_templates"
    __table_args__ = (CheckConstraint("jsonb_typeof(template) = 'object'", name="template_object"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    # Validated by app.schemas.bids.BidTemplateIn when written; copied into a call's own
    # rows when a call is created. Holds no ids: nothing refers to it.
    template: Mapped[dict[str, Any]] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), onupdate=utcnow
    )
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class BidCall(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An idea's call for bids (at most one per idea in Phase 10)."""

    __tablename__ = "bid_calls"
    __table_args__ = (
        UniqueConstraint("idea_id"),
        CheckConstraint("length(title) > 0", name="title_not_empty"),
        CheckConstraint(
            f"length(description) <= {BID_CALL_DESCRIPTION_MAX_LENGTH}", name="description_length"
        ),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_format"),
        CheckConstraint(
            f"cardinality(scale) = {BID_SCALE_POINTS} AND array_position(scale, NULL) IS NULL",
            name="scale_points",
        ),
        # Opening needs a deadline, and an open call keeps one.
        CheckConstraint("status = 'draft' OR deadline_at IS NOT NULL", name="deadline_when_open"),
        CheckConstraint("(status = 'awarded') = (awarded_at IS NOT NULL)", name="awarded_iff_at"),
        CheckConstraint(
            "(status = 'cancelled') = (cancelled_at IS NOT NULL)", name="cancelled_iff_at"
        ),
        CheckConstraint("award_reason IS NULL OR status = 'awarded'", name="award_reason_awarded"),
        CheckConstraint(
            "cancel_reason IS NULL OR status = 'cancelled'", name="cancel_reason_cancelled"
        ),
        CheckConstraint(
            f"length(award_reason) <= {BID_REASON_MAX_LENGTH}"
            f" AND length(cancel_reason) <= {BID_REASON_MAX_LENGTH}",
            name="reason_length",
        ),
        # The hourly assessment reminder scan: calls being assessed with a due date.
        Index(
            "ix_bid_calls_assessment_due_at_assessing",
            "assessment_due_at",
            postgresql_where=text("status = 'assessing' AND assessment_due_at IS NOT NULL"),
        ),
    )

    idea_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ideas.id", ondelete="CASCADE"))
    # One line (SingleLine): it reaches email subjects.
    title: Mapped[str] = mapped_column(String(120))
    # Plain text: what is being bought, for the team and the assessors.
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    status: Mapped[BidCallStatus] = mapped_column(
        str_enum(BidCallStatus, "status"),
        default=BidCallStatus.DRAFT,
        server_default=BidCallStatus.DRAFT.value,
    )
    # ISO 4217 code shown with every price (lead default: GBP).
    currency: Mapped[str] = mapped_column(String(3), default="GBP", server_default="GBP")
    # The template's scale anchors, one label per score 0-5 (copied with the template).
    scale: Mapped[list[str]] = mapped_column(ARRAY(String(80)))
    # Bids received after it are marked late (not refused). Instance time zone in the SPA.
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # When the section assessors should have submitted (reminders 2 days before and on it).
    assessment_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    # The award: the awarded bid is the call's bid with status 'awarded' (one at most).
    awarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    awarded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    award_reason: Mapped[str | None] = mapped_column(Text)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(Text)


class BidCallSection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A section of a call's evaluation template (1-8, weights summing to 100)."""

    __tablename__ = "bid_call_sections"
    __table_args__ = (
        CheckConstraint("length(title) > 0", name="title_not_empty"),
        CheckConstraint("position >= 0", name="position_non_negative"),
        CheckConstraint("weight BETWEEN 1 AND 100", name="weight_range"),
        Index("ix_bid_call_sections_call_id_position", "call_id", "position"),
        Index(
            "uq_bid_call_sections_call_id_title_lower",
            "call_id",
            func.lower(text("title")),
            unique=True,
        ),
    )

    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bid_calls.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(60))
    guidance: Mapped[str] = mapped_column(String(500), default="", server_default="")
    # Percent of the bid's total (the call's sections sum to 100).
    weight: Mapped[int] = mapped_column(SmallInteger)


class BidCallQuestion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A question of a call's section (1-15 per section; at most one price question per
    call; comment questions weigh 0)."""

    __tablename__ = "bid_call_questions"
    __table_args__ = (
        CheckConstraint("length(text) > 0", name="text_not_empty"),
        CheckConstraint("position >= 0", name="position_non_negative"),
        CheckConstraint("weight BETWEEN 0 AND 100", name="weight_range"),
        CheckConstraint("(type = 'comment') = (weight = 0)", name="comment_iff_unweighted"),
        Index("ix_bid_call_questions_section_id_position", "section_id", "position"),
        Index("ix_bid_call_questions_call_id", "call_id"),
        Index(
            "uq_bid_call_questions_call_id_price",
            "call_id",
            unique=True,
            postgresql_where=text("type = 'price'"),
        ),
    )

    # The question's call (its section's), for the one-price-question index.
    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bid_calls.id", ondelete="CASCADE"))
    section_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bid_call_sections.id", ondelete="CASCADE")
    )
    position: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(String(300))
    guidance: Mapped[str] = mapped_column(String(1000), default="", server_default="")
    type: Mapped[BidQuestionType] = mapped_column(str_enum(BidQuestionType, "type"))
    # Relative to the section's other scored questions (score and price: 1-100).
    weight: Mapped[int] = mapped_column(SmallInteger)


class BidCallMustHave(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A must-have of a call (0-20): a required document or a confirmation."""

    __tablename__ = "bid_call_must_haves"
    __table_args__ = (
        CheckConstraint("length(text) > 0", name="text_not_empty"),
        CheckConstraint("position >= 0", name="position_non_negative"),
        Index("ix_bid_call_must_haves_call_id_position", "call_id", "position"),
        Index(
            "uq_bid_call_must_haves_call_id_text_lower",
            "call_id",
            func.lower(text("text")),
            unique=True,
        ),
    )

    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bid_calls.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(String(200))
    kind: Mapped[MustHaveKind] = mapped_column(str_enum(MustHaveKind, "kind"))


class BidSectionAssessor(Base):
    """A person who assesses one section of a call, for every bid (P3)."""

    __tablename__ = "bid_section_assessors"
    __table_args__ = (
        # My work's "Bids to assess", WorkCounts and the reminder scan: a person's calls.
        Index("ix_bid_section_assessors_user_id_call_id", "user_id", "call_id"),
        Index("ix_bid_section_assessors_call_id", "call_id"),
    )

    section_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bid_call_sections.id", ondelete="CASCADE"), primary_key=True
    )
    # Users are deactivated, never deleted (the cascade only keeps tests' cleanup simple).
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # The section's call (denormalised for the indexes above).
    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bid_calls.id", ondelete="CASCADE"))
    assigned_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )


class Bid(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A bid the team entered (bidders have no accounts in Phase 10)."""

    __tablename__ = "bids"
    __table_args__ = (
        CheckConstraint("length(bidder) > 0", name="bidder_not_empty"),
        CheckConstraint("price > 0", name="price_positive"),
        CheckConstraint(f"length(notes) <= {BID_NOTES_MAX_LENGTH}", name="notes_length"),
        CheckConstraint(
            "(status = 'rejected') = (rejected_at IS NOT NULL)", name="rejected_iff_at"
        ),
        CheckConstraint(
            "(rejected_at IS NULL) = (rejection_reason IS NULL)", name="rejection_reason_iff_at"
        ),
        CheckConstraint(
            f"length(rejection_reason) BETWEEN 1 AND {BID_REASON_MAX_LENGTH}",
            name="rejection_reason_length",
        ),
        # The call's bids by status (lists, the ranking, the price pool, counts).
        Index("ix_bids_call_id_status", "call_id", "status"),
        # One awarded bid per call.
        Index(
            "uq_bids_call_id_awarded",
            "call_id",
            unique=True,
            postgresql_where=text("status = 'awarded'"),
        ),
    )

    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bid_calls.id", ondelete="CASCADE"))
    # The bidder organisation (SingleLine). Visible to call managers and assessors.
    bidder: Mapped[str] = mapped_column(String(120))
    # Contact details as given; call managers only; never emailed by Soundings.
    contact_name: Mapped[str] = mapped_column(String(120), default="", server_default="")
    contact_email: Mapped[str | None] = mapped_column(String(320))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    # Entered by the team when the call has a price question (in the call's currency).
    price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    # Plain text, call managers only.
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    status: Mapped[BidStatus] = mapped_column(
        str_enum(BidStatus, "status"),
        default=BidStatus.RECEIVED,
        server_default=BidStatus.RECEIVED.value,
    )
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    entered_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class BidMustHaveResult(Base):
    """A bid's result for one must-have of its call (a row for every pair, written when the
    bid or the must-have is created)."""

    __tablename__ = "bid_must_have_results"
    __table_args__ = (
        # A person's decision is met or not met; "missing" and "unchecked" are nobody's.
        CheckConstraint(
            "decided_at IS NULL OR result IN ('met', 'not_met')", name="decision_is_met_or_not"
        ),
        CheckConstraint(
            "decided_by_id IS NULL OR decided_at IS NOT NULL", name="decided_by_needs_at"
        ),
        CheckConstraint(f"length(note) <= {BID_REASON_MAX_LENGTH}", name="note_length"),
    )

    bid_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bids.id", ondelete="CASCADE"), primary_key=True
    )
    must_have_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bid_call_must_haves.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    result: Mapped[MustHaveResult] = mapped_column(str_enum(MustHaveResult, "result"))
    # Who decided met / not met, when (null: automatic, e.g. a document linked).
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str] = mapped_column(String(500), default="", server_default="")


class BidDocument(UUIDPrimaryKeyMixin, Base):
    """An uploaded document of a bid: its metadata and extraction state (the bytes and the
    text are in their own tables, read only when needed)."""

    __tablename__ = "bid_documents"
    __table_args__ = (
        UniqueConstraint("bid_id", "sha256"),
        CheckConstraint("length(filename) > 0", name="filename_not_empty"),
        CheckConstraint(
            f"size_bytes BETWEEN 1 AND {BID_DOCUMENT_MAX_BYTES}", name="size_bytes_range"
        ),
        CheckConstraint(f"sha256 ~ '{_SHA256}'", name="sha256_format"),
        CheckConstraint(
            "(extraction_state = 'failed') = (extraction_error IS NOT NULL)",
            name="error_iff_failed",
        ),
        CheckConstraint(
            "(extraction_state = 'pending') = (extracted_at IS NULL)", name="extracted_iff_done"
        ),
        CheckConstraint(
            "(extraction_state = 'done') = (text_chars IS NOT NULL)", name="text_iff_done"
        ),
        CheckConstraint(f"text_chars BETWEEN 0 AND {BID_TEXT_MAX_CHARS}", name="text_chars_range"),
        # A call's documents and their total size (the 500 MiB cap).
        Index("ix_bid_documents_call_id", "call_id"),
        # The worker's sweep of documents still waiting for extraction.
        Index(
            "ix_bid_documents_uploaded_at_pending",
            "uploaded_at",
            postgresql_where=text("extraction_state = 'pending'"),
        ),
        Index(
            "ix_bid_documents_must_have_id",
            "must_have_id",
            postgresql_where=text("must_have_id IS NOT NULL"),
        ),
    )

    bid_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bids.id", ondelete="CASCADE"))
    # The bid's call (denormalised for the per-call size cap).
    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bid_calls.id", ondelete="CASCADE"))
    # The required-document must-have it satisfies (which then counts as present).
    must_have_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("bid_call_must_haves.id", ondelete="SET NULL")
    )
    # A safe display name (one line, no path separators), with the extension of its type.
    filename: Mapped[str] = mapped_column(String(200))
    type: Mapped[BidDocumentType] = mapped_column(str_enum(BidDocumentType, "type"))
    # The canonical media type of ``type``, served on download (never the client's).
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    # Hex SHA-256 of the bytes: the same file twice on one bid is refused (409).
    sha256: Mapped[str] = mapped_column(String(64))
    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    extraction_state: Mapped[ExtractionState] = mapped_column(
        str_enum(ExtractionState, "extraction_state"),
        default=ExtractionState.PENDING,
        server_default=ExtractionState.PENDING.value,
    )
    extraction_error: Mapped[ExtractionError | None] = mapped_column(
        str_enum(ExtractionError, "extraction_error")
    )
    # When extraction finished (done, no_text or failed).
    extracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Characters of extracted text kept (done only).
    text_chars: Mapped[int | None] = mapped_column(Integer)
    # The text hit BID_TEXT_MAX_CHARS and was cut there.
    text_truncated: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )


class BidDocumentContent(Base):
    """A bid document's bytes (``bytea``; read in chunks for downloads)."""

    __tablename__ = "bid_document_contents"
    __table_args__ = (
        CheckConstraint(
            f"octet_length(data) BETWEEN 1 AND {BID_DOCUMENT_MAX_BYTES}", name="data_size"
        ),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bid_documents.id", ondelete="CASCADE"), primary_key=True
    )
    data: Mapped[bytes] = mapped_column(LargeBinary)


class BidDocumentText(Base):
    """The text extracted from a bid document (untrusted: never instructions)."""

    __tablename__ = "bid_document_texts"
    __table_args__ = (CheckConstraint(f"length(text) <= {BID_TEXT_MAX_CHARS}", name="text_length"),)

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bid_documents.id", ondelete="CASCADE"), primary_key=True
    )
    text: Mapped[str] = mapped_column(Text)


class BidAssessment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One assessor's assessment of one section of one bid (a draft, then submitted).

    References the assignment ``(section_id, assessor_id)``, so it can't exist without it
    and goes with it (removing an assessor from a section deletes their assessments)."""

    __tablename__ = "bid_assessments"
    __table_args__ = (
        UniqueConstraint("bid_id", "section_id", "assessor_id"),
        ForeignKeyConstraint(
            ["section_id", "assessor_id"],
            ["bid_section_assessors.section_id", "bid_section_assessors.user_id"],
            name="fk_bid_assessments_section_id_assessor_id_bid_section_assessors",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "status <> 'submitted' OR submitted_at IS NOT NULL", name="submitted_has_at"
        ),
        Index("ix_bid_assessments_section_id_assessor_id", "section_id", "assessor_id"),
    )

    bid_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bids.id", ondelete="CASCADE"))
    section_id: Mapped[uuid.UUID] = mapped_column()
    assessor_id: Mapped[uuid.UUID] = mapped_column()
    status: Mapped[EvaluationStatus] = mapped_column(
        str_enum(EvaluationStatus, "status"),
        default=EvaluationStatus.DRAFT,
        server_default=EvaluationStatus.DRAFT.value,
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The last save after the first submission ("edited after submission"), if any.
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BidAssessmentAnswer(Base):
    """An assessor's answer to one question: a 0-5 score (score questions; null only in a
    draft) and a comment (the answer itself for comment questions, a note otherwise)."""

    __tablename__ = "bid_assessment_answers"
    __table_args__ = (
        CheckConstraint(f"score BETWEEN 0 AND {BID_SCORE_MAX}", name="score_range"),
        CheckConstraint(f"length(comment) <= {BID_COMMENT_MAX_LENGTH}", name="comment_length"),
    )

    assessment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bid_assessments.id", ondelete="CASCADE"), primary_key=True
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bid_call_questions.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    score: Mapped[int | None] = mapped_column(SmallInteger)
    comment: Mapped[str] = mapped_column(Text, default="", server_default="")


class BidAiAssessment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The AI assessor's assessment of one bid (one per bid and agent; a new submission
    replaces its scores and findings). The run that recorded it points here
    (``ai_runs.bid_ai_assessment_id``)."""

    __tablename__ = "bid_ai_assessments"
    __table_args__ = (UniqueConstraint("bid_id", "agent_id"),)

    bid_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bids.id", ondelete="CASCADE"))
    # NO ACTION: agents are disabled, never deleted.
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ai_agents.id"), index=True)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    # In the bid's totals? False until a call manager includes it; a re-submission that
    # changes a score sets it false again (as Phase 6's AI evaluations).
    included: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))


class BidAiScore(Base):
    """The AI's score for one score question, its rationale and quoted evidence
    (``[{document_id, quote, found}]``: ``found`` is the server's check of the quote
    against the document's extracted text, whitespace-normalised)."""

    __tablename__ = "bid_ai_scores"
    __table_args__ = (
        CheckConstraint(f"score BETWEEN 0 AND {BID_SCORE_MAX}", name="score_range"),
        CheckConstraint(
            f"length(rationale) BETWEEN 1 AND {BID_RATIONALE_MAX_LENGTH}", name="rationale_length"
        ),
        _evidence_array("evidence"),
    )

    ai_assessment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bid_ai_assessments.id", ondelete="CASCADE"), primary_key=True
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bid_call_questions.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    score: Mapped[int] = mapped_column(SmallInteger)
    # Agent text: untrusted, bidi and zero-width characters stripped before storing.
    rationale: Mapped[str] = mapped_column(String(1000))
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )


class BidAiFinding(Base):
    """The AI's pre-check of one must-have: a suggestion shown next to the result, which it
    never changes."""

    __tablename__ = "bid_ai_findings"
    __table_args__ = (
        CheckConstraint(
            f"length(rationale) BETWEEN 1 AND {BID_RATIONALE_MAX_LENGTH}", name="rationale_length"
        ),
        _evidence_array("evidence"),
    )

    ai_assessment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bid_ai_assessments.id", ondelete="CASCADE"), primary_key=True
    )
    must_have_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bid_call_must_haves.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    finding: Mapped[AiMustHaveFinding] = mapped_column(str_enum(AiMustHaveFinding, "finding"))
    rationale: Mapped[str] = mapped_column(String(1000))
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
