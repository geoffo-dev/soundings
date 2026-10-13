"""Bid evaluation (Phase 10, product owner 2026-10-13; contract-phase10, ADR 0018).

An idea in Proposal gets **one call for bids**. The team enters each bid and uploads its
documents (P1: no bidder accounts); a bid evaluation **template** (copied from the
project's default) splits the evaluation into weighted **sections** of **questions**
(score 0-5, one automatic price question, comments) and lists **must-haves** (required
documents, confirmations). A missing must-have is flagged (a required document without a
file at once; confirmations are pre-checked by the AI and confirmed by a person) and a
person rejects the bid in one click with a reason (P2). **Section assessors** score their
sections for every bid (P3), blind like idea evaluations; an **AI assessor** scores every
score question with quoted evidence and checks the must-haves (P4), left out of the totals
until a call manager includes it.

Who may do what (role matrix table M; the one policy module decides):

* **call managers** (the idea's owner, project admins, platform admins): everything
  about the call (``bid.manage``; documents ``bid.upload_document``, the decisions
  ``bid.decide`` and deleting the call ``bid.delete_call`` session only), its bids and
  prices, every score (``bid.view_scores``), the report;
* **section assessors**: the call, every bid that isn't rejected, its documents and
  must-have results (``bid.view_bids``), scoring their own sections (``bid.assess``),
  other people's scores of a section **only after submitting it for that bid**
  (``bid.view_section_scores``), prices and **pricing documents** only when their section
  holds the price question (``bid.view_price``);
* **everyone else who can view the idea**: that a call exists (``bid.view_call``: title,
  status, deadline, number of bids) and nothing more; a guest researcher (column R) not
  even that; an AI agent only the bid of its open assess run, through MCP (c22).

Scoring is pure arithmetic over the submitted assessments (:func:`question_mean`,
:func:`section_score`, :func:`bid_total`, :func:`price_score`, :func:`rank_bids`), so the
API, the report and the tests compute exactly the same numbers (worked example:
contract-phase10 section 8.1, ``tests/test_schemas_phase10.py``). Scored bids are those
:func:`is_scored` accepts (not rejected, every must-have met), before and after the award.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from typing import Annotated, Final, Literal
from uuid import UUID

from pydantic import AfterValidator, AwareDatetime, Field, field_validator, model_validator

from app.models.bid import (
    BID_CALL_DESCRIPTION_MAX_LENGTH,
    BID_COMMENT_MAX_LENGTH,
    BID_NOTES_MAX_LENGTH,
    BID_REASON_MAX_LENGTH,
    BID_SCALE_POINTS,
    BID_SCORE_MAX,
)
from app.models.enums import (
    AiMustHaveFinding,
    BidCallStatus,
    BidDocumentType,
    BidQuestionType,
    BidStatus,
    EvaluatorState,
    ExtractionError,
    ExtractionState,
    MustHaveKind,
    MustHaveResult,
)
from app.schemas.ai import AiAgentRef, AiBlockedReason, AiRun
from app.schemas.base import (
    DueAt,
    RequestModel,
    ResponseModel,
    SingleLine,
    VisibleLine,
    VisibleText,
)
from app.schemas.bid_refs import BidCallRef, BidCallSummary, BidProgress, BidRef, BidSectionRef
from app.schemas.users import UserRef

__all__ = [
    "ASSESSORS_PER_SECTION_MAX",
    "BIDS_PER_CALL_MAX",
    "BID_ARCHIVE_MAX_ENTRIES",
    "BID_ARCHIVE_MAX_RATIO",
    "BID_ARCHIVE_PART_MAX_BYTES",
    "BID_ARCHIVE_TOTAL_MAX_BYTES",
    "BID_AUTO_AI_QUIET",
    "BID_CALL_STORAGE_MAX_BYTES",
    "BID_CALL_TITLE_MAX_LENGTH",
    "BID_CONTENT_TYPES_MAX_BYTES",
    "BID_DOCUMENTS_PER_BID_MAX",
    "BID_DOCUMENT_TYPES",
    "BID_EXTRACTIONS_PER_WORKER",
    "BID_EXTRACTION_MAX_ATTEMPTS",
    "BID_EXTRACTION_MEMORY_BYTES",
    "BID_EXTRACTION_TIMEOUT",
    "BID_FILENAME_MAX_LENGTH",
    "BID_MUST_HAVES_MAX",
    "BID_ODF_MIMETYPE_MAX_BYTES",
    "BID_PROJECT_STORAGE_MAX_BYTES",
    "BID_QUESTIONS_PER_SECTION_MAX",
    "BID_QUOTE_MAX_LENGTH",
    "BID_QUOTE_MIN_LENGTH",
    "BID_REFUSED_ARCHIVE_ENTRY",
    "BID_SECTIONS_MAX",
    "BID_TEXT_PAGE_CHARS",
    "BID_UPLOADS_PER_PROCESS",
    "BID_UPLOAD_READ_TIMEOUT",
    "DEFAULT_BID_SCALE",
    "DEFAULT_BID_TEMPLATE",
    "DISAGREEMENT_SPREAD",
    "AiRunBatch",
    "Bid",
    "BidAiAssessment",
    "BidAiAssessmentList",
    "BidAiFindingView",
    "BidAiInclusionUpdate",
    "BidAiScoreView",
    "BidAiSectionScores",
    "BidAnswer",
    "BidAnswerIn",
    "BidAssessmentView",
    "BidAssessor",
    "BidAssessorsUpdate",
    "BidAwardIn",
    "BidCall",
    "BidCallCancelIn",
    "BidCallCreate",
    "BidCallMustHave",
    "BidCallMustHaveIn",
    "BidCallPermissions",
    "BidCallQuestion",
    "BidCallQuestionIn",
    "BidCallRef",
    "BidCallSection",
    "BidCallSectionIn",
    "BidCallStatusChange",
    "BidCallSummary",
    "BidCallTemplate",
    "BidCallTemplateIn",
    "BidCallUpdate",
    "BidCallView",
    "BidComparison",
    "BidComparisonRow",
    "BidComparisonSection",
    "BidDetail",
    "BidDocument",
    "BidDocumentExtraction",
    "BidDocumentFilename",
    "BidDocumentText",
    "BidDocumentTypeInfo",
    "BidDocumentUpdate",
    "BidEvidence",
    "BidIn",
    "BidList",
    "BidMustHaveCounts",
    "BidMustHaveIn",
    "BidMustHaveState",
    "BidPermissions",
    "BidProgress",
    "BidQuestionIn",
    "BidQuestionStats",
    "BidRef",
    "BidRejection",
    "BidRejectionIn",
    "BidScore",
    "BidSectionAssessments",
    "BidSectionAssessorsIn",
    "BidSectionIn",
    "BidSectionRef",
    "BidSectionScore",
    "BidSectionState",
    "BidTemplate",
    "BidTemplateIn",
    "BidTemplateMustHave",
    "BidTemplateQuestion",
    "BidTemplateSection",
    "BidUpdate",
    "MustHaveDecisionIn",
    "MyBidAssessment",
    "MyBidAssessmentIn",
    "RankedBid",
    "bid_total",
    "call_bid_status",
    "disagreement",
    "is_scored",
    "normalise_quote_text",
    "price_score",
    "question_mean",
    "quote_found",
    "quotes_found",
    "rank_bids",
    "round_score",
    "section_score",
]

# --- Limits (constants: simple beats configurable) -----------------------------------------
BID_CALL_TITLE_MAX_LENGTH: Final = 120
BID_SECTIONS_MAX: Final = 8
BID_QUESTIONS_PER_SECTION_MAX: Final = 15
BID_MUST_HAVES_MAX: Final = 20
BIDS_PER_CALL_MAX: Final = 50
"""Bids one call may hold (rejected ones included): 409 ``too_many_bids`` beyond."""
ASSESSORS_PER_SECTION_MAX: Final = 10
BID_DOCUMENTS_PER_BID_MAX: Final = 30
"""Documents per bid: 409 ``too_many_documents`` beyond."""
BID_CALL_STORAGE_MAX_BYTES: Final = 500 * 1024 * 1024
"""500 MiB per call: the sum of its documents' ``size_bytes`` **plus** their extracted text
(``text_chars``, one character counted as one byte): 409 ``call_storage_full`` for an upload
that would pass it (review S6; text extracted later may take a call a little over, by at
most :data:`app.models.bid.BID_TEXT_MAX_CHARS` per document)."""
BID_PROJECT_STORAGE_MAX_BYTES: Final = 5 * 1024 * 1024 * 1024
"""5 GiB per project, counted the same way over every call of the project's ideas: 409
``project_storage_full`` (review S6: one member owning many ideas can't fill the database)."""
BID_FILENAME_MAX_LENGTH: Final = 200
BID_UPLOADS_PER_PROCESS: Final = 2
"""Uploads an API process reads at once (each holds up to 25 MiB in memory): beyond, 503
``upload_busy`` with ``Retry-After: 5``. Taken after the 401/404/403 checks and before the
body is read (review S5)."""
BID_UPLOAD_READ_TIMEOUT: Final = timedelta(seconds=120)
"""The whole upload body must arrive within this (one buffer, no transaction held while
reading); slower: 408 ``upload_timeout``."""
BID_ARCHIVE_MAX_ENTRIES: Final = 2_000
"""ZIP-based uploads (OOXML, OpenDocument): more entries than this in the end-of-central-
directory record is 415 ``unsupported_document_type`` at upload (read before anything else,
review M5), and ``archive_limits`` in the extraction child."""
BID_CONTENT_TYPES_MAX_BYTES: Final = 256 * 1024
"""At upload, ``[Content_Types].xml`` is read (decompressed) up to this many bytes and
checked by substring, never parsed; bigger: 415 ``unsupported_document_type``."""
BID_ODF_MIMETYPE_MAX_BYTES: Final = 64
"""At upload, an OpenDocument file's ``mimetype`` entry is read up to this many bytes."""
BID_ARCHIVE_PART_MAX_BYTES: Final = 50 * 1024 * 1024
BID_ARCHIVE_TOTAL_MAX_BYTES: Final = 200 * 1024 * 1024
BID_ARCHIVE_MAX_RATIO: Final = 100
"""The extraction child's archive caps (review S4): an entry read past 50 MiB, the archive's
entries read past 200 MiB in total (actual bytes as they stream, never the sizes the
archive claims), or an entry whose uncompressed size is more than 100 times its compressed
size: ``failed`` ``archive_limits``. Nested archives are never opened."""
BID_EXTRACTION_TIMEOUT: Final = timedelta(seconds=30)
"""The extraction child's wall-clock limit (then killed: ``failed``, ``timeout``)."""
BID_EXTRACTION_MEMORY_BYTES: Final = 512 * 1024 * 1024
"""The extraction child's address-space cap (``RLIMIT_AS``; then ``failed``, ``memory``),
in a worker container with 1 GiB (review S4: the chart's worker limit goes to 1 GiB)."""
BID_EXTRACTIONS_PER_WORKER: Final = 1
"""Extraction children one worker process runs at once (the queue's concurrency)."""
BID_EXTRACTION_MAX_ATTEMPTS: Final = 3
"""A document whose extraction crashed the child (or the worker) this many times is
``failed`` ``internal_error`` (``bid_documents.extraction_attempts``): one bad file can't
crash-loop the worker."""
BID_TEXT_PAGE_CHARS: Final = 20_000
"""``get_bid_document_text`` (REST and MCP) returns the extracted text in pages of this many
characters (the last one shorter)."""
BID_QUOTE_MIN_LENGTH: Final = 20
BID_QUOTE_MAX_LENGTH: Final = 500
"""An AI quote's length after whitespace normalisation (at least 20 characters: a short
phrase like "ISO 27001" is found in almost any bid and proves nothing)."""
BID_AUTO_AI_QUIET: Final = timedelta(minutes=5)
"""The call's AI assessor starts a bid's one automatic assess run once none of its documents
is pending extraction **and** nothing was uploaded to the bid for this long (so a batch of
uploads is read together)."""
DISAGREEMENT_SPREAD: Final = 2
"""Two scores counted for one question that differ by this much or more flag disagreement."""

_HUNDRED = Decimal(100)
_ONE_DP = Decimal("0.1")
_TWO_DP = Decimal("0.01")


# --- What an upload may be ---------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class BidDocumentTypeInfo:
    """One allowed document type: the media type served on download and the extensions a
    stored filename may end with (the first is appended when the name has none of them)."""

    media_type: str
    extensions: tuple[str, ...]


BID_DOCUMENT_TYPES: Final[Mapping[BidDocumentType, BidDocumentTypeInfo]] = {
    BidDocumentType.PDF: BidDocumentTypeInfo("application/pdf", (".pdf",)),
    BidDocumentType.DOCX: BidDocumentTypeInfo(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document", (".docx",)
    ),
    BidDocumentType.XLSX: BidDocumentTypeInfo(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", (".xlsx",)
    ),
    BidDocumentType.PPTX: BidDocumentTypeInfo(
        "application/vnd.openxmlformats-officedocument.presentationml.presentation", (".pptx",)
    ),
    BidDocumentType.ODT: BidDocumentTypeInfo("application/vnd.oasis.opendocument.text", (".odt",)),
    BidDocumentType.ODS: BidDocumentTypeInfo(
        "application/vnd.oasis.opendocument.spreadsheet", (".ods",)
    ),
    BidDocumentType.TXT: BidDocumentTypeInfo("text/plain; charset=utf-8", (".txt",)),
    BidDocumentType.CSV: BidDocumentTypeInfo("text/csv; charset=utf-8", (".csv",)),
    BidDocumentType.PNG: BidDocumentTypeInfo("image/png", (".png",)),
    BidDocumentType.JPEG: BidDocumentTypeInfo("image/jpeg", (".jpg", ".jpeg")),
}
"""Every type an upload may be (contract-phase10 section 6), decided from the bytes. Macro-
enabled Office files (``.docm``, ``.xlsm``, ``.pptm``: a ``vbaProject.bin`` or a
``macroEnabled`` content type) and anything else are refused (415). Text is UTF-8 on
download (decoded with a fallback at upload, served as it was stored). Plain text is
``csv`` when the given name ends in ``.csv`` (any case) and ``txt`` otherwise: the bytes
decide that it is text, the name only which of the two labels it gets."""

BID_REFUSED_ARCHIVE_ENTRY: Final = re.compile(
    r"(?:^|/)(?:vbaProject\.bin|vbaData\.xml|vbaProjectSignature\.bin)$"
    r"|(?:^|/)activeX/"
    r"|(?:^|/)embeddings/[^/]*\.bin$"
    r"|(?:^|/)oleObject[^/]*\.bin$"
    r"|(?:^|/)(?:Basic|Scripts)/"
    r"|\.(?:docm|dotm|xlsm|xltm|xlsb|xlam|pptm|potm|ppsm|ppam|sldm)$",
    re.IGNORECASE,
)
"""An entry name (from the ZIP's central directory only, review M5) that makes an Office or
OpenDocument upload 415 ``macro_document``: VBA projects, ActiveX controls, embedded OLE
packages (an embedded ``.docm`` would get round the macro rule), OpenDocument ``Basic/`` and
``Scripts/``, and nested macro-enabled files by name. Active content the names can't show (a
PDF's JavaScript, launch actions or attached files; an Office file's remote template,
external links or DDE fields) is found by the extraction child, which sets
``BidDocument.active_content`` (review S3)."""


def _filename(value: str) -> str:
    if "/" in value or "\\" in value:
        raise ValueError("a file name, without folders (no / or \\)")
    if value in {".", ".."} or value.startswith("."):
        raise ValueError("the file name can't start with a dot")
    return value


BidDocumentFilename = Annotated[
    str,
    Field(min_length=1, max_length=BID_FILENAME_MAX_LENGTH),
    VisibleLine,
    SingleLine,
    AfterValidator(_filename),
]
"""The ``filename`` query parameter of an upload: one line (no control, bidi or tag
characters), no folders (``/`` or ``\\``: 422, never stripped), not starting with a dot, at
most 200 characters. The stored name ends with an extension of the type the bytes are (one
is appended otherwise: ``invoice.exe`` holding a PDF is stored as ``invoice.exe.pdf``); when
the name and that extension would pass 200 characters, the **stem** is cut so they fit
(review S12: ``bid_documents.filename`` is ``varchar(200)``)."""


# --- Templates: requests ------------------------------------------------------------------
ScaleLabel = Annotated[str, Field(min_length=1, max_length=80), VisibleLine, SingleLine]
SectionTitle = Annotated[str, Field(min_length=1, max_length=60), VisibleLine, SingleLine]
QuestionText = Annotated[str, Field(min_length=1, max_length=300), VisibleLine, SingleLine]
MustHaveText = Annotated[str, Field(min_length=1, max_length=200), VisibleLine, SingleLine]


class BidQuestionIn(RequestModel):
    text: QuestionText = Field(description="The question assessors answer (one line).")
    guidance: str = Field(
        default="",
        max_length=1_000,
        description="What a good answer shows (plain text; line breaks kept). Shown to assessors.",
    )
    type: BidQuestionType = BidQuestionType.SCORE
    weight: int | None = Field(
        default=None,
        ge=0,
        le=100,
        description=(
            "Relative to the section's other scored questions: score and price questions 1-100 "
            "(default 1), comment questions 0 (the default; any other value is a 422)."
        ),
    )

    @model_validator(mode="after")
    def _weight(self) -> BidQuestionIn:
        if self.type is BidQuestionType.COMMENT:
            if self.weight not in (None, 0):
                raise ValueError("comment questions aren't scored: weight 0")
            self.weight = 0
        else:
            if self.weight == 0:
                raise ValueError("score and price questions need a weight of 1-100")
            self.weight = self.weight or 1
        return self


class BidSectionIn(RequestModel):
    title: SectionTitle
    guidance: Annotated[str, Field(max_length=500)] = ""
    weight: int = Field(ge=1, le=100, description="Percent of the total; the sections sum to 100.")
    questions: list[BidQuestionIn] = Field(
        min_length=1,
        max_length=BID_QUESTIONS_PER_SECTION_MAX,
        description="1-15, in order; at least one score question (assessors score it).",
    )

    @field_validator("questions")
    @classmethod
    def _one_score_question(cls, questions: list[BidQuestionIn]) -> list[BidQuestionIn]:
        if not any(question.type is BidQuestionType.SCORE for question in questions):
            raise ValueError("every section needs at least one score question")
        return questions


class BidMustHaveIn(RequestModel):
    text: MustHaveText = Field(
        description='e.g. "Insurance certificate" (document) or "Accepts our standard terms".'
    )
    kind: MustHaveKind
    pricing: bool = Field(
        default=False,
        description=(
            'Document must-haves only (e.g. "Pricing schedule"): a file linked to it is a '
            "pricing document, shown only to call managers and the assessors of the section "
            "holding the price question (bid.view_price), never to the AI assessor, which isn't "
            "asked about it. A confirmation can't be one (422)."
        ),
    )

    @model_validator(mode="after")
    def _pricing_documents_only(self) -> BidMustHaveIn:
        if self.pricing and self.kind is not MustHaveKind.DOCUMENT:
            raise ValueError("only a document must-have can be a pricing one")
        return self


def _check_template(
    scale: Sequence[str],
    sections: Sequence[BidSectionIn],
    must_haves: Sequence[BidMustHaveIn],
) -> None:
    if len(scale) != BID_SCALE_POINTS:
        raise ValueError(f"the scale needs {BID_SCALE_POINTS} labels, one per score 0-5")
    if sum(section.weight for section in sections) != 100:
        raise ValueError("the section weights must add up to 100")
    titles = [section.title.casefold() for section in sections]
    if len(set(titles)) != len(titles):
        raise ValueError("section titles must be unique")
    prices = [
        question
        for section in sections
        for question in section.questions
        if question.type is BidQuestionType.PRICE
    ]
    if len(prices) > 1:
        raise ValueError("a template has at most one price question")
    texts = [must_have.text.casefold() for must_have in must_haves]
    if len(set(texts)) != len(texts):
        raise ValueError("must-haves must be unique")


class BidTemplateIn(RequestModel):
    """A project's default bid evaluation template (``replace_bid_template``, the complete
    template; last write wins). Calls copy it when they are created: changing it never
    touches an existing call."""

    scale: list[ScaleLabel] = Field(
        min_length=BID_SCALE_POINTS,
        max_length=BID_SCALE_POINTS,
        description='One anchor per score, 0 to 5 ("0: No response", ..., "5: Excellent").',
    )
    sections: list[BidSectionIn] = Field(
        min_length=1,
        max_length=BID_SECTIONS_MAX,
        description="1-8 sections in order; weights sum to 100; titles unique (any case).",
    )
    must_haves: list[BidMustHaveIn] = Field(
        default_factory=list,
        max_length=BID_MUST_HAVES_MAX,
        description="0-20, in order, unique (any case).",
    )

    @model_validator(mode="after")
    def _template(self) -> BidTemplateIn:
        _check_template(self.scale, self.sections, self.must_haves)
        return self


class BidCallQuestionIn(BidQuestionIn):
    id: UUID | None = Field(
        default=None,
        description=(
            "An existing question of this call (keeps it); omit for a new one. Another call's "
            "or an unknown id: 422 unknown_template_item."
        ),
    )


class BidCallSectionIn(BidSectionIn):
    id: UUID | None = Field(
        default=None,
        description="An existing section of this call (keeps its assessors); omit for a new one.",
    )
    questions: list[BidCallQuestionIn] = Field(  # type: ignore[assignment]
        min_length=1, max_length=BID_QUESTIONS_PER_SECTION_MAX
    )


class BidCallMustHaveIn(BidMustHaveIn):
    id: UUID | None = Field(
        default=None,
        description=(
            "An existing must-have of this call (keeps its results and linked documents); "
            "omit for a new one."
        ),
    )


class BidCallTemplateIn(RequestModel):
    """A call's own copy of the template (``replace_bid_call_template``): the complete
    template, editable until the call's first **human** assessment is submitted (then 409
    ``bid_call_template_locked``). Items keep their id; items left out are deleted (a
    section with its assessor assignments, a must-have with its results and document
    links); new must-haves get a result for every bid (``missing`` or ``unchecked``, which
    may move a qualified bid back to received). Any change clears the call's AI assessments
    (they were made against the old questions: ask again)."""

    scale: list[ScaleLabel] = Field(min_length=BID_SCALE_POINTS, max_length=BID_SCALE_POINTS)
    sections: list[BidCallSectionIn] = Field(min_length=1, max_length=BID_SECTIONS_MAX)
    must_haves: list[BidCallMustHaveIn] = Field(default_factory=list, max_length=BID_MUST_HAVES_MAX)

    @model_validator(mode="after")
    def _template(self) -> BidCallTemplateIn:
        _check_template(self.scale, self.sections, self.must_haves)
        ids = [s.id for s in self.sections if s.id] + [
            q.id for s in self.sections for q in s.questions if q.id
        ]
        ids += [m.id for m in self.must_haves if m.id]
        if len(set(ids)) != len(ids):
            raise ValueError("an id appears more than once")
        return self


DEFAULT_BID_SCALE: Final[tuple[str, ...]] = (
    "No response, or unacceptable",
    "Poor: major gaps",
    "Weak: some gaps or doubts",
    "Acceptable: meets the requirement",
    "Good: meets it with some added value",
    "Excellent: exceeds it, with clear evidence",
)
"""The default scale anchors, scores 0 to 5."""

DEFAULT_BID_TEMPLATE: Final = BidTemplateIn.model_validate(
    {
        "scale": list(DEFAULT_BID_SCALE),
        "sections": [
            {
                "title": "Technical",
                "guidance": "How well the solution meets our requirements, and how safely.",
                "weight": 40,
                "questions": [
                    {
                        "text": "How well does the proposed solution meet our requirements?",
                        "guidance": (
                            "Look for a clear description of how each requirement is met, "
                            "with evidence such as references, demos or examples."
                        ),
                        "type": "score",
                        "weight": 2,
                    },
                    {
                        "text": "How well will our data be kept secure and compliant?",
                        "guidance": (
                            "Certifications, where data is held, access controls, backups and "
                            "how personal data is protected."
                        ),
                        "type": "score",
                        "weight": 1,
                    },
                    {
                        "text": "What risks do you see in the technical approach?",
                        "guidance": "Note anything the team should ask the bidder about.",
                        "type": "comment",
                    },
                ],
            },
            {
                "title": "Commercial",
                "guidance": "What it costs and on what terms.",
                "weight": 40,
                "questions": [
                    {
                        "text": "Price",
                        "guidance": (
                            "The total price for the contract term, from the pricing schedule, "
                            "entered by the team. Scored automatically: lowest qualified price / "
                            "this price x 5."
                        ),
                        "type": "price",
                        "weight": 3,
                    },
                    {
                        "text": "How clear and complete is the pricing?",
                        "guidance": "All costs shown, no hidden extras, clear assumptions.",
                        "type": "score",
                        "weight": 1,
                    },
                    {
                        "text": "Are the payment terms and contract conditions acceptable?",
                        "guidance": "Payment schedule, notice periods, liability and exit terms.",
                        "type": "score",
                        "weight": 1,
                    },
                ],
            },
            {
                "title": "Delivery",
                "guidance": "Whether they can deliver it, when, and with whom.",
                "weight": 20,
                "questions": [
                    {
                        "text": "How realistic is the delivery plan and timeline?",
                        "guidance": "Milestones, dependencies, what they need from us.",
                        "type": "score",
                        "weight": 2,
                    },
                    {
                        "text": "How strong is the team and its relevant experience?",
                        "guidance": "Named people, similar work done before, references.",
                        "type": "score",
                        "weight": 1,
                    },
                ],
            },
        ],
        "must_haves": [
            {"text": "Signed form of tender", "kind": "document"},
            {"text": "Pricing schedule", "kind": "document", "pricing": True},
            {"text": "Insurance certificate", "kind": "document"},
            {"text": "Accepts our standard terms", "kind": "confirmation"},
        ],
    }
)
"""Every project's starting template (L3): Technical 40 / Commercial 40 (with the price
question) / Delivery 20, and four must-haves, the "Pricing schedule" a pricing one (review
M4, lead decision: prices travel in their own document, which only call managers and the
Commercial assessors open, not in the form of tender). Migration 0016 writes this JSON for
every existing project (``tests/test_schemas_phase10.py`` keeps the two equal); new
projects get it when they are created."""


# --- Templates: responses -------------------------------------------------------------------
class BidTemplateQuestion(ResponseModel):
    text: str
    guidance: str
    type: BidQuestionType
    weight: int = Field(description="0 for comment questions.")


class BidTemplateSection(ResponseModel):
    title: str
    guidance: str
    weight: int = Field(description="Percent of the total.")
    questions: list[BidTemplateQuestion]


class BidTemplateMustHave(ResponseModel):
    text: str
    kind: MustHaveKind
    pricing: bool = Field(description="A pricing document must-have (bid.view_price only).")


class BidTemplate(ResponseModel):
    """A project's default bid evaluation template (Project settings -> Bids)."""

    scale: list[str] = Field(description="Six anchors, scores 0 to 5.")
    sections: list[BidTemplateSection]
    must_haves: list[BidTemplateMustHave]
    updated_at: datetime | None
    updated_by: UserRef | None
    can_edit: bool = Field(
        description="project.edit_bid_template (project and platform admins, session only)."
    )


class BidCallQuestion(ResponseModel):
    id: UUID
    section_id: UUID
    position: int = Field(description="0-based, within its section.")
    text: str
    guidance: str
    type: BidQuestionType
    weight: int


class BidAssessor(ResponseModel):
    """A section's assessor and their progress on it. Never scores."""

    user: UserRef
    assigned_at: datetime
    can_assess: bool = Field(
        description=(
            "Still eligible (c28, checked live): an active person who can view the idea as a "
            "person in their own right (in a private project, a role there; never as the "
            "idea's guest researcher). False: their assignment grants nothing, their "
            "unsubmitted assessments aren't expected any more (progress) and their submitted "
            "ones still count; remove or replace them."
        )
    )
    progress: BidProgress = Field(
        description="Their submitted assessments of this section / bids that aren't rejected."
    )


class BidCallSection(ResponseModel):
    id: UUID
    position: int
    title: str
    guidance: str
    weight: int = Field(description="Percent of the total.")
    questions: list[BidCallQuestion] = Field(description="In order.")
    has_price: bool = Field(description="Holds the call's price question.")
    assessors: list[BidAssessor] = Field(description="By name.")


class BidCallMustHave(ResponseModel):
    id: UUID
    position: int
    text: str
    kind: MustHaveKind
    pricing: bool = Field(
        description=(
            "Its files are pricing documents (bid.view_price only; never read by the AI, which "
            "isn't asked about this must-have)."
        )
    )


class BidCallTemplate(ResponseModel):
    """The call's own evaluation template (a copy of the project's when it was created)."""

    scale: list[str] = Field(description="Six anchors, scores 0 to 5.")
    sections: list[BidCallSection] = Field(description="In order.")
    must_haves: list[BidCallMustHave] = Field(description="In order.")
    price_question_id: UUID | None
    locked: bool = Field(
        description=(
            "A human assessment has been submitted: the template can't change any more (409 "
            "bid_call_template_locked)."
        )
    )


# --- The call --------------------------------------------------------------------------------
CallTitle = Annotated[
    str, Field(min_length=1, max_length=BID_CALL_TITLE_MAX_LENGTH), VisibleLine, SingleLine
]
Currency = Annotated[str, Field(pattern=r"^[A-Z]{3}$", description="ISO 4217, e.g. GBP.")]
Reason = Annotated[str, Field(max_length=BID_REASON_MAX_LENGTH)]


class BidCall(BidCallSummary):
    """The call for those who see its bids (call managers and section assessors:
    ``bid.view_bids``)."""

    description: str = Field(description="Plain text: what is being bought.")
    currency: str
    assessment_due_at: datetime | None
    created_by: UserRef | None
    created_at: datetime
    updated_at: datetime
    template: BidCallTemplate
    progress: BidProgress = Field(
        description="Every assigned assessor x section x bid that isn't rejected."
    )
    ai_assessor: AiAgentRef | None = Field(
        description=(
            "The call's AI assessor (an agent with the purpose assess_bid), or null. While one "
            "is set and AI is on, each bid gets one automatic assess run once its documents "
            "are read (contract-phase10 section 9.1)."
        )
    )
    awarded_at: datetime | None
    awarded_bid: BidRef | None = Field(description="Set once awarded.")
    award_reason: str | None = Field(description="Call managers only (null for assessors).")
    cancelled_at: datetime | None
    cancel_reason: str | None = Field(description="Call managers only (null for assessors).")


class BidCallPermissions(ResponseModel):
    """What you may do on the Bids tab (the API enforces the same rules)."""

    can_create: bool = Field(
        description=(
            "bid.manage and c27: no call yet, the idea in Proposal with a proposal, not "
            'closed, the project not archived: show "Start a call for bids".'
        )
    )
    can_manage_call: bool = Field(
        description=(
            "bid.manage (the idea's owner, project admins, platform admins) and the call not "
            "awarded or cancelled: settings (and the AI assessor), opening and closing it, "
            "assessors, bids, must-haves, AI inclusion."
        )
    )
    can_edit_template: bool = Field(
        description="can_manage_call and the template isn't locked (no human assessment yet)."
    )
    can_upload_documents: bool = Field(
        description=(
            "bid.upload_document (session only), before the award: upload bid documents, mark "
            "them pricing, link them to must-haves, delete them."
        )
    )
    can_decide: bool = Field(
        description=(
            "bid.decide (session only): reject or reinstate bids, award or cancel the call."
        )
    )
    can_delete_call: bool = Field(
        description=(
            "bid.delete_call (session only, c30): the call is a draft or cancelled, or awarded "
            "and you are a platform admin (the bidders' data goes with it)."
        )
    )
    can_view_bids: bool = Field(
        description="bid.view_bids: the bids, their documents and must-have results."
    )
    can_see_prices: bool = Field(
        description=(
            "bid.view_price: call managers, and the assessors of the section holding the price "
            "question."
        )
    )
    can_view_scores: bool = Field(
        description=(
            "bid.view_scores (call managers): the comparison, the AI's assessments and the "
            "report, Markdown and PDF (parts hidden while you owe an assessment yourself)."
        )
    )
    can_assess: bool = Field(
        description="You assess at least one section and the call is being assessed."
    )
    assess_section_ids: list[UUID] = Field(description="The sections you assess (any status).")
    can_request_ai: bool = Field(
        description=(
            'ai.assess_bid and c10: "Ask AI to assess" / "Assess all with AI" (the call open '
            "or being assessed)."
        )
    )
    request_ai_blocked_by: AiBlockedReason | None = Field(
        description="Why can_request_ai is false (null when true)."
    )


class BidCallView(ResponseModel):
    """The Bids tab: the call (as much of it as you may see) and what you may do."""

    summary: BidCallSummary | None = Field(
        description="Null when the idea has no call (or for a guest researcher: 404 anyway)."
    )
    call: BidCall | None = Field(
        description="Call managers and section assessors only (bid.view_bids); else null."
    )
    ai_agents: list[AiAgentRef] = Field(
        description="Agents you may ask to assess bids now (c10 for assess_bid), by name."
    )
    permissions: BidCallPermissions


class BidCallCreate(RequestModel):
    """Start the idea's call for bids: a draft with a copy of the project's template."""

    title: CallTitle = Field(description='e.g. "Test data generator: build partner".')
    description: str = Field(default="", max_length=BID_CALL_DESCRIPTION_MAX_LENGTH)
    currency: Currency = "GBP"


class BidCallUpdate(RequestModel):
    """The call's settings, the complete new state (``PUT``; last write wins). The
    deadline changes only while the call is a draft or open (a change while assessing: 409
    ``bid_call_not_open``, so ``late`` never flips after bids are closed); an open call keeps
    one (409 ``bid_call_deadline_required``). The currency is a label and changes until the
    award. The assessment due date is set with the assessors (``set_bid_assessors``)."""

    title: CallTitle
    description: str = Field(max_length=BID_CALL_DESCRIPTION_MAX_LENGTH)
    currency: Currency
    deadline_at: DueAt | None = Field(
        description="Bids received after it are marked late, not refused. Needed to open."
    )
    ai_assessor_id: UUID | None = Field(
        description=(
            "The call's AI assessor: an agent that may assess bids on this idea now (c10 for "
            "assess_bid, else 409 ai_unavailable; an unchanged value isn't checked again), or "
            "null for none. Each bid then gets one automatic assess run (section 9.1)."
        )
    )


class BidCallStatusChange(RequestModel):
    """Move the call (``bid.manage``): draft -> open (needs a deadline), open -> assessing,
    assessing -> open (only while no person's assessment is submitted). Cancelling is
    ``cancel_bid_call``, awarding ``award_bid_call``."""

    status: Literal[BidCallStatus.OPEN, BidCallStatus.ASSESSING]


class BidCallCancelIn(RequestModel):
    """Cancel the call (``bid.decide``, session only) from draft, open or assessing: it
    becomes read-only; active AI assess runs of its bids are cancelled."""

    reason: Reason = Field(default="", description="Optional, plain text (at most 500).")


class BidSectionAssessorsIn(RequestModel):
    section_id: UUID
    user_ids: list[UUID] = Field(
        max_length=ASSESSORS_PER_SECTION_MAX,
        description="0-10 people (duplicates merged); each must be eligible (c28).",
    )

    @field_validator("user_ids")
    @classmethod
    def _distinct(cls, user_ids: list[UUID]) -> list[UUID]:
        return list(dict.fromkeys(user_ids))


class BidAssessorsUpdate(RequestModel):
    """Who assesses each section, and by when: the complete new state (``PUT``, session
    only; the one writer of the call's assessment due date). Every section of the call
    exactly once. People added are asked ("Asked to assess bids"). Removing someone from a
    section deletes their **drafts** of it; someone who has **submitted** an assessment of
    that section can't be removed (409 ``assessor_has_submitted``), and you can't remove
    yourself from a section while you still owe it for any bid of the call, rejected ones
    included (403 ``cannot_remove_self``: otherwise a pending assessor could step out, read
    the scores and come back)."""

    sections: list[BidSectionAssessorsIn] = Field(min_length=1, max_length=BID_SECTIONS_MAX)
    due_at: DueAt | None = Field(
        description="The assessment due date (null: none): reminders 2 days before and on it."
    )

    @field_validator("sections")
    @classmethod
    def _each_once(cls, sections: list[BidSectionAssessorsIn]) -> list[BidSectionAssessorsIn]:
        ids = [section.section_id for section in sections]
        if len(set(ids)) != len(ids):
            raise ValueError("a section appears more than once")
        return sections


class BidAwardIn(RequestModel):
    """Award the call to one qualified bid (``bid.decide``, session only, while assessing)."""

    bid_id: UUID
    reason: Reason = Field(default="", description="Optional, plain text (call managers read it).")


# --- Bids ----------------------------------------------------------------------------------
_EMAIL = r"^[^@\s]+@[^@\s]+$"
_RECEIVED_MAX_AHEAD = timedelta(minutes=5)
_RECEIVED_MAX_BACK = timedelta(days=366)


def _received(value: datetime) -> datetime:
    utc = value.astimezone(UTC)
    now = datetime.now(UTC)
    if not now - _RECEIVED_MAX_BACK <= utc <= now + _RECEIVED_MAX_AHEAD:
        raise ValueError("received_at must be in the past year (not in the future)")
    return utc


ReceivedAt = Annotated[AwareDatetime, AfterValidator(_received)]
Price = Annotated[
    Decimal,
    Field(gt=0, max_digits=14, decimal_places=2, description="In the call's currency, > 0."),
]


class BidIn(RequestModel):
    """A bid as the team enters it (``create_bid``; ``update_bid`` takes the complete new
    state as :class:`BidUpdate`). Contact details are stored as given and never emailed by
    Soundings."""

    bidder: Annotated[str, Field(min_length=1, max_length=120), VisibleLine, SingleLine] = Field(
        description="The bidder organisation."
    )
    contact_name: Annotated[str, Field(max_length=120), SingleLine] = ""
    contact_email: Annotated[str, Field(max_length=254, pattern=_EMAIL), SingleLine] | None = None
    received_at: ReceivedAt | None = Field(
        default=None,
        description="When the bid arrived (default now; at most a year back, not ahead).",
    )
    price: Price | None = Field(
        default=None,
        description=(
            "Only when the call has a price question (else 422 price_not_asked); a bid "
            "without one gets no price score (and so no total)."
        ),
    )
    notes: str = Field(default="", max_length=BID_NOTES_MAX_LENGTH, description="Plain text.")


class BidUpdate(BidIn):
    """``update_bid``: the complete new state, with ``received_at`` **required** (review S11:
    leaving it out must not reset it to now and flip ``late``). Its stored value is always
    accepted; a changed one must be within a year back and not ahead (422)."""

    received_at: AwareDatetime = Field(
        description="When the bid arrived: send the stored value unless correcting it."
    )


class BidRejectionIn(RequestModel):
    """Reject a bid (one click, a reason; ``bid.decide``, session only). Allowed until the
    award; ``reinstate_bid`` undoes it."""

    reason: Annotated[str, Field(min_length=1, max_length=BID_REASON_MAX_LENGTH), VisibleText]


class MustHaveDecisionIn(RequestModel):
    """A person's decision on one must-have of a bid (``bid.manage``)."""

    result: Literal[MustHaveResult.MET, MustHaveResult.NOT_MET] | None = Field(
        description=(
            "met or not_met; null clears the decision (back to missing or met for a document, "
            "depending on its linked files, or unchecked). A document must-have without a "
            "linked file can't be met (409 document_missing): upload it first."
        )
    )
    note: Annotated[str, Field(max_length=BID_REASON_MAX_LENGTH)] = ""


class BidRejection(ResponseModel):
    """The bid's current rejection, or its last one once reinstated (review consider-11: the
    reason is kept, so the decision stays on record)."""

    reason: str
    rejected_by: UserRef | None
    rejected_at: datetime
    reinstated_at: datetime | None = Field(description="Set when the bid was reinstated.")
    reinstated_by: UserRef | None


class BidMustHaveCounts(ResponseModel):
    """The bid's must-have results at a glance ("1 missing")."""

    met: int
    not_met: int
    missing: int
    unchecked: int


class BidSectionState(ResponseModel):
    """One of your sections for this bid."""

    section: BidSectionRef
    state: EvaluatorState = Field(description="invited (nothing saved), draft or submitted.")


class Bid(BidRef):
    """A bid, for call managers and section assessors (``bid.view_bids``). Assessors never
    see rejected bids (404), contact details, notes or rejection reasons."""

    contact_name: str = Field(description='Call managers only ("" for assessors).')
    contact_email: str | None = Field(description="Call managers only.")
    received_at: datetime
    late: bool = Field(description="Received after the call's deadline.")
    price: str | None = Field(
        description=(
            'Decimal string in the call\'s currency ("120000.00"); null when not entered or '
            "hidden (price_hidden)."
        )
    )
    price_hidden: bool = Field(
        description=(
            "bid.view_price denied: you assess a section that doesn't hold the price question."
        )
    )
    notes: str = Field(description='Call managers only ("" for assessors).')
    rejection: BidRejection | None = Field(
        description="Call managers only: the current rejection, or the last one if reinstated."
    )
    must_haves: BidMustHaveCounts
    document_count: int = Field(
        description="Documents you can see (pricing documents only with bid.view_price)."
    )
    restricted_document_count: int = Field(
        description=(
            "Pricing documents you may not open (counted, never named); 0 with bid.view_price."
        )
    )
    progress: BidProgress = Field(description="Its assessments: submitted / expected.")
    my_progress: BidProgress | None = Field(
        description="Yours on this bid (your sections), when you assess the call."
    )
    my_sections: list[BidSectionState] = Field(
        description="Your sections for this bid and where you are with each, in order (the queue)."
    )
    entered_by: UserRef | None
    created_at: datetime
    updated_at: datetime


class BidList(ResponseModel):
    """The call's bids, in the order they were received (not paged: at most 50)."""

    items: list[Bid]


class BidEvidence(ResponseModel):
    """A quote the AI gave as evidence, and the server's check of it. It proves the words are
    in the document, not that they support the score: people judge that."""

    document_id: UUID
    quote: str = Field(description="Untrusted: the AI's text, as it gave it.")
    found: bool = Field(
        description=(
            "The quote is in the document's extracted text (whitespace-normalised): show "
            '"Found in the document"; false: "Not found in the document".'
        )
    )


class BidAiFindingView(ResponseModel):
    """The AI's pre-check of one must-have: a suggestion only."""

    ai_assessment_id: UUID
    agent: UserRef = Field(description="The agent's service account (show an AI badge).")
    finding: AiMustHaveFinding
    rationale: str = Field(description="Untrusted agent text (rendered as plain text).")
    evidence: list[BidEvidence]
    submitted_at: datetime


class BidMustHaveState(ResponseModel):
    """A bid's result for one must-have, with the evidence for it."""

    must_have: BidCallMustHave
    result: MustHaveResult
    automatic: bool = Field(
        description=(
            "Nobody decided it: missing (no file) or met because a document is linked. "
            "False once a person decided (decided_by)."
        )
    )
    decided_by: UserRef | None
    decided_at: datetime | None
    note: str
    document_ids: list[UUID] = Field(
        description="Documents linked to it that you can see (pricing ones need bid.view_price)."
    )
    restricted_document_count: int = Field(
        description=(
            'Linked pricing documents you may not see: show the must-have as "present '
            '(restricted)", without a file name.'
        )
    )
    ai_findings: list[BidAiFindingView] = Field(
        description=(
            "The AI's suggestions (never change the result). None for a pricing must-have "
            "(the AI isn't asked about it)."
        )
    )


class BidPermissions(ResponseModel):
    """What you may do with this bid (the API enforces the same rules)."""

    can_edit: bool = Field(description="bid.manage, the call not awarded or cancelled.")
    can_delete: bool = Field(description="bid.decide, the call draft or open.")
    can_upload: bool = Field(
        description="bid.upload_document (session only), before the award: upload, mark, delete."
    )
    can_decide_must_haves: bool = Field(description="bid.manage, before the award.")
    can_reject: bool = Field(description="bid.decide, before the award, not rejected yet.")
    can_reinstate: bool = Field(description="bid.decide, before the award, rejected.")
    reject_suggested: bool = Field(
        description=(
            "A must-have is missing or not met, or an AI assessor found one not met (a "
            'suggestion a person checks): offer "Reject" prominently.'
        )
    )
    can_assess: bool = Field(
        description="You assess a section, the call is being assessed, the bid isn't rejected."
    )
    can_request_ai: bool = Field(description="ai.assess_bid and c10, the bid not rejected.")
    can_view_ai: bool = Field(description="bid.view_scores: the AI's assessment of this bid.")


# --- Documents -----------------------------------------------------------------------------
class BidDocumentExtraction(ResponseModel):
    state: ExtractionState
    error: ExtractionError | None = Field(description="failed only.")
    chars: int | None = Field(description="Characters of text kept (done only).")
    truncated: bool = Field(description="The text was cut at 2,000,000 characters.")
    page_count: int = Field(
        description=f"Pages of {BID_TEXT_PAGE_CHARS:,} characters (0 unless done)."
    )


class BidDocument(ResponseModel):
    """A bid document's metadata. The SPA never renders a document inline: it shows the
    extracted text (``get_bid_document_text``) and offers the file as a download. A pricing
    document is listed only to principals with ``bid.view_price``."""

    id: UUID
    filename: str = Field(description="Safe display name; ends with its type's extension.")
    type: BidDocumentType
    content_type: str = Field(description="What a download is served as (the type's).")
    size_bytes: int
    sha256: str = Field(description="Hex SHA-256 of the file.")
    must_have_id: UUID | None = Field(description="The required-document must-have it satisfies.")
    pricing: bool = Field(
        description=(
            "A pricing document (marked at upload or later, or linked to a pricing must-have): "
            "only call managers and the price section's assessors see it; the AI never reads it."
        )
    )
    active_content: bool = Field(
        description=(
            "The extraction found content that can act when the file is opened (a PDF's "
            "JavaScript, launch actions or attached files; an Office file's remote template, "
            "external links or DDE fields): warn before the download."
        )
    )
    uploaded_by: UserRef | None
    uploaded_at: datetime
    extraction: BidDocumentExtraction


class BidDocumentText(ResponseModel):
    """One page of a document's extracted text (untrusted: written by the bidder)."""

    document_id: UUID
    state: ExtractionState
    page: int = Field(ge=1)
    page_count: int
    text: str = Field(description="Plain text; empty unless done. Never render it as HTML.")
    truncated: bool


class BidDocumentUpdate(RequestModel):
    """A document's link and pricing mark, the complete new state (``bid.upload_document``,
    session only; audited ``bid_document.update``). Marking a document **pricing** deletes the
    bid's AI assessments and cancels its active assess runs (the AI may have read it: ask
    again); unmarking opens it to every assessor and the AI."""

    must_have_id: UUID | None = Field(
        description=(
            "A document must-have of the call (a confirmation or another call's: 422 "
            "invalid_must_have), or null."
        )
    )
    pricing: bool = Field(
        description=(
            "A pricing document. Linked to a pricing must-have it must be true (else 422 "
            "invalid_must_have)."
        )
    )


class BidDetail(Bid):
    """One bid: its documents, must-have results and what you may do."""

    documents: list[BidDocument] = Field(
        description="In upload order; pricing documents only with bid.view_price."
    )
    must_have_results: list[BidMustHaveState] = Field(description="In the template's order.")
    permissions: BidPermissions


# --- Assessments ---------------------------------------------------------------------------
BidScore = Annotated[int, Field(ge=0, le=BID_SCORE_MAX, description="0 (none) to 5.")]


class BidAnswerIn(RequestModel):
    question_id: UUID
    score: BidScore | None = Field(
        default=None,
        description="Score questions (null only in a draft); comment questions take none (422).",
    )
    comment: str = Field(
        default="",
        max_length=BID_COMMENT_MAX_LENGTH,
        description="The answer for comment questions; a note for score questions.",
    )


class MyBidAssessmentIn(RequestModel):
    """Your assessment of one section of a bid (``bid.assess``): save a draft or submit.
    Questions of the section only (others: 422 unknown_question; the price question isn't
    yours to score: 422 not_assessable); submitting needs every score question scored (422
    assessment_incomplete). Editable after submitting while the call is being assessed."""

    answers: list[BidAnswerIn] = Field(max_length=BID_QUESTIONS_PER_SECTION_MAX)
    submit: bool = False

    @field_validator("answers")
    @classmethod
    def _distinct(cls, answers: list[BidAnswerIn]) -> list[BidAnswerIn]:
        ids = [answer.question_id for answer in answers]
        if len(set(ids)) != len(ids):
            raise ValueError("a question appears more than once")
        return answers


class BidAnswer(ResponseModel):
    question_id: UUID
    score: int | None
    comment: str


class MyBidAssessment(ResponseModel):
    bid_id: UUID
    section: BidSectionRef
    state: EvaluatorState = Field(description="invited (nothing saved yet), draft or submitted.")
    answers: list[BidAnswer] = Field(description="In question order; empty when invited.")
    submitted_at: datetime | None
    edited_at: datetime | None = Field(description="Saved again after submitting.")
    can_edit: bool = Field(description="The call is being assessed and the bid isn't rejected.")


class BidAssessmentView(ResponseModel):
    """Someone's submitted assessment of a section (never a draft)."""

    assessor: UserRef
    submitted_at: datetime
    edited_at: datetime | None
    answers: list[BidAnswer]


class BidAiScoreView(ResponseModel):
    question_id: UUID
    score: int
    rationale: str = Field(description="Untrusted agent text.")
    evidence: list[BidEvidence]


class BidAiSectionScores(ResponseModel):
    ai_assessment_id: UUID
    agent: UserRef = Field(description="The agent's service account (AI badge).")
    included: bool = Field(description="Counted in the totals for this bid.")
    submitted_at: datetime
    scores: list[BidAiScoreView] = Field(description="The section's score questions.")


class BidQuestionStats(ResponseModel):
    """One question's scores for one bid: those counted (submitted human scores, plus the AI's
    when included). Price questions: the automatic score only."""

    question_id: UUID
    type: BidQuestionType
    mean: float | None = Field(description="0-5, 2 decimal places; null with no scores.")
    min: int | None
    max: int | None
    count: int
    disagreement: bool = Field(description="Two counted scores differ by 2 or more.")


class BidSectionAssessments(ResponseModel):
    """A section of a bid as you may see it (``bid.view_section_scores``): after you
    submitted it yourself, or as a call manager who doesn't owe it."""

    bid_id: UUID
    section: BidSectionRef
    hidden: bool = Field(
        description=('You still owe this assessment: nothing below ("Hidden until you submit").')
    )
    assessments: list[BidAssessmentView] = Field(description="Submitted ones, yours included.")
    ai: list[BidAiSectionScores]
    questions: list[BidQuestionStats] = Field(description="Score and price questions, in order.")
    section_score: float | None = Field(
        description="0-100, 1 decimal place; null until every scored question has a score."
    )


# --- The comparison ------------------------------------------------------------------------
class BidComparisonSection(ResponseModel):
    id: UUID
    title: str
    weight: int


class BidSectionScore(ResponseModel):
    section_id: UUID
    score: float | None = Field(description="0-100, 1 decimal place.")
    hidden: bool = Field(description="You owe this section's assessment of this bid.")
    progress: BidProgress
    disagreement: bool = Field(description="A question of the section has disagreement.")


class BidComparisonRow(ResponseModel):
    bid: BidRef
    received_at: datetime
    late: bool
    price: str | None = Field(description="Decimal string in the call's currency, or null.")
    price_score: float | None = Field(
        description=(
            "0-5, 2 decimal places: lowest scored price / this price x 5 (scored bids only: "
            "not rejected, every must-have met; section 8)."
        )
    )
    sections: list[BidSectionScore] = Field(
        description="In the template's order. A rejected bid's cells carry no score."
    )
    total: float | None = Field(
        description=(
            "0-100, 1 decimal place: the sum of section weight x section score. Null until "
            "every section has a score, for a bid that isn't scored (rejected, or a must-have "
            "not met), or while hidden."
        )
    )
    total_hidden: bool = Field(description="You owe an assessment of this bid.")
    rank: int | None = Field(
        description=(
            "1 = best; equal rounded totals share a rank (1, 2, 2, 4). Scored bids with a "
            "total only; null for every row while ranking_hidden."
        )
    )
    tied: bool = Field(description="Another bid has the same rank.")
    ai_included: bool = Field(description="An AI assessment is counted in this bid's scores.")
    progress: BidProgress


class BidComparison(ResponseModel):
    """Every bid side by side (``bid.view_scores``, call managers): ranked bids first (by
    rank, then lower price, earlier received, id), then the other scored and not yet
    qualified bids by when they were received, then rejected ones (no scores). Parts you
    owe an assessment for are hidden (``hidden``); while any row's total is hidden from you,
    **no row has a rank** and the rows are in the order received (``ranking_hidden``: the
    gaps in a ranking would show where the hidden bid stands, review M2). Before and after
    the award alike (an awarded or unsuccessful bid that met every must-have is scored)."""

    call: BidCallRef
    currency: str
    sections: list[BidComparisonSection]
    price_section_id: UUID | None
    lowest_price: str | None = Field(
        description="The lowest scored price (the formula's: not rejected, every must-have met)."
    )
    ranking_hidden: bool = Field(
        description=(
            "You owe an assessment of at least one bid: every rank is null, rows by received "
            '("The ranking shows once you have submitted your assessments").'
        )
    )
    rows: list[BidComparisonRow]
    progress: BidProgress
    complete: bool = Field(
        description="Every assigned assessor has submitted every bid that isn't rejected."
    )


# --- The AI assessor -----------------------------------------------------------------------
class BidAiAssessment(ResponseModel):
    """The AI's assessment of a bid (``bid.view_scores``). Scores of sections you owe an
    assessment for are left out (``hidden_section_ids``)."""

    id: UUID
    bid_id: UUID
    agent: UserRef = Field(description="The agent's service account (AI badge).")
    submitted_at: datetime
    included: bool = Field(
        description=(
            "Counted in this bid's scores. False until a call manager includes it, and again "
            "after a re-submission that changed a score."
        )
    )
    scores: list[BidAiScoreView]
    hidden_section_ids: list[UUID]
    findings: list[BidAiFindingView]
    quotes_not_found: int = Field(description="Quotes the server couldn't find in the text.")


class BidAiAssessmentList(ResponseModel):
    items: list[BidAiAssessment] = Field(description="One per agent that assessed the bid.")
    can_include: bool = Field(description="bid.manage, before the award.")


class BidAiInclusionUpdate(RequestModel):
    """Count an AI assessment in this bid's scores, or leave it out again."""

    include: bool


class AiRunBatch(ResponseModel):
    """ "Assess all with AI": a run per bid that isn't rejected (an active one is returned as
    it is). Each new run counts toward your 20 AI requests an hour: the runs that fit are
    started, in the order the bids were received, the rest are ``skipped`` (ask again later);
    429 only when none fits."""

    items: list[AiRun]
    created: int = Field(description="New runs started.")
    skipped: int = Field(description="Bids not started: your hourly AI limit was reached.")


# --- Scoring (contract-phase10 section 7; ADR 0018) ------------------------------------------
def round_score(value: Fraction | Decimal | float, places: int = 1) -> float:
    """Half up to ``places`` decimals (the API's numbers). Computing uses exact fractions;
    only results are rounded."""
    exponent = _ONE_DP if places == 1 else _TWO_DP
    if isinstance(value, Fraction):
        decimal = Decimal(value.numerator) / Decimal(value.denominator)
    else:
        decimal = Decimal(str(value))
    return float(decimal.quantize(exponent, rounding=ROUND_HALF_UP))


def question_mean(scores: Iterable[int]) -> Fraction | None:
    """The mean of the scores counted for one question (submitted human scores, plus each
    included AI score); ``None`` without any."""
    values = list(scores)
    if not values:
        return None
    return Fraction(sum(values), len(values))


def disagreement(scores: Iterable[int]) -> bool:
    """Two counted scores of one question differ by :data:`DISAGREEMENT_SPREAD` or more."""
    values = list(scores)
    return len(values) >= 2 and max(values) - min(values) >= DISAGREEMENT_SPREAD


def is_scored(*, rejected: bool, results: Iterable[MustHaveResult]) -> bool:
    """A bid takes part in the scoring (the price formula's lowest price, section scores,
    totals, the ranking) when it isn't rejected and every must-have is met (a call without
    must-haves: every bid that isn't rejected), **whatever the award made it** (review M1:
    after the award no bid is ``qualified`` any more, yet the report and the comparison
    still rank the awarded and unsuccessful bids). Before the award this is exactly
    ``status == qualified``."""
    return not rejected and all(result is MustHaveResult.MET for result in results)


def price_score(price: Decimal | None, lowest_qualified: Decimal | None) -> Fraction | None:
    """Lowest scored price / this bid's price x 5 (0-5), for a **scored** bid
    (:func:`is_scored`, whose price is never below the lowest scored one); ``None`` without a
    price or a scored price to compare with. Rejected bids and bids with a must-have not met
    are out of the formula."""
    if price is None or lowest_qualified is None or price <= 0:
        return None
    return Fraction(lowest_qualified) / Fraction(price) * BID_SCORE_MAX


def section_score(questions: Iterable[tuple[int, Fraction | None]]) -> Fraction | None:
    """A section's score on 0-5: the weighted mean of its scored questions' scores
    (``(weight, score)`` pairs: score questions' means, the price question's score; comment
    questions are not passed). ``None`` while any of them has no score."""
    pairs = list(questions)
    if not pairs or any(score is None for _, score in pairs):
        return None
    weights = sum(weight for weight, _ in pairs)
    weighted = sum((weight * score for weight, score in pairs if score is not None), Fraction(0))
    return weighted / weights


def bid_total(sections: Iterable[tuple[int, Fraction | None]]) -> Fraction | None:
    """A bid's total on 0-100: the sum of section weight (percent) x section score (0-5,
    shown x 20 as 0-100). ``None`` while any section has no score."""
    pairs = list(sections)
    if not pairs or any(score is None for _, score in pairs):
        return None
    return sum(
        (Fraction(weight, 100) * score * 20 for weight, score in pairs if score is not None),
        Fraction(0),
    )


@dataclass(frozen=True, slots=True)
class RankedBid:
    """A bid's place in the ranking (:func:`rank_bids`)."""

    bid_id: UUID
    total: float
    rank: int
    tied: bool


def rank_bids(
    bids: Iterable[tuple[UUID, Fraction | None, Decimal | None, datetime]],
) -> list[RankedBid]:
    """The ranking of scored bids (:func:`is_scored`), best first: ``(bid id, total, price,
    received_at)`` for each; bids without a total aren't ranked. Ranks follow the **rounded**
    total (what people see), so equal rounded totals share a rank ("1, 2, 2, 4"); within a
    tie, the lower price comes first (no price last), then the earlier bid, then the id.
    The caller shows no rank at all to someone who owes an assessment of any bid
    (``BidComparison.ranking_hidden``)."""
    scored = [
        (round_score(total), price, received_at, bid_id)
        for bid_id, total, price, received_at in bids
        if total is not None
    ]
    scored.sort(
        key=lambda row: (
            -row[0],
            row[1] is None,
            row[1] if row[1] is not None else Decimal(0),
            row[2],
            str(row[3]),
        )
    )
    ranked: list[RankedBid] = []
    counts: dict[float, int] = {}
    for total, *_ in scored:
        counts[total] = counts.get(total, 0) + 1
    rank = 0
    previous: float | None = None
    for position, (total, _price, _received, bid_id) in enumerate(scored, start=1):
        if total != previous:
            rank, previous = position, total
        ranked.append(RankedBid(bid_id=bid_id, total=total, rank=rank, tied=counts[total] > 1))
    return ranked


def call_bid_status(
    *, rejected: bool, results: Iterable[MustHaveResult], awarded: bool | None = None
) -> BidStatus:
    """A bid's status from its facts (the service keeps ``bids.status`` equal to this):
    rejected wins; at the award, awarded or unsuccessful; else qualified when every
    must-have is met (a call without must-haves qualifies every bid), else received."""
    if rejected:
        return BidStatus.REJECTED
    if awarded is not None:
        return BidStatus.AWARDED if awarded else BidStatus.UNSUCCESSFUL
    if all(result is MustHaveResult.MET for result in results):
        return BidStatus.QUALIFIED
    return BidStatus.RECEIVED


_WHITESPACE = re.compile(r"\s+")


def normalise_quote_text(text: str) -> str:
    """What quote checks compare: every run of whitespace (Unicode ``\\s``: spaces, tabs,
    line breaks, no-break spaces) as one space, ends trimmed. Case and punctuation count."""
    return _WHITESPACE.sub(" ", text).strip()


def quote_found(quote: str, document_text: str) -> bool:
    """The AI's quote appears in the document's extracted text (both normalised), and is at
    least :data:`BID_QUOTE_MIN_LENGTH` characters once normalised. For one quote; a
    submission checks all of its quotes with :func:`quotes_found`."""
    needle = normalise_quote_text(quote)
    return len(needle) >= BID_QUOTE_MIN_LENGTH and needle in normalise_quote_text(document_text)


def quotes_found(
    quotes: Sequence[tuple[UUID, str]], document_texts: Mapping[UUID, str]
) -> list[bool]:
    """:func:`quote_found` for every ``(document id, quote)`` of a submission, normalising each
    cited document **once** (review S2: up to 420 quotes over 2,000,000-character texts). A
    document missing from ``document_texts`` finds nothing. CPU-bound: the service runs it
    off the event loop (``anyio.to_thread.run_sync``). The texts are the stored ones, which
    the extraction child already passed through ``app.mcp.text.visible_text`` (review S1), so
    REST, MCP and this check read the same characters."""
    normalised = {
        document_id: normalise_quote_text(document_texts[document_id])
        for document_id in {document_id for document_id, _ in quotes}
        if document_id in document_texts
    }
    found: list[bool] = []
    for document_id, quote in quotes:
        needle = normalise_quote_text(quote)
        haystack = normalised.get(document_id)
        found.append(
            haystack is not None and len(needle) >= BID_QUOTE_MIN_LENGTH and needle in haystack
        )
    return found
