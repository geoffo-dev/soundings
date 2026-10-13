"""Phase 10: bid evaluation (calls for bids, bids and their documents, section assessors,
assessments, the AI assessor).

Expand only (``scripts/lib/check-migrations.py``): new tables, new nullable columns, swapped
``CHECK`` constraints and a rebuilt index; nothing the previous release reads is dropped,
renamed or retyped.

* ``bid_templates``: each project's default bid evaluation template (one JSON document).
  **Every existing project gets the built-in default** (Technical 40 / Commercial 40 with
  the price question / Delivery 20, three must-haves: ``DEFAULT_TEMPLATE`` below, the same
  as ``app.schemas.bids.DEFAULT_BID_TEMPLATE``). A project created later by the previous
  release (a rollback window) has no row and reads as the built-in default.
* ``bid_calls`` (one per idea), its template copy ``bid_call_sections``,
  ``bid_call_questions`` (at most one price question per call: a partial unique index) and
  ``bid_call_must_haves``; ``bid_section_assessors``; ``bids`` (one awarded per call: a
  partial unique index) and ``bid_must_have_results``; ``bid_documents`` with
  ``bid_document_contents`` (``bytea``) and ``bid_document_texts``; ``bid_assessments``
  (referencing the assessor assignment, so removing an assessor deletes their assessments)
  and ``bid_assessment_answers``; ``bid_ai_assessments`` with ``bid_ai_scores`` and
  ``bid_ai_findings`` (quoted evidence as JSON arrays of at most three).
* ``ai_runs.bid_id`` (``assess_bid`` runs, and only they: ``ck_ai_runs_bid_iff_assess``) and
  ``ai_runs.bid_ai_assessment_id`` (the result; ``ck_ai_runs_result_matches_kind`` gains it);
  the run kind ``assess_bid`` (``ck_ai_runs_kind``) and the agent purpose
  (``ck_ai_agents_purposes``: 1-4 distinct purposes now); ``uq_ai_runs_active`` gains
  ``bid_id`` (one active run per idea, agent, kind, section **and bid**; the same as before
  for every other kind).
* Three notification types, ``assessor_assigned``, ``assessment_reminder``,
  ``assessments_complete``: the ``CHECK`` constraints of ``notifications.type``,
  ``notification_preferences.type`` and ``outbound_email.type`` are swapped (the columns are
  long enough: 20 and 25 characters). They default to ``immediate`` in code; someone who had
  every existing type off gets ``off`` rows for the three, so "Unsubscribe from all email"
  stays all.

Downgrade (below 0016 there is no bid evaluation): every call, bid, document (with its
bytes and text), assessment and AI assessment is **deleted**, with the ``assess_bid`` runs
(and their events) and the ``bid_call_changed`` feed events; notifications, outbox rows and
preferences of the three types are deleted; ``assess_bid`` is removed from every agent's
purposes, and an agent left with none gets ``research`` back as a placeholder, is disabled
and its key revoked (older code needs a purpose). The constraints and the index go back.

Hand-written to match the models exactly (``tests/test_domain_schema.py`` compares them).
See docs/erd.md and docs/api/contract-phase10.md.

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-13
"""

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016"
down_revision: str | Sequence[str] | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# --- Values, spelled out (a migration must not import app code that may change) ---------
CALL_STATUSES = ("draft", "open", "assessing", "awarded", "cancelled")
BID_STATUSES = ("received", "qualified", "rejected", "awarded", "unsuccessful")
QUESTION_TYPES = ("score", "price", "comment")
MUST_HAVE_KINDS = ("document", "confirmation")
MUST_HAVE_RESULTS = ("missing", "unchecked", "met", "not_met")
AI_FINDINGS = ("met", "not_met", "unclear")
DOCUMENT_TYPES = ("pdf", "docx", "xlsx", "pptx", "odt", "ods", "txt", "csv", "png", "jpeg")
EXTRACTION_STATES = ("pending", "done", "no_text", "failed")
EXTRACTION_ERRORS = (
    "timeout",
    "memory",
    "damaged",
    "encrypted",
    "archive_limits",
    "internal_error",
)
ASSESSMENT_STATUSES = ("draft", "submitted")

DOCUMENT_MAX_BYTES = 25 * 1024 * 1024
TEXT_MAX_CHARS = 2_000_000
SCALE_POINTS = 6
EVIDENCE_MAX = 3
SCORE_MAX = 5
REASON_MAX = 500
SHA256 = "^[0-9a-f]{64}$"

KINDS_BEFORE = ("evaluate", "research", "draft_section")
KINDS = (*KINDS_BEFORE, "assess_bid")
ACTIVE = "status IN ('queued', 'running')"
RESULT_MATCHES_KIND_BEFORE = (
    "(evaluation_id IS NULL OR kind = 'evaluate')"
    " AND (suggestion_id IS NULL OR kind = 'draft_section')"
    " AND (activity_event_id IS NULL OR kind = 'research')"
)
RESULT_MATCHES_KIND = (
    RESULT_MATCHES_KIND_BEFORE + " AND (bid_ai_assessment_id IS NULL OR kind = 'assess_bid')"
)
PURPOSES_DISTINCT_BEFORE = (
    "(cardinality(purposes) < 2 OR purposes[1] <> purposes[2])"
    " AND (cardinality(purposes) < 3"
    " OR (purposes[1] <> purposes[3] AND purposes[2] <> purposes[3]))"
)
PURPOSES_DISTINCT = " AND ".join(
    f"(cardinality(purposes) < {j} OR purposes[{i}] <> purposes[{j}])"
    for j in range(2, len(KINDS) + 1)
    for i in range(1, j)
)
"""``app.models.ai.AI_PURPOSES_DISTINCT_SQL`` for four purposes (every pair differs)."""

NOTIFICATION_TYPES_BEFORE = (
    "owner_assigned",
    "evaluator_invited",
    "evaluation_reminder",
    "evaluations_complete",
    "status_changed",
    "comment",
    "mention",
    "researcher_assigned",
    "research_reminder",
)
NEW_TYPES = ("assessor_assigned", "assessment_reminder", "assessments_complete")
NOTIFICATION_TYPES = (*NOTIFICATION_TYPES_BEFORE, *NEW_TYPES)
"""In ``app.models.enums.NotificationType`` order (the ``CHECK`` lists them so)."""
_EMAIL_ONLY = ("digest", "test", "submission_received", "submission_status_changed")
EMAIL_TYPES_BEFORE = (*NOTIFICATION_TYPES_BEFORE, *_EMAIL_ONLY)
EMAIL_TYPES = (*NOTIFICATION_TYPES, *_EMAIL_ONLY)
"""In ``app.models.enums.EmailType`` order."""
NEW_ACTIVITY_TYPES = ("bid_call_changed",)

TYPE_CHECKS: tuple[tuple[str, str], ...] = (
    ("notifications", "ck_notifications_type"),
    ("notification_preferences", "ck_notification_preferences_type"),
)

DEFAULT_TEMPLATE: dict[str, Any] = {
    "scale": [
        "No response, or unacceptable",
        "Poor: major gaps",
        "Weak: some gaps or doubts",
        "Acceptable: meets the requirement",
        "Good: meets it with some added value",
        "Excellent: exceeds it, with clear evidence",
    ],
    "sections": [
        {
            "title": "Technical",
            "guidance": "How well the solution meets our requirements, and how safely.",
            "weight": 40,
            "questions": [
                {
                    "text": "How well does the proposed solution meet our requirements?",
                    "guidance": (
                        "Look for a clear description of how each requirement is met, with "
                        "evidence such as references, demos or examples."
                    ),
                    "type": "score",
                    "weight": 2,
                },
                {
                    "text": "How well will our data be kept secure and compliant?",
                    "guidance": (
                        "Certifications, where data is held, access controls, backups and how "
                        "personal data is protected."
                    ),
                    "type": "score",
                    "weight": 1,
                },
                {
                    "text": "What risks do you see in the technical approach?",
                    "guidance": "Note anything the team should ask the bidder about.",
                    "type": "comment",
                    "weight": 0,
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
                        "The total price for the contract term, entered by the team. Scored "
                        "automatically: lowest qualified price / this price x 5."
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
        {"text": "Insurance certificate", "kind": "document"},
        {"text": "Accepts our standard terms", "kind": "confirmation"},
    ],
}
"""``app.schemas.bids.DEFAULT_BID_TEMPLATE`` as JSON (``tests/test_schemas_phase10.py``
keeps the two equal)."""


# --- Helpers ---------------------------------------------------------------------------------
def _id() -> sa.Column[Any]:
    return sa.Column("id", sa.Uuid(), nullable=False)


def _timestamp(name: str) -> sa.Column[Any]:
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def _timestamps() -> list[sa.Column[Any]]:
    return [_timestamp("created_at"), _timestamp("updated_at")]


def _values(values: Sequence[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _length(values: Sequence[str]) -> int:
    return max(len(value) for value in values)


def _enum(column: str, values: Sequence[str], **kwargs: Any) -> sa.Column[Any]:
    return sa.Column(column, sa.String(length=_length(values)), **kwargs)


def _enum_check(table: str, column: str, values: Sequence[str]) -> sa.CheckConstraint:
    return sa.CheckConstraint(f"{column} IN ({_values(values)})", name=op.f(f"ck_{table}_{column}"))


def _check(table: str, name: str, sql: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(sql, name=op.f(f"ck_{table}_{name}"))


def _fk(
    table: str, column: str, target: str, ondelete: str | None = "CASCADE"
) -> sa.ForeignKeyConstraint:
    referred = target.split(".")[0]
    return sa.ForeignKeyConstraint(
        [column], [target], name=op.f(f"fk_{table}_{column}_{referred}"), ondelete=ondelete
    )


def _pk(table: str, *columns: str) -> sa.PrimaryKeyConstraint:
    return sa.PrimaryKeyConstraint(*columns, name=op.f(f"pk_{table}"))


def _evidence(table: str) -> list[Any]:
    return [
        sa.Column(
            "evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        _check(
            table,
            "evidence_array",
            "CASE WHEN jsonb_typeof(evidence) = 'array'"
            f" THEN jsonb_array_length(evidence) <= {EVIDENCE_MAX} ELSE false END",
        ),
    ]


# --- Upgrade: the tables ---------------------------------------------------------------
def _templates() -> None:
    t = "bid_templates"
    op.create_table(
        t,
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("template", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        _timestamp("updated_at"),
        sa.Column("updated_by_id", sa.Uuid(), nullable=True),
        _check(t, "template_object", "jsonb_typeof(template) = 'object'"),
        _fk(t, "project_id", "projects.id"),
        _fk(t, "updated_by_id", "users.id", "SET NULL"),
        _pk(t, "project_id"),
    )
    op.execute(
        sa.text(
            "INSERT INTO bid_templates (project_id, template, updated_at)"
            " SELECT id, CAST(:template AS jsonb), now() FROM projects"
        ).bindparams(template=json.dumps(DEFAULT_TEMPLATE))
    )


def _calls() -> None:
    t = "bid_calls"
    op.create_table(
        t,
        _id(),
        sa.Column("idea_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        _enum("status", CALL_STATUSES, server_default="draft", nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="GBP", nullable=False),
        sa.Column("scale", postgresql.ARRAY(sa.String(length=80)), nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("assessment_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("awarded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("awarded_by_id", sa.Uuid(), nullable=True),
        sa.Column("award_reason", sa.Text(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        *_timestamps(),
        _enum_check(t, "status", CALL_STATUSES),
        _check(t, "title_not_empty", "length(title) > 0"),
        _check(t, "description_length", "length(description) <= 2000"),
        _check(t, "currency_format", "currency ~ '^[A-Z]{3}$'"),
        _check(
            t,
            "scale_points",
            f"cardinality(scale) = {SCALE_POINTS} AND array_position(scale, NULL) IS NULL",
        ),
        _check(t, "deadline_when_open", "status = 'draft' OR deadline_at IS NOT NULL"),
        _check(t, "awarded_iff_at", "(status = 'awarded') = (awarded_at IS NOT NULL)"),
        _check(t, "cancelled_iff_at", "(status = 'cancelled') = (cancelled_at IS NOT NULL)"),
        _check(t, "award_reason_awarded", "award_reason IS NULL OR status = 'awarded'"),
        _check(t, "cancel_reason_cancelled", "cancel_reason IS NULL OR status = 'cancelled'"),
        _check(
            t,
            "reason_length",
            f"length(award_reason) <= {REASON_MAX} AND length(cancel_reason) <= {REASON_MAX}",
        ),
        _fk(t, "idea_id", "ideas.id"),
        _fk(t, "created_by_id", "users.id", "SET NULL"),
        _fk(t, "awarded_by_id", "users.id", "SET NULL"),
        _pk(t, "id"),
        sa.UniqueConstraint("idea_id", name=op.f("uq_bid_calls_idea_id")),
    )
    op.create_index(
        "ix_bid_calls_assessment_due_at_assessing",
        t,
        ["assessment_due_at"],
        postgresql_where=sa.text("status = 'assessing' AND assessment_due_at IS NOT NULL"),
    )


def _template_copy() -> None:
    t = "bid_call_sections"
    op.create_table(
        t,
        _id(),
        sa.Column("call_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=60), nullable=False),
        sa.Column("guidance", sa.String(length=500), server_default="", nullable=False),
        sa.Column("weight", sa.SmallInteger(), nullable=False),
        *_timestamps(),
        _check(t, "title_not_empty", "length(title) > 0"),
        _check(t, "position_non_negative", "position >= 0"),
        _check(t, "weight_range", "weight BETWEEN 1 AND 100"),
        _fk(t, "call_id", "bid_calls.id"),
        _pk(t, "id"),
    )
    op.create_index("ix_bid_call_sections_call_id_position", t, ["call_id", "position"])
    op.create_index(
        "uq_bid_call_sections_call_id_title_lower",
        t,
        ["call_id", sa.text("lower(title)")],
        unique=True,
    )

    t = "bid_call_questions"
    op.create_table(
        t,
        _id(),
        sa.Column("call_id", sa.Uuid(), nullable=False),
        sa.Column("section_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("text", sa.String(length=300), nullable=False),
        sa.Column("guidance", sa.String(length=1000), server_default="", nullable=False),
        _enum("type", QUESTION_TYPES, nullable=False),
        sa.Column("weight", sa.SmallInteger(), nullable=False),
        *_timestamps(),
        _enum_check(t, "type", QUESTION_TYPES),
        _check(t, "text_not_empty", "length(text) > 0"),
        _check(t, "position_non_negative", "position >= 0"),
        _check(t, "weight_range", "weight BETWEEN 0 AND 100"),
        _check(t, "comment_iff_unweighted", "(type = 'comment') = (weight = 0)"),
        _fk(t, "call_id", "bid_calls.id"),
        _fk(t, "section_id", "bid_call_sections.id"),
        _pk(t, "id"),
    )
    op.create_index("ix_bid_call_questions_section_id_position", t, ["section_id", "position"])
    op.create_index("ix_bid_call_questions_call_id", t, ["call_id"])
    op.create_index(
        "uq_bid_call_questions_call_id_price",
        t,
        ["call_id"],
        unique=True,
        postgresql_where=sa.text("type = 'price'"),
    )

    t = "bid_call_must_haves"
    op.create_table(
        t,
        _id(),
        sa.Column("call_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("text", sa.String(length=200), nullable=False),
        _enum("kind", MUST_HAVE_KINDS, nullable=False),
        *_timestamps(),
        _enum_check(t, "kind", MUST_HAVE_KINDS),
        _check(t, "text_not_empty", "length(text) > 0"),
        _check(t, "position_non_negative", "position >= 0"),
        _fk(t, "call_id", "bid_calls.id"),
        _pk(t, "id"),
    )
    op.create_index("ix_bid_call_must_haves_call_id_position", t, ["call_id", "position"])
    op.create_index(
        "uq_bid_call_must_haves_call_id_text_lower",
        t,
        ["call_id", sa.text("lower(text)")],
        unique=True,
    )

    t = "bid_section_assessors"
    op.create_table(
        t,
        sa.Column("section_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("call_id", sa.Uuid(), nullable=False),
        sa.Column("assigned_by_id", sa.Uuid(), nullable=True),
        _timestamp("assigned_at"),
        _fk(t, "section_id", "bid_call_sections.id"),
        _fk(t, "user_id", "users.id"),
        _fk(t, "call_id", "bid_calls.id"),
        _fk(t, "assigned_by_id", "users.id", "SET NULL"),
        _pk(t, "section_id", "user_id"),
    )
    op.create_index("ix_bid_section_assessors_user_id_call_id", t, ["user_id", "call_id"])
    op.create_index("ix_bid_section_assessors_call_id", t, ["call_id"])


def _bids() -> None:
    t = "bids"
    op.create_table(
        t,
        _id(),
        sa.Column("call_id", sa.Uuid(), nullable=False),
        sa.Column("bidder", sa.String(length=120), nullable=False),
        sa.Column("contact_name", sa.String(length=120), server_default="", nullable=False),
        sa.Column("contact_email", sa.String(length=320), nullable=True),
        _timestamp("received_at"),
        sa.Column("price", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("notes", sa.Text(), server_default="", nullable=False),
        _enum("status", BID_STATUSES, server_default="received", nullable=False),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_by_id", sa.Uuid(), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("entered_by_id", sa.Uuid(), nullable=True),
        *_timestamps(),
        _enum_check(t, "status", BID_STATUSES),
        _check(t, "bidder_not_empty", "length(bidder) > 0"),
        _check(t, "price_positive", "price > 0"),
        _check(t, "notes_length", "length(notes) <= 2000"),
        _check(t, "rejected_iff_at", "(status = 'rejected') = (rejected_at IS NOT NULL)"),
        _check(t, "rejection_reason_iff_at", "(rejected_at IS NULL) = (rejection_reason IS NULL)"),
        _check(
            t, "rejection_reason_length", f"length(rejection_reason) BETWEEN 1 AND {REASON_MAX}"
        ),
        _fk(t, "call_id", "bid_calls.id"),
        _fk(t, "rejected_by_id", "users.id", "SET NULL"),
        _fk(t, "entered_by_id", "users.id", "SET NULL"),
        _pk(t, "id"),
    )
    op.create_index("ix_bids_call_id_status", t, ["call_id", "status"])
    op.create_index(
        "uq_bids_call_id_awarded",
        t,
        ["call_id"],
        unique=True,
        postgresql_where=sa.text("status = 'awarded'"),
    )

    t = "bid_must_have_results"
    op.create_table(
        t,
        sa.Column("bid_id", sa.Uuid(), nullable=False),
        sa.Column("must_have_id", sa.Uuid(), nullable=False),
        _enum("result", MUST_HAVE_RESULTS, nullable=False),
        sa.Column("decided_by_id", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.String(length=500), server_default="", nullable=False),
        _enum_check(t, "result", MUST_HAVE_RESULTS),
        _check(t, "decision_is_met_or_not", "decided_at IS NULL OR result IN ('met', 'not_met')"),
        _check(t, "decided_by_needs_at", "decided_by_id IS NULL OR decided_at IS NOT NULL"),
        _check(t, "note_length", f"length(note) <= {REASON_MAX}"),
        _fk(t, "bid_id", "bids.id"),
        _fk(t, "must_have_id", "bid_call_must_haves.id"),
        _fk(t, "decided_by_id", "users.id", "SET NULL"),
        _pk(t, "bid_id", "must_have_id"),
    )
    op.create_index(op.f("ix_bid_must_have_results_must_have_id"), t, ["must_have_id"])


def _documents() -> None:
    t = "bid_documents"
    op.create_table(
        t,
        _id(),
        sa.Column("bid_id", sa.Uuid(), nullable=False),
        sa.Column("call_id", sa.Uuid(), nullable=False),
        sa.Column("must_have_id", sa.Uuid(), nullable=True),
        sa.Column("filename", sa.String(length=200), nullable=False),
        _enum("type", DOCUMENT_TYPES, nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("uploaded_by_id", sa.Uuid(), nullable=True),
        _timestamp("uploaded_at"),
        _enum("extraction_state", EXTRACTION_STATES, server_default="pending", nullable=False),
        _enum("extraction_error", EXTRACTION_ERRORS, nullable=True),
        sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("text_chars", sa.Integer(), nullable=True),
        sa.Column("text_truncated", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        _enum_check(t, "type", DOCUMENT_TYPES),
        _enum_check(t, "extraction_state", EXTRACTION_STATES),
        _enum_check(t, "extraction_error", EXTRACTION_ERRORS),
        _check(t, "filename_not_empty", "length(filename) > 0"),
        _check(t, "size_bytes_range", f"size_bytes BETWEEN 1 AND {DOCUMENT_MAX_BYTES}"),
        _check(t, "sha256_format", f"sha256 ~ '{SHA256}'"),
        _check(
            t, "error_iff_failed", "(extraction_state = 'failed') = (extraction_error IS NOT NULL)"
        ),
        _check(t, "extracted_iff_done", "(extraction_state = 'pending') = (extracted_at IS NULL)"),
        _check(t, "text_iff_done", "(extraction_state = 'done') = (text_chars IS NOT NULL)"),
        _check(t, "text_chars_range", f"text_chars BETWEEN 0 AND {TEXT_MAX_CHARS}"),
        _fk(t, "bid_id", "bids.id"),
        _fk(t, "call_id", "bid_calls.id"),
        _fk(t, "must_have_id", "bid_call_must_haves.id", "SET NULL"),
        _fk(t, "uploaded_by_id", "users.id", "SET NULL"),
        _pk(t, "id"),
        sa.UniqueConstraint("bid_id", "sha256", name=op.f("uq_bid_documents_bid_id_sha256")),
    )
    op.create_index("ix_bid_documents_call_id", t, ["call_id"])
    op.create_index(
        "ix_bid_documents_uploaded_at_pending",
        t,
        ["uploaded_at"],
        postgresql_where=sa.text("extraction_state = 'pending'"),
    )
    op.create_index(
        "ix_bid_documents_must_have_id",
        t,
        ["must_have_id"],
        postgresql_where=sa.text("must_have_id IS NOT NULL"),
    )

    t = "bid_document_contents"
    op.create_table(
        t,
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        _check(t, "data_size", f"octet_length(data) BETWEEN 1 AND {DOCUMENT_MAX_BYTES}"),
        _fk(t, "document_id", "bid_documents.id"),
        _pk(t, "document_id"),
    )

    t = "bid_document_texts"
    op.create_table(
        t,
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        _check(t, "text_length", f"length(text) <= {TEXT_MAX_CHARS}"),
        _fk(t, "document_id", "bid_documents.id"),
        _pk(t, "document_id"),
    )


def _assessments() -> None:
    t = "bid_assessments"
    op.create_table(
        t,
        _id(),
        sa.Column("bid_id", sa.Uuid(), nullable=False),
        sa.Column("section_id", sa.Uuid(), nullable=False),
        sa.Column("assessor_id", sa.Uuid(), nullable=False),
        _enum("status", ASSESSMENT_STATUSES, server_default="draft", nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        _enum_check(t, "status", ASSESSMENT_STATUSES),
        _check(t, "submitted_has_at", "status <> 'submitted' OR submitted_at IS NOT NULL"),
        _fk(t, "bid_id", "bids.id"),
        sa.ForeignKeyConstraint(
            ["section_id", "assessor_id"],
            ["bid_section_assessors.section_id", "bid_section_assessors.user_id"],
            name=op.f("fk_bid_assessments_section_id_assessor_id_bid_section_assessors"),
            ondelete="CASCADE",
        ),
        _pk(t, "id"),
        sa.UniqueConstraint(
            "bid_id",
            "section_id",
            "assessor_id",
            name=op.f("uq_bid_assessments_bid_id_section_id_assessor_id"),
        ),
    )
    op.create_index("ix_bid_assessments_section_id_assessor_id", t, ["section_id", "assessor_id"])

    t = "bid_assessment_answers"
    op.create_table(
        t,
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("question_id", sa.Uuid(), nullable=False),
        sa.Column("score", sa.SmallInteger(), nullable=True),
        sa.Column("comment", sa.Text(), server_default="", nullable=False),
        _check(t, "score_range", f"score BETWEEN 0 AND {SCORE_MAX}"),
        _check(t, "comment_length", "length(comment) <= 2000"),
        _fk(t, "assessment_id", "bid_assessments.id"),
        _fk(t, "question_id", "bid_call_questions.id"),
        _pk(t, "assessment_id", "question_id"),
    )
    op.create_index(op.f("ix_bid_assessment_answers_question_id"), t, ["question_id"])


def _ai_assessments() -> None:
    t = "bid_ai_assessments"
    op.create_table(
        t,
        _id(),
        sa.Column("bid_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        _timestamp("submitted_at"),
        sa.Column("included", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        *_timestamps(),
        _fk(t, "bid_id", "bids.id"),
        _fk(t, "agent_id", "ai_agents.id", None),
        _pk(t, "id"),
        sa.UniqueConstraint(
            "bid_id", "agent_id", name=op.f("uq_bid_ai_assessments_bid_id_agent_id")
        ),
    )
    op.create_index(op.f("ix_bid_ai_assessments_agent_id"), t, ["agent_id"])

    t = "bid_ai_scores"
    op.create_table(
        t,
        sa.Column("ai_assessment_id", sa.Uuid(), nullable=False),
        sa.Column("question_id", sa.Uuid(), nullable=False),
        sa.Column("score", sa.SmallInteger(), nullable=False),
        sa.Column("rationale", sa.String(length=1000), nullable=False),
        *_evidence(t),
        _check(t, "score_range", f"score BETWEEN 0 AND {SCORE_MAX}"),
        _check(t, "rationale_length", "length(rationale) BETWEEN 1 AND 1000"),
        _fk(t, "ai_assessment_id", "bid_ai_assessments.id"),
        _fk(t, "question_id", "bid_call_questions.id"),
        _pk(t, "ai_assessment_id", "question_id"),
    )
    op.create_index(op.f("ix_bid_ai_scores_question_id"), t, ["question_id"])

    t = "bid_ai_findings"
    op.create_table(
        t,
        sa.Column("ai_assessment_id", sa.Uuid(), nullable=False),
        sa.Column("must_have_id", sa.Uuid(), nullable=False),
        _enum("finding", AI_FINDINGS, nullable=False),
        sa.Column("rationale", sa.String(length=1000), nullable=False),
        *_evidence(t),
        _enum_check(t, "finding", AI_FINDINGS),
        _check(t, "rationale_length", "length(rationale) BETWEEN 1 AND 1000"),
        _fk(t, "ai_assessment_id", "bid_ai_assessments.id"),
        _fk(t, "must_have_id", "bid_call_must_haves.id"),
        _pk(t, "ai_assessment_id", "must_have_id"),
    )
    op.create_index(op.f("ix_bid_ai_findings_must_have_id"), t, ["must_have_id"])


# --- Upgrade: AI runs and agents, notification types ---------------------------------------
def _swap_check(table: str, name: str, sql: str) -> None:
    op.drop_constraint(op.f(name), table, type_="check")
    op.create_check_constraint(op.f(name), table, sql)


def _purposes_check(kinds: Sequence[str], distinct: str) -> None:
    kinds_sql = f"ARRAY[{_values(kinds)}]::varchar[]"
    _swap_check(
        "ai_agents",
        "ck_ai_agents_purposes",
        f"cardinality(purposes) BETWEEN 1 AND {len(kinds)} AND purposes <@ {kinds_sql}"
        f" AND array_position(purposes, NULL) IS NULL AND {distinct}",
    )


def _active_runs_index(columns: list[str]) -> None:
    op.drop_index("uq_ai_runs_active", table_name="ai_runs")
    op.create_index(
        "uq_ai_runs_active",
        "ai_runs",
        columns,
        unique=True,
        postgresql_nulls_not_distinct=True,
        postgresql_where=sa.text(ACTIVE),
    )


def _ai_runs() -> None:
    op.add_column("ai_runs", sa.Column("bid_id", sa.Uuid(), nullable=True))
    op.add_column("ai_runs", sa.Column("bid_ai_assessment_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_ai_runs_bid_id_bids"), "ai_runs", "bids", ["bid_id"], ["id"], ondelete="CASCADE"
    )
    op.create_foreign_key(
        op.f("fk_ai_runs_bid_ai_assessment_id_bid_ai_assessments"),
        "ai_runs",
        "bid_ai_assessments",
        ["bid_ai_assessment_id"],
        ["id"],
        ondelete="SET NULL",
    )
    _swap_check("ai_runs", "ck_ai_runs_kind", f"kind IN ({_values(KINDS)})")
    _swap_check("ai_runs", "ck_ai_runs_result_matches_kind", RESULT_MATCHES_KIND)
    op.create_check_constraint(
        op.f("ck_ai_runs_bid_iff_assess"), "ai_runs", "(kind = 'assess_bid') = (bid_id IS NOT NULL)"
    )
    _active_runs_index(["idea_id", "agent_id", "kind", "section_key", "bid_id"])
    op.create_index(
        "ix_ai_runs_bid_id", "ai_runs", ["bid_id"], postgresql_where=sa.text("bid_id IS NOT NULL")
    )
    op.create_index(
        "ix_ai_runs_bid_ai_assessment_id",
        "ai_runs",
        ["bid_ai_assessment_id"],
        postgresql_where=sa.text("bid_ai_assessment_id IS NOT NULL"),
    )
    _purposes_check(KINDS, PURPOSES_DISTINCT)


def _swap_type_checks(notification_types: Sequence[str], email_types: Sequence[str]) -> None:
    for table, name in TYPE_CHECKS:
        _swap_check(table, name, f"type IN ({_values(notification_types)})")
    _swap_check("outbound_email", "ck_outbound_email_type", f"type IN ({_values(email_types)})")


def _notification_types() -> None:
    _swap_type_checks(NOTIFICATION_TYPES, EMAIL_TYPES)
    # Whoever had every existing type off keeps getting no email for the new ones.
    before = _values(NOTIFICATION_TYPES_BEFORE)  # constants, not input
    for new_type in NEW_TYPES:
        op.execute(
            "INSERT INTO notification_preferences (user_id, type, mode, updated_at) "  # noqa: S608
            f"SELECT user_id, '{new_type}', 'off', now() FROM notification_preferences "
            f"WHERE type IN ({before}) AND mode = 'off' "
            f"GROUP BY user_id HAVING count(*) = {len(NOTIFICATION_TYPES_BEFORE)} "
            "ON CONFLICT (user_id, type) DO NOTHING"
        )


def upgrade() -> None:
    _templates()
    _calls()
    _template_copy()
    _bids()
    _documents()
    _assessments()
    _ai_assessments()
    _ai_runs()
    _notification_types()


# --- Downgrade -------------------------------------------------------------------------------
def downgrade() -> None:
    new_types = _values(NEW_TYPES)  # constants, not input
    op.execute(f"DELETE FROM notifications WHERE type IN ({new_types})")  # noqa: S608
    op.execute(f"DELETE FROM outbound_email WHERE type IN ({new_types})")  # noqa: S608
    op.execute(f"DELETE FROM notification_preferences WHERE type IN ({new_types})")  # noqa: S608
    _swap_type_checks(NOTIFICATION_TYPES_BEFORE, EMAIL_TYPES_BEFORE)
    op.execute(
        f"DELETE FROM activity_events WHERE type IN ({_values(NEW_ACTIVITY_TYPES)})"  # noqa: S608
    )

    # AI: the assess runs go (their events cascade); agents lose the purpose.
    op.execute("DELETE FROM ai_runs WHERE kind = 'assess_bid'")
    op.drop_index("ix_ai_runs_bid_ai_assessment_id", table_name="ai_runs")
    op.drop_index("ix_ai_runs_bid_id", table_name="ai_runs")
    _active_runs_index(["idea_id", "agent_id", "kind", "section_key"])
    op.drop_constraint(op.f("ck_ai_runs_bid_iff_assess"), "ai_runs", type_="check")
    _swap_check("ai_runs", "ck_ai_runs_result_matches_kind", RESULT_MATCHES_KIND_BEFORE)
    _swap_check("ai_runs", "ck_ai_runs_kind", f"kind IN ({_values(KINDS_BEFORE)})")
    op.drop_constraint(
        op.f("fk_ai_runs_bid_ai_assessment_id_bid_ai_assessments"), "ai_runs", type_="foreignkey"
    )
    op.drop_constraint(op.f("fk_ai_runs_bid_id_bids"), "ai_runs", type_="foreignkey")
    op.drop_column("ai_runs", "bid_ai_assessment_id")
    op.drop_column("ai_runs", "bid_id")
    op.execute(
        "UPDATE api_keys SET revoked_at = now() WHERE revoked_at IS NULL AND user_id IN"
        " (SELECT service_account_id FROM ai_agents"
        " WHERE purposes = ARRAY['assess_bid']::varchar[])"
    )
    op.execute(
        "UPDATE ai_agents SET purposes = ARRAY['research']::varchar[], enabled = false"
        " WHERE purposes = ARRAY['assess_bid']::varchar[]"
    )
    op.execute(
        "UPDATE ai_agents SET purposes = array_remove(purposes, 'assess_bid')"
        " WHERE 'assess_bid' = ANY(purposes)"
    )
    _purposes_check(KINDS_BEFORE, PURPOSES_DISTINCT_BEFORE)

    for table in (
        "bid_ai_findings",
        "bid_ai_scores",
        "bid_ai_assessments",
        "bid_assessment_answers",
        "bid_assessments",
        "bid_document_texts",
        "bid_document_contents",
        "bid_documents",
        "bid_must_have_results",
        "bids",
        "bid_section_assessors",
        "bid_call_must_haves",
        "bid_call_questions",
        "bid_call_sections",
        "bid_calls",
        "bid_templates",
    ):
        op.drop_table(table)
