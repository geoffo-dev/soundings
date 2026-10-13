"""Phase 10 schemas (contract-phase10, ADR 0018): the bid evaluation template and its
default, the scoring math (the worked example of contract-phase10 section 7), the ranking
and its ties, quote checks, the document types, the AI assessor's MCP tools, the three
notification types and the key and guest tables, and blind safety by construction (what
everyone, notifications, My work and the AI see carries no score data, prices or bidders).
"""

from __future__ import annotations

import importlib.util
import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from typing import Any

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from app.authz.guest import RESEARCH_GUEST_ACCESS, GuestAccess, mcp_operation
from app.authz.keys import ROUTE_KEY_ACCESS, KeyAccess
from app.migrate import MIGRATIONS_DIR
from app.models.enums import (
    AiRunKind,
    ApiKeyScope,
    BidDocumentType,
    BidQuestionType,
    BidStatus,
    MustHaveResult,
    NotificationType,
)
from app.schemas.activity import BidCallChangedActivity
from app.schemas.ai import (
    AGENT_RUN_WRITE_TOOLS,
    AI_TOOL_MESSAGES,
    ASSESS_RUN_READ_TOOLS,
    AiRun,
    agent_key_scopes,
    run_message,
)
from app.schemas.audit import AuditAction
from app.schemas.bid_refs import BidCallRef, BidCallSummary, BidProgress
from app.schemas.bids import (
    BID_DOCUMENT_TYPES,
    DEFAULT_BID_TEMPLATE,
    BidCallTemplateIn,
    BidDocumentFilename,
    BidIn,
    BidQuestionIn,
    BidTemplateIn,
    bid_total,
    call_bid_status,
    disagreement,
    price_score,
    question_mean,
    quote_found,
    rank_bids,
    round_score,
    section_score,
)
from app.schemas.mcp import (
    BID_ASSESSMENT_INSTRUCTION,
    MCP_INSTRUCTIONS,
    MCP_TOOLS,
    PHASE10_MCP_TOOLS,
    McpBidFindingIn,
    McpBidScoreIn,
    SubmitBidAssessmentInput,
)
from app.schemas.notifications import (
    BID_NOTIFICATION_TYPES,
    DEFAULT_MODES,
    RESEARCH_GUEST_NOTIFICATION_TYPES,
    AssessmentReminderNotification,
    AssessmentsCompleteNotification,
    AssessorAssignedNotification,
    NotificationMode,
)
from app.schemas.work import WorkBidAssessment
from tests.test_contract_routes import PHASE10_OPERATIONS

T = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)


def _migration() -> Any:
    path = MIGRATIONS_DIR / "versions" / "20261013_0016_bid_evaluation.py"
    spec = importlib.util.spec_from_file_location("migration_0016", path)
    assert spec is not None
    assert spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


# --- The template ----------------------------------------------------------------------------
def test_the_default_template_is_the_one_the_migration_writes() -> None:
    assert DEFAULT_BID_TEMPLATE.model_dump(mode="json") == _migration().DEFAULT_TEMPLATE


def test_the_default_template_is_l3s() -> None:
    sections = DEFAULT_BID_TEMPLATE.sections
    assert [(s.title, s.weight) for s in sections] == [
        ("Technical", 40),
        ("Commercial", 40),
        ("Delivery", 20),
    ]
    prices = [q for s in sections for q in s.questions if q.type is BidQuestionType.PRICE]
    assert [q.text for q in prices] == ["Price"]
    assert prices[0] in sections[1].questions
    assert all(2 <= len(s.questions) <= 3 for s in sections)
    assert [(m.text, m.kind.value) for m in DEFAULT_BID_TEMPLATE.must_haves] == [
        ("Signed form of tender", "document"),
        ("Insurance certificate", "document"),
        ("Accepts our standard terms", "confirmation"),
    ]
    assert len(DEFAULT_BID_TEMPLATE.scale) == 6


def test_question_weights_default_by_type() -> None:
    assert BidQuestionIn.model_validate({"text": "Notes?", "type": "comment"}).weight == 0
    assert BidQuestionIn.model_validate({"text": "Good?"}).weight == 1
    assert BidQuestionIn.model_validate({"text": "Price", "type": "price", "weight": 3}).weight == 3
    for body in (
        {"text": "Notes?", "type": "comment", "weight": 1},
        {"text": "Good?", "type": "score", "weight": 0},
        {"text": "Price", "type": "price", "weight": 0},
    ):
        with pytest.raises(ValidationError):
            BidQuestionIn.model_validate(body)


def test_a_calls_template_keeps_ids_once_each() -> None:
    template = DEFAULT_BID_TEMPLATE.model_dump(mode="json")
    section_id, question_id = str(uuid.uuid4()), str(uuid.uuid4())
    template["sections"][0]["id"] = section_id
    template["sections"][0]["questions"][0]["id"] = question_id

    copy = BidCallTemplateIn.model_validate(template)

    assert copy.sections[0].id == uuid.UUID(section_id)
    assert copy.sections[0].questions[0].id == uuid.UUID(question_id)
    template["sections"][1]["id"] = section_id
    with pytest.raises(ValidationError, match="more than once"):
        BidCallTemplateIn.model_validate(template)
    template["sections"][1]["id"] = question_id  # an id is an id, whatever it names
    with pytest.raises(ValidationError, match="more than once"):
        BidCallTemplateIn.model_validate(template)


def test_the_project_template_takes_no_ids() -> None:
    template = DEFAULT_BID_TEMPLATE.model_dump(mode="json")
    template["sections"][0]["id"] = str(uuid.uuid4())

    with pytest.raises(ValidationError):
        BidTemplateIn.model_validate(template)


# --- Scoring: the worked example (contract-phase10 section 7, ADR 0018) ---------------------
# Technical 40 % (Q1 weight 2, Q2 weight 1), Commercial 40 % (Q3 the price, weight 3; Q4
# weight 1), Delivery 20 % (Q5). Bids A (120,000) and B (96,000) qualified, C (80,000)
# rejected: out of the price formula. Technical: carol and mateo; Commercial: priya;
# Delivery: sven and alice.
LOWEST = Decimal("96000")  # C's 80,000 doesn't count: it is rejected


def _bid(scores: dict[str, list[int]], price: Decimal) -> Fraction | None:
    technical = section_score([(2, question_mean(scores["Q1"])), (1, question_mean(scores["Q2"]))])
    commercial = section_score([(3, price_score(price, LOWEST)), (1, question_mean(scores["Q4"]))])
    delivery = section_score([(1, question_mean(scores["Q5"]))])
    return bid_total([(40, technical), (40, commercial), (20, delivery)])


A = {"Q1": [4, 5], "Q2": [4, 4], "Q4": [4], "Q5": [4, 5]}
B = {"Q1": [4, 2], "Q2": [3, 3], "Q4": [3], "Q5": [3, 4]}
AI_ON_B = {"Q1": 3, "Q2": 4, "Q4": 4, "Q5": 3}


def test_price_scores_compare_with_the_lowest_qualified_price() -> None:
    assert price_score(Decimal("120000"), LOWEST) == Fraction(4)
    assert price_score(Decimal("96000"), LOWEST) == Fraction(5)
    assert price_score(None, LOWEST) is None
    assert price_score(Decimal("96000"), None) is None
    assert round_score(price_score(Decimal("110000"), LOWEST) or 0, 2) == 4.36


def test_section_scores_are_weighted_means_shown_out_of_100() -> None:
    technical_a = section_score([(2, question_mean(A["Q1"])), (1, question_mean(A["Q2"]))])

    assert technical_a == Fraction(13, 3)
    assert round_score((technical_a or 0) * 20) == 86.7
    assert section_score([(1, None), (1, Fraction(3))]) is None  # a question without scores
    assert section_score([]) is None


def test_the_worked_example() -> None:
    total_a, total_b = _bid(A, Decimal("120000")), _bid(B, Decimal("96000"))

    assert total_a == Fraction(254, 3)  # 34.67 + 32 + 18
    assert round_score(total_a) == 84.7
    assert round_score(total_b or 0) == 74.0
    assert disagreement(B["Q1"]) is True  # 4 and 2
    assert disagreement(A["Q1"]) is False
    ranked = rank_bids(
        [
            (uuid.UUID(int=1), total_a, Decimal("120000"), T),
            (uuid.UUID(int=2), total_b, Decimal("96000"), T),
        ]
    )
    assert [(r.bid_id.int, r.total, r.rank, r.tied) for r in ranked] == [
        (1, 84.7, 1, False),
        (2, 74.0, 2, False),
    ]


def test_the_ai_counts_once_included() -> None:
    with_ai = {key: [*scores, AI_ON_B[key]] for key, scores in B.items()}

    total = _bid(with_ai, Decimal("96000"))

    assert round_score(total or 0) == 75.2
    assert disagreement(with_ai["Q1"]) is True  # 4, 2 and 3


def test_a_bid_without_a_section_score_has_no_total() -> None:
    assert bid_total([(60, Fraction(4)), (40, None)]) is None
    assert bid_total([(100, Fraction(5))]) == Fraction(100)
    assert bid_total([(100, Fraction(0))]) == Fraction(0)


def test_rounding_is_half_up_on_exact_values() -> None:
    assert round_score(Fraction(1729, 20)) == 86.5  # 86.45
    assert round_score(Fraction(1, 3) * 3) == 1.0
    assert round_score(Fraction(10, 3), 2) == 3.33


def test_equal_rounded_totals_share_a_rank() -> None:
    """Ties are what people see (the rounded total): competition ranking, "1, 2, 2, 4";
    within a tie the lower price first (none last), then the earlier bid, then the id."""
    late, early = T + timedelta(hours=2), T
    ranked = rank_bids(
        [
            (uuid.UUID(int=4), Fraction(6001, 100), Decimal("90000"), T),  # 60.01 -> 60.0
            (uuid.UUID(int=1), Fraction(80), Decimal("100000"), T),
            (uuid.UUID(int=2), Fraction(7403, 100), Decimal("95000"), late),  # 74.03 -> 74.0
            (uuid.UUID(int=3), Fraction(74), Decimal("95000"), early),
            (uuid.UUID(int=5), Fraction(74), None, early),
            (uuid.UUID(int=6), None, Decimal("1"), T),  # not ranked: no total
        ]
    )

    assert [(r.bid_id.int, r.rank, r.tied) for r in ranked] == [
        (1, 1, False),
        (3, 2, True),
        (2, 2, True),
        (5, 2, True),
        (4, 5, False),
    ]


@pytest.mark.parametrize(
    ("rejected", "results", "awarded", "status"),
    [
        (False, [MustHaveResult.MET, MustHaveResult.MET], None, BidStatus.QUALIFIED),
        (False, [], None, BidStatus.QUALIFIED),  # a call without must-haves
        (False, [MustHaveResult.MET, MustHaveResult.MISSING], None, BidStatus.RECEIVED),
        (False, [MustHaveResult.UNCHECKED], None, BidStatus.RECEIVED),
        (False, [MustHaveResult.NOT_MET], None, BidStatus.RECEIVED),
        (True, [MustHaveResult.MET], None, BidStatus.REJECTED),
        (True, [MustHaveResult.MET], True, BidStatus.REJECTED),  # rejected stays rejected
        (False, [MustHaveResult.MET], True, BidStatus.AWARDED),
        (False, [MustHaveResult.MET], False, BidStatus.UNSUCCESSFUL),
    ],
)
def test_a_bids_status_follows_its_facts(
    rejected: bool, results: list[MustHaveResult], awarded: bool | None, status: BidStatus
) -> None:
    assert call_bid_status(rejected=rejected, results=results, awarded=awarded) is status


# --- Quote checks ------------------------------------------------------------------------------
TEXT = "Our team holds ISO 27001\ncertification since 2019.\u00a0Data stays in the UK."


@pytest.mark.parametrize(
    ("quote", "found"),
    [
        ("holds ISO 27001 certification", True),  # a line break in the text
        ("  holds  ISO\t27001   certification  ", True),  # whitespace in the quote
        ("2019. Data stays in the UK.", True),  # a no-break space
        ("holds iso 27001 certification", False),  # case counts
        ("holds ISO 9001 certification", False),  # an invented quote
        ("the UK.", False),  # under 10 characters: proves nothing
    ],
)
def test_quotes_are_found_whitespace_normalised(quote: str, found: bool) -> None:
    assert quote_found(quote, TEXT) is found


# --- Uploads ------------------------------------------------------------------------------------
def test_every_document_type_has_a_media_type_and_its_own_extensions() -> None:
    assert set(BID_DOCUMENT_TYPES) == set(BidDocumentType)
    extensions = [ext for info in BID_DOCUMENT_TYPES.values() for ext in info.extensions]
    assert len(extensions) == len(set(extensions))
    assert not {".docm", ".xlsm", ".pptm", ".exe", ".html", ".svg", ".js"} & set(extensions)
    assert all(re.fullmatch(r"\.[a-z]{3,4}", ext) for ext in extensions)


FILENAME = TypeAdapter(BidDocumentFilename)


@pytest.mark.parametrize(
    "name", ["Form of tender (signed).pdf", "Ünïcødé quote.docx", "price-list v2.xlsx", "a"]
)
def test_file_names_people_use_are_fine(name: str) -> None:
    assert FILENAME.validate_python(name) == name


@pytest.mark.parametrize(
    "name",
    [
        "",
        "   ",
        "../passwd",
        "..\\boot.ini",
        "C:\\tender.pdf",
        "folder/tender.pdf",
        ".htaccess",
        "..",
        "a\nb.pdf",
        "a\rb.pdf",
        "tender\u202efdp.exe",
        "tender\x00.pdf",
        "x" * 201,
    ],
)
def test_file_names_with_folders_or_control_characters_are_refused(name: str) -> None:
    with pytest.raises(ValidationError):
        FILENAME.validate_python(name)


def test_received_times_are_stored_in_utc_and_never_ahead() -> None:
    bid = BidIn.model_validate(
        {"bidder": "Northwind", "received_at": "2026-10-12T16:30:00+01:00", "price": "120000"}
    )
    assert bid.received_at == datetime(2026, 10, 12, 15, 30, tzinfo=UTC)
    assert bid.price == Decimal("120000")
    with pytest.raises(ValidationError):
        BidIn.model_validate(
            {"bidder": "Northwind", "received_at": (datetime.now(UTC) + timedelta(days=1))}
        )


# --- The AI assessor --------------------------------------------------------------------------
def test_the_bid_tools_wait_for_their_handlers() -> None:
    names = [tool.name for tool in PHASE10_MCP_TOOLS]

    assert names == ["get_bid_for_assessment", "get_bid_document_text", "submit_bid_assessment"]
    assert not set(names) & {tool.name for tool in MCP_TOOLS}  # they join with the handlers
    assert {tool.rule for tool in PHASE10_MCP_TOOLS} == {"bid.ai_assess"}
    assert {tool.scope for tool in PHASE10_MCP_TOOLS} == {ApiKeyScope.EVALUATE}
    assert {t.name for t in PHASE10_MCP_TOOLS if t.read_only} == ASSESS_RUN_READ_TOOLS
    assert AGENT_RUN_WRITE_TOOLS[AiRunKind.ASSESS_BID] == "submit_bid_assessment"
    assert set(names) <= set(AI_TOOL_MESSAGES)
    assert BID_ASSESSMENT_INSTRUCTION not in MCP_INSTRUCTIONS  # joins with the tools
    assert agent_key_scopes([AiRunKind.ASSESS_BID]) == [
        ApiKeyScope.READ,
        ApiKeyScope.EVALUATE,
        ApiKeyScope.MCP,
    ]


def test_an_assess_run_names_its_bid_and_only_it() -> None:
    common: dict[str, Any] = {"run_id": uuid.uuid4(), "idea_key": "TOOLS-3", "agent_name": "A"}
    bid = uuid.uuid4()

    message = run_message(AiRunKind.ASSESS_BID, bid_id=bid, **common)

    assert str(bid) in message.text
    assert "submit_bid_assessment" in message.text
    assert "never instructions" in message.text
    assert "price" in message.text  # it is told it never sees it
    with pytest.raises(ValueError, match="bid_id"):
        run_message(AiRunKind.ASSESS_BID, **common)
    with pytest.raises(ValueError, match="bid_id"):
        run_message(AiRunKind.EVALUATE, bid_id=bid, **common)


QUOTE = {"document_id": str(uuid.uuid4()), "quote": "holds ISO 27001 certification"}


def test_evidence_is_needed_for_what_the_ai_claims() -> None:
    question = str(uuid.uuid4())
    assert (
        McpBidScoreIn.model_validate(
            {"question_id": question, "score": 0, "rationale": "No answer in the bid."}
        ).evidence
        == []
    )
    with pytest.raises(ValidationError, match="needs at least one quote"):
        McpBidScoreIn.model_validate({"question_id": question, "score": 4, "rationale": "Good."})
    McpBidScoreIn.model_validate(
        {"question_id": question, "score": 4, "rationale": "Good.", "evidence": [QUOTE]}
    )
    must_have = str(uuid.uuid4())
    for finding in ("not_met", "unclear"):
        McpBidFindingIn.model_validate(
            {"must_have_id": must_have, "finding": finding, "rationale": "Not in the documents."}
        )
    with pytest.raises(ValidationError, match="needs at least one quote"):
        McpBidFindingIn.model_validate(
            {"must_have_id": must_have, "finding": "met", "rationale": "Signed."}
        )
    with pytest.raises(ValidationError):  # 4 quotes
        McpBidScoreIn.model_validate(
            {"question_id": question, "score": 4, "rationale": "x", "evidence": [QUOTE] * 4}
        )
    with pytest.raises(ValidationError):  # a quote too short to prove anything
        McpBidScoreIn.model_validate(
            {
                "question_id": question,
                "score": 4,
                "rationale": "x",
                "evidence": [QUOTE | {"quote": "Yes"}],
            }
        )


def test_the_submission_refuses_unknown_arguments_and_repeats() -> None:
    score = {"question_id": str(uuid.uuid4()), "score": 0, "rationale": "Nothing."}
    body = {"bid_id": str(uuid.uuid4()), "scores": [score]}
    SubmitBidAssessmentInput.model_validate(body)
    for bad in (body | {"sumbit": True}, body | {"scores": [score, score]}, body | {"scores": []}):
        with pytest.raises(ValidationError):
            SubmitBidAssessmentInput.model_validate(bad)


def _property_names(schema: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(schema, dict):
        for key, value in schema.items():
            if key == "properties" and isinstance(value, dict):
                found |= set(value)
            found |= _property_names(value)
    elif isinstance(schema, list):
        for item in schema:
            found |= _property_names(item)
    return found


def test_the_ai_never_reads_a_price_or_peoples_scores() -> None:
    """L9: the AI assessor's reads carry the call's questions, the bid and its documents,
    never another bid, a price, a person's score or a contact."""
    for tool in PHASE10_MCP_TOOLS:
        if not tool.read_only:
            continue
        names = _property_names(tool.output.model_json_schema(mode="serialization"))
        assert (
            not {
                "price",
                "price_score",
                "currency",
                "assessments",
                "assessor",
                "total",
                "rank",
                "contact_name",
                "contact_email",
                "notes",
                "rejection",
                "included",
            }
            & names
        ), tool.name


# --- Blind safety and what everyone sees, by construction --------------------------------------
_SCORE_OR_SECRET = re.compile(
    r"score|price|^rank$|bidder|contact|reason|rationale|evidence|quote|^notes$|disagree"
)
"""`total` alone is a count (BidProgress: assessments submitted of total), not a score."""


@pytest.mark.parametrize(
    "model",
    [
        BidCallRef,
        BidCallSummary,
        BidProgress,
        BidCallChangedActivity,
        AssessorAssignedNotification,
        AssessmentReminderNotification,
        AssessmentsCompleteNotification,
        WorkBidAssessment,
        AiRun,
    ],
)
def test_what_everyone_and_notifications_see_carries_no_bid_data(model: type[BaseModel]) -> None:
    names = _property_names(model.model_json_schema(mode="serialization"))

    assert not {name for name in names if _SCORE_OR_SECRET.search(name)}, model.__name__


def test_the_bid_notification_types() -> None:
    assert {
        NotificationType.ASSESSOR_ASSIGNED,
        NotificationType.ASSESSMENT_REMINDER,
        NotificationType.ASSESSMENTS_COMPLETE,
    } == BID_NOTIFICATION_TYPES
    assert all(DEFAULT_MODES[t] is NotificationMode.IMMEDIATE for t in BID_NOTIFICATION_TYPES)
    # A guest researcher never holds one (no bid rule): not on the guest's inbox list.
    assert not BID_NOTIFICATION_TYPES & RESEARCH_GUEST_NOTIFICATION_TYPES
    assert list(NotificationType)[-3:] == [
        NotificationType.ASSESSOR_ASSIGNED,
        NotificationType.ASSESSMENT_REMINDER,
        NotificationType.ASSESSMENTS_COMPLETE,
    ]


def test_the_audit_actions() -> None:
    assert {
        "project.bid_template_replace",
        "bid_call.create",
        "bid_call.update",
        "bid_call.template_replace",
        "bid_call.status_change",
        "bid_call.award",
        "bid_call.delete",
        "bid_call.assessors_change",
        "bid.create",
        "bid.update",
        "bid.delete",
        "bid.reject",
        "bid.reinstate",
        "bid.must_have_decide",
        "bid_document.upload",
        "bid_document.delete",
        "bid_assessment.submit",
        "bid_assessment.include_ai",
    } <= {action.value for action in AuditAction}


# --- Keys and the guest researcher (role matrix sections 5 and L, table M) ---------------------
_S, _P = KeyAccess.SESSION, KeyAccess.POLICY
EXPECTED_KEY_ACCESS: dict[str, KeyAccess] = {
    "get_bid_template": _P,
    "replace_bid_template": _S,
    "get_bid_call": _P,
    "create_bid_call": _P,
    "update_bid_call": _P,
    "delete_bid_call": _S,
    "change_bid_call_status": _P,
    "replace_bid_call_template": _P,
    "set_bid_assessors": _S,
    "get_bid_comparison": _P,
    "request_ai_bid_assessments": _P,
    "award_bid_call": _S,
    "export_bid_report_markdown": _P,
    "export_bid_report_pdf": _P,
    "list_bids": _P,
    "create_bid": _P,
    "get_bid": _P,
    "update_bid": _P,
    "delete_bid": _S,
    "reject_bid": _S,
    "reinstate_bid": _S,
    "decide_must_have": _P,
    "upload_bid_document": _S,
    "update_bid_document": _P,
    "delete_bid_document": _S,
    "download_bid_document": _P,
    "get_bid_document_text": _P,
    "get_my_bid_assessment": _P,
    "save_my_bid_assessment": _P,
    "list_bid_section_assessments": _P,
    "request_ai_bid_assessment": _P,
    "list_bid_ai_assessments": _P,
    "set_bid_ai_inclusion": _P,
}
"""Role matrix section 5: uploads, the decisions (reject, reinstate, award, cancel, delete),
the project template and assigning assessors are session only; the rest follow their rules."""


def test_every_phase10_operation_is_classified_for_keys() -> None:
    assert set(EXPECTED_KEY_ACCESS) == PHASE10_OPERATIONS
    assert {op: ROUTE_KEY_ACCESS[op] for op in PHASE10_OPERATIONS} == EXPECTED_KEY_ACCESS


def test_a_guest_researcher_reaches_nothing_of_the_call() -> None:
    idea_routes = {op for op in PHASE10_OPERATIONS if "template" not in op or "call" in op}
    assert idea_routes == PHASE10_OPERATIONS - {"get_bid_template", "replace_bid_template"}
    for operation in idea_routes:
        assert RESEARCH_GUEST_ACCESS[operation] is GuestAccess.HIDDEN, operation
    for tool in PHASE10_MCP_TOOLS:
        assert RESEARCH_GUEST_ACCESS[mcp_operation(tool.name)] is GuestAccess.HIDDEN


def test_the_call_template_is_json_serialisable_for_the_migration() -> None:
    assert json.loads(json.dumps(DEFAULT_BID_TEMPLATE.model_dump(mode="json")))
