"""Phase 10 tables and columns (migration 0016): calls for bids and their template copies,
bids, must-have results, documents, section assessors and assessments, the AI assessor and
its runs, the three notification types; what the upgrade writes (every project's template,
"off" for people who had every type off) and what the downgrade removes.
tests/test_domain_schema.py runs the full up/down/up and compares the migrated schema with
the models."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import uuid
from collections.abc import Mapping
from typing import Any

import psycopg
import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.migrate import MIGRATIONS_DIR, alembic_config
from app.models.ai import AI_PURPOSES_DISTINCT_SQL
from app.models.bid import (
    BID_DOCUMENT_MAX_BYTES,
    BID_EVIDENCE_MAX,
    BID_REASON_MAX_LENGTH,
    BID_SCALE_POINTS,
    BID_SCORE_MAX,
    BID_TEXT_MAX_CHARS,
)
from app.models.enums import (
    AiMustHaveFinding,
    AiRunKind,
    BidCallStatus,
    BidDocumentType,
    BidQuestionType,
    BidStatus,
    EmailType,
    EvaluationStatus,
    ExtractionError,
    ExtractionState,
    MustHaveKind,
    MustHaveResult,
    NotificationType,
)
from app.schemas.activity import PHASE10_ACTIVITY_TYPES
from app.schemas.bids import DEFAULT_BID_TEMPLATE
from tests.conftest import make_settings
from tests.test_domain_schema import (  # noqa: F401 - scratch_database_url is a fixture
    _dsn,
    _idea_and_user,
    scratch_database_url,
)

NEW_TYPES = ("assessor_assigned", "assessment_reminder", "assessments_complete")
LATER_TYPES = ("submitter_replied", "submission_link", "submission_message")
"""Phase 11's (migration 0017): not there at 0016."""
AT_0016 = tuple(t.value for t in NotificationType if t.value not in LATER_TYPES)
EARLIER_TYPES = tuple(t for t in AT_0016 if t not in NEW_TYPES)
EMAIL_AT_0016 = tuple(t.value for t in EmailType if t.value not in LATER_TYPES)
SCALE = "{Nothing,Poor,Weak,Fair,Good,Excellent}"


def _migration() -> Any:
    path = MIGRATIONS_DIR / "versions" / "20261013_0016_bid_evaluation.py"
    spec = importlib.util.spec_from_file_location("migration_0016", path)
    assert spec is not None
    assert spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_enum_values_are_the_migrations() -> None:
    """The migration spells the values out, in the enums' order (the CHECKs list them so)."""
    m = _migration()

    assert tuple(BidCallStatus) == m.CALL_STATUSES
    assert tuple(BidStatus) == m.BID_STATUSES
    assert tuple(BidQuestionType) == m.QUESTION_TYPES
    assert tuple(MustHaveKind) == m.MUST_HAVE_KINDS
    assert tuple(MustHaveResult) == m.MUST_HAVE_RESULTS
    assert tuple(AiMustHaveFinding) == m.AI_FINDINGS
    assert tuple(BidDocumentType) == m.DOCUMENT_TYPES
    assert tuple(ExtractionState) == m.EXTRACTION_STATES
    assert tuple(ExtractionError) == m.EXTRACTION_ERRORS
    assert tuple(EvaluationStatus) == m.ASSESSMENT_STATUSES
    assert tuple(AiRunKind) == m.KINDS
    assert AT_0016 == m.NOTIFICATION_TYPES
    assert m.NOTIFICATION_TYPES_BEFORE == EARLIER_TYPES
    assert m.NEW_TYPES == NEW_TYPES
    assert EMAIL_AT_0016 == m.EMAIL_TYPES
    assert tuple(t for t in EMAIL_AT_0016 if t not in NEW_TYPES) == m.EMAIL_TYPES_BEFORE
    assert m.NEW_ACTIVITY_TYPES == PHASE10_ACTIVITY_TYPES
    assert m.PURPOSES_DISTINCT == AI_PURPOSES_DISTINCT_SQL
    assert (m.DOCUMENT_MAX_BYTES, m.TEXT_MAX_CHARS, m.SCALE_POINTS) == (
        BID_DOCUMENT_MAX_BYTES,
        BID_TEXT_MAX_CHARS,
        BID_SCALE_POINTS,
    )
    assert (m.EVIDENCE_MAX, m.SCORE_MAX, m.REASON_MAX) == (
        BID_EVIDENCE_MAX,
        BID_SCORE_MAX,
        BID_REASON_MAX_LENGTH,
    )
    assert json.loads(json.dumps(m.DEFAULT_TEMPLATE)) == DEFAULT_BID_TEMPLATE.model_dump(
        mode="json"
    )
    assert max(len(t) for t in NEW_TYPES) <= 20  # notifications.type is varchar(20)


async def _fails(session: AsyncSession, sql: str, values: Mapping[str, object], name: str) -> None:
    with pytest.raises(IntegrityError, match=name):
        async with session.begin_nested():
            await session.execute(text(sql), values)


async def _call(
    session: AsyncSession, idea_id: uuid.UUID, user_id: uuid.UUID, status: str = "open"
) -> dict[str, uuid.UUID]:
    """A call with one section of one score question and a price question, one must-have,
    one bid and its assessor; returns the ids."""
    ids = {name: uuid.uuid4() for name in ("call", "section", "q", "price", "must", "bid")}
    statements = (
        "INSERT INTO bid_calls (id, idea_id, title, status, scale, deadline_at, created_by_id)"
        " VALUES (:call, :idea, 'Call', :status, CAST(:scale AS varchar[]), now(), :user)",
        "INSERT INTO bid_call_sections (id, call_id, position, title, weight)"
        " VALUES (:section, :call, 0, 'Commercial', 100)",
        "INSERT INTO bid_call_questions (id, call_id, section_id, position, text, type, weight)"
        " VALUES (:q, :call, :section, 0, 'Value?', 'score', 1),"
        " (:price, :call, :section, 1, 'Price', 'price', 3)",
        "INSERT INTO bid_call_must_haves (id, call_id, position, text, kind)"
        " VALUES (:must, :call, 0, 'Insurance certificate', 'document')",
        "INSERT INTO bid_section_assessors (section_id, user_id, call_id)"
        " VALUES (:section, :user, :call)",
        "INSERT INTO bids (id, call_id, bidder, price) VALUES (:bid, :call, 'Northwind', 96000)",
        "INSERT INTO bid_must_have_results (bid_id, must_have_id, call_id, result)"
        " VALUES (:bid, :must, :call, 'missing')",
    )
    for statement in statements:
        await session.execute(
            text(statement),
            {**ids, "idea": idea_id, "user": user_id, "status": status, "scale": SCALE},
        )
    return ids


async def test_a_call_and_its_template_copy(db_session: AsyncSession) -> None:
    idea_id, user_id = await _idea_and_user(db_session)
    ids = await _call(db_session, idea_id, user_id)
    insert_call = (
        "INSERT INTO bid_calls (id, idea_id, title, status, currency, scale, deadline_at)"
        " VALUES (:id, :idea, 'Call', :status, :currency, CAST(:scale AS varchar[]), :deadline)"
    )
    call: dict[str, object] = {
        "id": uuid.uuid4(),
        "idea": idea_id,
        "status": "draft",
        "currency": "GBP",
        "scale": SCALE,
        "deadline": None,
    }

    await _fails(db_session, insert_call, call, "uq_bid_calls_idea_id")  # one per idea
    other_idea, _ = await _idea_and_user_in(db_session, idea_id)
    call["idea"] = other_idea
    await _fails(db_session, insert_call, call | {"status": "open"}, "deadline_when_open")
    await _fails(db_session, insert_call, call | {"currency": "gbp"}, "currency_format")
    await _fails(db_session, insert_call, call | {"scale": "{a,b,c,d,e}"}, "scale_points")
    await _fails(db_session, insert_call, call | {"scale": "{a,b,c,d,e,NULL}"}, "scale_points")
    await _fails(db_session, insert_call, call | {"status": "awarded"}, "awarded_iff_at")
    async with db_session.begin_nested():
        await db_session.execute(text(insert_call), call)  # a draft needs no deadline

    section = (
        "INSERT INTO bid_call_sections (id, call_id, position, title, weight)"
        " VALUES (:id, :call, 1, :title, :weight)"
    )
    values = {"id": uuid.uuid4(), "call": ids["call"], "title": "Delivery", "weight": 20}
    await _fails(db_session, section, values | {"weight": 0}, "weight_range")
    await _fails(db_session, section, values | {"title": "COMMERCIAL"}, "title_lower")

    question = (
        "INSERT INTO bid_call_questions (id, call_id, section_id, position, text, type, weight)"
        " VALUES (:id, :call, :section, 2, 'Q', :type, :weight)"
    )
    values = {"id": uuid.uuid4(), "call": ids["call"], "section": ids["section"]}
    await _fails(db_session, question, values | {"type": "comment", "weight": 1}, "comment_iff")
    await _fails(db_session, question, values | {"type": "score", "weight": 0}, "comment_iff")
    await _fails(db_session, question, values | {"type": "price", "weight": 1}, "_price")
    await _fails(
        db_session,
        "INSERT INTO bid_call_must_haves (id, call_id, position, text, kind)"
        " VALUES (:id, :call, 1, 'insurance CERTIFICATE', 'confirmation')",
        {"id": uuid.uuid4(), "call": ids["call"]},
        "text_lower",
    )
    await _fails(
        db_session,
        "INSERT INTO bid_call_must_haves (id, call_id, position, text, kind, pricing)"
        " VALUES (:id, :call, 1, 'Prices', 'confirmation', true)",
        {"id": uuid.uuid4(), "call": ids["call"]},
        "pricing_is_document",
    )
    await db_session.rollback()


async def test_no_row_mixes_two_calls(db_session: AsyncSession) -> None:
    """Review S7: every row naming two of a call's rows carries the call in a composite
    foreign key; a question, assessor, result, document, assessment or AI run that pairs
    rows of two calls (or a run on another idea than its bid's call) is refused."""
    idea_id, user_id = await _idea_and_user(db_session)
    first = await _call(db_session, idea_id, user_id)
    other_idea, _ = await _idea_and_user_in(db_session, idea_id)
    second = await _call(db_session, other_idea, user_id)
    agent = await _agent(db_session)
    mixed = {"call": first["call"], "user": user_id}
    stranger = uuid.uuid4()
    await db_session.execute(
        text("INSERT INTO users (id, email, display_name) VALUES (:u, :email, 'Stranger')"),
        {"u": stranger, "email": f"{stranger.hex}@example.com"},
    )

    await _fails(
        db_session,
        "INSERT INTO bid_call_questions (id, call_id, section_id, position, text, type, weight)"
        " VALUES (:id, :call, :section, 5, 'Q', 'score', 1)",
        mixed | {"id": uuid.uuid4(), "section": second["section"]},
        "fk_bid_call_questions_section_id",
    )
    await _fails(
        db_session,
        "INSERT INTO bid_section_assessors (section_id, user_id, call_id)"
        " VALUES (:section, :user, :call)",
        mixed | {"section": second["section"], "user": stranger},
        "fk_bid_section_assessors_section_id",
    )
    await _fails(
        db_session,
        "INSERT INTO bid_must_have_results (bid_id, must_have_id, call_id, result)"
        " VALUES (:bid, :must, :call, 'missing')",
        mixed | {"bid": first["bid"], "must": second["must"]},
        "fk_bid_must_have_results_must_have_id",
    )
    document = (
        "INSERT INTO bid_documents (id, bid_id, call_id, must_have_id, filename, type,"
        " content_type, size_bytes, sha256) VALUES (:id, :bid, :call, :must, 'a.pdf', 'pdf',"
        " 'application/pdf', 1, :sha)"
    )
    values = mixed | {"id": uuid.uuid4(), "sha": _sha(b"x"), "must": None}
    await _fails(
        db_session, document, values | {"bid": second["bid"]}, "fk_bid_documents_bid_id_bids"
    )
    await _fails(
        db_session,
        document,
        values | {"bid": first["bid"], "must": second["must"]},
        "fk_bid_documents_must_have_id",
    )
    await _fails(
        db_session,
        "INSERT INTO bid_assessments (id, bid_id, section_id, assessor_id, call_id)"
        " VALUES (:id, :bid, :section, :user, :call)",
        mixed | {"id": uuid.uuid4(), "bid": second["bid"], "section": first["section"]},
        "fk_bid_assessments_bid_id_bids",
    )
    await _fails(
        db_session,
        "INSERT INTO bid_assessments (id, bid_id, section_id, assessor_id, call_id)"
        " VALUES (:id, :bid, :section, :user, :call)",
        mixed | {"id": uuid.uuid4(), "bid": first["bid"], "section": second["section"]},
        "fk_bid_assessments_section_id_assessor_id",
    )
    run = (
        "INSERT INTO ai_runs (id, idea_id, agent_id, kind, timeout_seconds, bid_id, bid_call_id)"
        " VALUES (:id, :idea, :agent, 'assess_bid', 300, :bid, :bid_call)"
    )
    values = {"id": uuid.uuid4(), "agent": agent, "bid": first["bid"]}
    await _fails(
        db_session,
        run,
        values | {"idea": idea_id, "bid_call": second["call"]},
        "fk_ai_runs_bid_id_bids",
    )
    await _fails(
        db_session,
        run,
        values | {"idea": other_idea, "bid_call": first["call"]},
        "fk_ai_runs_bid_call_id_bid_calls",
    )
    async with db_session.begin_nested():
        await db_session.execute(text(run), values | {"idea": idea_id, "bid_call": first["call"]})
    await db_session.rollback()


async def _idea_and_user_in(
    session: AsyncSession, idea_id: uuid.UUID
) -> tuple[uuid.UUID, uuid.UUID]:
    """A second idea in the same project."""
    other = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO ideas (id, project_id, number, title)"
            " SELECT :o, project_id, 2, 'Other' FROM ideas WHERE id = :i"
        ),
        {"o": other, "i": idea_id},
    )
    return other, idea_id


async def test_bids_are_rejected_with_a_reason_and_one_is_awarded(
    db_session: AsyncSession,
) -> None:
    idea_id, user_id = await _idea_and_user(db_session)
    ids = await _call(db_session, idea_id, user_id)
    insert = (
        "INSERT INTO bids (id, call_id, bidder, price, status, rejected_at, rejection_reason)"
        " VALUES (:id, :call, 'Quillfield', :price, :status, :at, :reason)"
    )
    bid: dict[str, object] = {
        "id": uuid.uuid4(),
        "call": ids["call"],
        "price": 80000,
        "status": "received",
        "at": None,
        "reason": None,
    }

    await _fails(db_session, insert, bid | {"price": 0}, "price_positive")
    await _fails(db_session, insert, bid | {"status": "rejected"}, "rejected_has_rejection")
    rejected = {"status": "rejected", "at": "2026-10-12T10:00:00Z"}
    await _fails(db_session, insert, bid | rejected, "rejection_reason_iff_at")
    await _fails(db_session, insert, bid | rejected | {"reason": ""}, "rejection_reason_length")
    async with db_session.begin_nested():
        await db_session.execute(text(insert), bid | rejected | {"reason": "No insurance."})
    # Reinstating keeps the last rejection on record (review: the reason isn't lost).
    reinstate = "UPDATE bids SET status = :status, reinstated_at = now() WHERE id = :id"
    await _fails(
        db_session,
        reinstate,
        {"status": "rejected", "id": bid["id"]},
        "rejected_has_rejection|reinstated_after_rejection",
    )
    async with db_session.begin_nested():
        await db_session.execute(text(reinstate), {"status": "received", "id": bid["id"]})
    await _fails(
        db_session,
        "UPDATE bids SET reinstated_at = now() WHERE id = :id",
        {"id": ids["bid"]},
        "reinstated_after_rejection",
    )

    await db_session.execute(
        text("UPDATE bids SET status = 'awarded' WHERE id = :b"), {"b": ids["bid"]}
    )
    await _fails(
        db_session,
        "INSERT INTO bids (id, call_id, bidder, status) VALUES (:id, :call, 'B', 'awarded')",
        {"id": uuid.uuid4(), "call": ids["call"]},
        "uq_bids_call_id_awarded",
    )

    # A person decides met or not met; "missing" and "unchecked" are facts, not decisions.
    update = (
        "UPDATE bid_must_have_results SET result = :result, decided_at = now() WHERE bid_id = :bid"
    )
    await _fails(db_session, update, {"result": "missing", "bid": ids["bid"]}, "decision_is")
    await db_session.execute(text(update), {"result": "not_met", "bid": ids["bid"]})
    await db_session.rollback()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def test_documents_their_bytes_and_text(db_session: AsyncSession) -> None:
    idea_id, user_id = await _idea_and_user(db_session)
    ids = await _call(db_session, idea_id, user_id)
    insert = (
        "INSERT INTO bid_documents (id, bid_id, call_id, must_have_id, filename, type,"
        " content_type, size_bytes, sha256, extraction_state, extraction_error, extracted_at,"
        " text_chars) VALUES (:id, :bid, :call, :must, 'Insurance.pdf', 'pdf',"
        " 'application/pdf', :size, :sha, :state, :error, :at, :chars)"
    )
    document: dict[str, object] = {
        "id": uuid.uuid4(),
        "bid": ids["bid"],
        "call": ids["call"],
        "must": ids["must"],
        "size": 9,
        "sha": _sha(b"%PDF-1.7\n"),
        "state": "pending",
        "error": None,
        "at": None,
        "chars": None,
    }
    now = "2026-10-12T10:00:00Z"

    await _fails(db_session, insert, document | {"size": 0}, "size_bytes_range")
    big = BID_DOCUMENT_MAX_BYTES + 1
    await _fails(db_session, insert, document | {"size": big}, "size_bytes_range")
    await _fails(db_session, insert, document | {"sha": "ABC"}, "sha256_format")
    await _fails(db_session, insert, document | {"state": "failed", "at": now}, "error_iff")
    await _fails(db_session, insert, document | {"state": "done"}, "extracted_iff_done")
    await _fails(db_session, insert, document | {"state": "done", "at": now}, "text_iff_done")
    await _fails(
        db_session, insert, document | {"state": "no_text", "at": now, "chars": 0}, "text_iff"
    )
    await db_session.execute(text(insert), document)
    await db_session.execute(
        text("INSERT INTO bid_document_contents (document_id, data) VALUES (:d, :data)"),
        {"d": document["id"], "data": b"%PDF-1.7\n"},
    )
    await db_session.execute(
        text("INSERT INTO bid_document_texts (document_id, text) VALUES (:d, 'Insured.')"),
        {"d": document["id"]},
    )
    # The same file twice on one bid is one document.
    await _fails(
        db_session, insert, document | {"id": uuid.uuid4()}, "uq_bid_documents_bid_id_sha256"
    )

    # A must-have removed from the template leaves the file, unlinked: the service unlinks
    # it first (the composite key is NO ACTION, review S7).
    await _fails(
        db_session,
        "DELETE FROM bid_call_must_haves WHERE id = :must",
        ids,
        "fk_bid_documents_must_have_id",
    )
    await db_session.execute(
        text("UPDATE bid_documents SET must_have_id = NULL WHERE must_have_id = :must"), ids
    )
    await db_session.execute(text("DELETE FROM bid_call_must_haves WHERE id = :must"), ids)
    link = await db_session.scalar(
        text("SELECT must_have_id FROM bid_documents WHERE id = :d"), {"d": document["id"]}
    )
    assert link is None
    storage = await db_session.scalar(
        text(
            "SELECT attstorage FROM pg_attribute WHERE attrelid = 'bid_document_contents'::regclass"
            " AND attname = 'data'"
        )
    )
    assert storage == "e"  # EXTERNAL: range reads without decompressing
    # A deleted bid takes its documents, their bytes and their text with it.
    await db_session.execute(text("DELETE FROM bids WHERE id = :bid"), ids)
    left = await db_session.scalar(
        text(
            "SELECT (SELECT count(*) FROM bid_documents) + (SELECT count(*) FROM"
            " bid_document_contents) + (SELECT count(*) FROM bid_document_texts)"
        )
    )
    assert left == 0
    await db_session.rollback()


async def test_assessments_belong_to_a_section_assessor(db_session: AsyncSession) -> None:
    idea_id, user_id = await _idea_and_user(db_session)
    ids = await _call(db_session, idea_id, user_id)
    insert = (
        "INSERT INTO bid_assessments (id, bid_id, section_id, assessor_id, call_id, status,"
        " submitted_at) VALUES (:id, :bid, :section, :assessor, :call, :status, :at)"
    )
    assessment: dict[str, object] = {
        "id": uuid.uuid4(),
        "bid": ids["bid"],
        "section": ids["section"],
        "assessor": user_id,
        "call": ids["call"],
        "status": "draft",
        "at": None,
    }

    stranger = {"assessor": uuid.uuid4()}
    await _fails(db_session, insert, assessment | stranger, "fk_bid_assessments_section_id")
    await _fails(db_session, insert, assessment | {"status": "submitted"}, "submitted_has_at")
    await db_session.execute(text(insert), assessment)
    await _fails(db_session, insert, assessment | {"id": uuid.uuid4()}, "uq_bid_assessments")
    answer = (
        "INSERT INTO bid_assessment_answers (assessment_id, question_id, score)"
        " VALUES (:a, :q, :score)"
    )
    values = {"a": assessment["id"], "q": ids["q"]}
    await _fails(db_session, answer, values | {"score": BID_SCORE_MAX + 1}, "score_range")
    await _fails(db_session, answer, values | {"score": -1}, "score_range")
    await db_session.execute(text(answer), values | {"score": 4})

    # Removing someone as the section's assessor deletes their assessments of it (the
    # service only does so for drafts: 409 assessor_has_submitted otherwise).
    await db_session.execute(
        text("DELETE FROM bid_section_assessors WHERE section_id = :s AND user_id = :u"),
        {"s": ids["section"], "u": user_id},
    )
    left = await db_session.scalar(
        text("SELECT (SELECT count(*) FROM bid_assessments) + (SELECT count(*) FROM"
             " bid_assessment_answers)")
    )  # fmt: skip
    assert left == 0
    await db_session.rollback()


async def _agent(session: AsyncSession, purposes: str = "{assess_bid}") -> uuid.UUID:
    account, agent = uuid.uuid4(), uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO users (id, email, display_name, is_service_account)"
            " VALUES (:a, :email, 'Bid assessor', true)"
        ),
        {"a": account, "email": f"{account.hex}@soundings.invalid"},
    )
    await session.execute(
        text(
            "INSERT INTO ai_agents (id, display_name, namespace, name, protocol, purposes,"
            " service_account_id) VALUES (:id, 'Bid assessor', 'soundings', :name,"
            " 'kagent_v0_10', CAST(:purposes AS varchar[]), :a)"
        ),
        {"id": agent, "name": f"bid-{agent.hex[:8]}", "purposes": purposes, "a": account},
    )
    return agent


async def test_the_ai_assessor_and_its_runs(db_session: AsyncSession) -> None:
    idea_id, user_id = await _idea_and_user(db_session)
    ids = await _call(db_session, idea_id, user_id)
    agent = await _agent(db_session)
    await _fails(
        db_session,
        "UPDATE ai_agents SET purposes = '{assess_bid,evaluate,assess_bid}' WHERE id = :a",
        {"a": agent},
        "ck_ai_agents_purposes",
    )
    await db_session.execute(
        text(
            "UPDATE ai_agents SET purposes = '{evaluate,research,draft_section,assess_bid}'"
            " WHERE id = :a"
        ),
        {"a": agent},
    )

    run = (
        "INSERT INTO ai_runs (id, idea_id, agent_id, kind, timeout_seconds, bid_id, bid_call_id,"
        " automatic, requested_by_id) VALUES (:id, :idea, :agent, :kind, 300, :bid, :call,"
        " :automatic, :by)"
    )
    values: dict[str, object] = {
        "id": uuid.uuid4(),
        "idea": idea_id,
        "agent": agent,
        "kind": "assess_bid",
        "bid": ids["bid"],
        "call": ids["call"],
        "automatic": False,
        "by": user_id,
    }
    await _fails(db_session, run, values | {"bid": None}, "ck_ai_runs_bid_iff_assess")
    await _fails(db_session, run, values | {"call": None}, "ck_ai_runs_bid_iff_assess")
    await _fails(db_session, run, values | {"kind": "evaluate"}, "ck_ai_runs_bid_iff_assess")
    # Automatic runs are the call's AI assessor's: assess runs that nobody requested.
    await _fails(db_session, run, values | {"automatic": True}, "ck_ai_runs_automatic_assess")
    await db_session.execute(text(run), values)
    # One active run per bid; another bid of the same call may run beside it.
    await _fails(db_session, run, values | {"id": uuid.uuid4()}, "uq_ai_runs_active")
    other_bid = uuid.uuid4()
    await db_session.execute(
        text("INSERT INTO bids (id, call_id, bidder) VALUES (:b, :c, 'Tessellate')"),
        {"b": other_bid, "c": ids["call"]},
    )
    await db_session.execute(text(run), values | {"id": uuid.uuid4(), "bid": other_bid})

    assessment = uuid.uuid4()
    await db_session.execute(
        text("INSERT INTO bid_ai_assessments (id, bid_id, agent_id) VALUES (:id, :b, :a)"),
        {"id": assessment, "b": ids["bid"], "a": agent},
    )
    await db_session.execute(
        text("UPDATE ai_runs SET bid_ai_assessment_id = :x WHERE id = :r"),
        {"x": assessment, "r": values["id"]},
    )
    score = (
        "INSERT INTO bid_ai_scores (ai_assessment_id, question_id, score, rationale, evidence)"
        " VALUES (:x, :q, 4, 'Clear plan.', CAST(:evidence AS jsonb))"
    )
    quote = {"document_id": str(uuid.uuid4()), "quote": "We hold ISO 27001."}
    too_many = json.dumps([quote] * (BID_EVIDENCE_MAX + 1))
    await _fails(db_session, score, {"x": assessment, "q": ids["q"], "evidence": too_many}, "ev")
    an_object = json.dumps(quote)
    await _fails(db_session, score, {"x": assessment, "q": ids["q"], "evidence": an_object}, "ev")
    await db_session.execute(
        text(score), {"x": assessment, "q": ids["q"], "evidence": json.dumps([quote])}
    )
    await _fails(
        db_session,
        "INSERT INTO bid_ai_findings (ai_assessment_id, must_have_id, finding, rationale)"
        " VALUES (:x, :m, 'maybe', 'Unsure.')",
        {"x": assessment, "m": ids["must"]},
        "ck_bid_ai_findings_finding",
    )
    # An evaluate run can't carry a bid assessment.
    await _fails(
        db_session,
        "INSERT INTO ai_runs (id, idea_id, agent_id, kind, timeout_seconds,"
        " bid_ai_assessment_id) VALUES (:id, :idea, :agent, 'evaluate', 300, :x)",
        {"id": uuid.uuid4(), "idea": idea_id, "agent": agent, "x": assessment},
        "result_matches_kind",
    )

    # Deleting the bid deletes its runs and AI assessments.
    await db_session.execute(text("DELETE FROM bids WHERE id = :bid"), ids)
    left = await db_session.scalar(
        text(
            "SELECT (SELECT count(*) FROM ai_runs WHERE bid_id = :b)"
            " + (SELECT count(*) FROM bid_ai_assessments) + (SELECT count(*) FROM bid_ai_scores)"
        ),
        {"b": ids["bid"]},
    )
    assert left == 0
    await db_session.rollback()


async def test_the_bid_notification_types_are_stored(db_session: AsyncSession) -> None:
    idea_id, user_id = await _idea_and_user(db_session)
    for new_type in NEW_TYPES:
        email_id = uuid.uuid4()
        await db_session.execute(
            text(
                "INSERT INTO outbound_email (id, type, recipient_user_id, message_id)"
                " VALUES (:id, :type, :u, :m)"
            ),
            {"id": email_id, "type": new_type, "u": user_id, "m": f"{email_id}@x"},
        )
        await db_session.execute(
            text(
                "INSERT INTO notifications (id, user_id, type, idea_id, dedupe_key, email_mode,"
                " email_id) VALUES (:id, :u, :type, :i, :key, 'immediate', :e)"
            ),
            {
                "id": uuid.uuid4(),
                "u": user_id,
                "type": new_type,
                "i": idea_id,
                "key": f"{new_type}:x",
                "e": email_id,
            },
        )
        await db_session.execute(
            text(
                "INSERT INTO notification_preferences (user_id, type, mode)"
                " VALUES (:u, :type, 'digest')"
            ),
            {"u": user_id, "type": new_type},
        )
    await db_session.rollback()


# --- The migration on data -------------------------------------------------------------------
def _people(connection: psycopg.Connection[Any]) -> dict[str, uuid.UUID]:
    people = {name: uuid.uuid4() for name in ("all_off", "some_off")}
    for name, user_id in people.items():
        connection.execute(
            "INSERT INTO users (id, email, display_name) VALUES (%s, %s, %s)",
            (user_id, f"{name}@example.com", name),
        )
    for type_ in EARLIER_TYPES:  # "Unsubscribe from all email" turned every type off
        connection.execute(
            "INSERT INTO notification_preferences (user_id, type, mode) VALUES (%s, %s, 'off')",
            (people["all_off"], type_),
        )
    for type_ in EARLIER_TYPES[:-1]:
        connection.execute(
            "INSERT INTO notification_preferences (user_id, type, mode) VALUES (%s, %s, 'off')",
            (people["some_off"], type_),
        )
    return people


def test_0016_gives_every_project_the_default_template(scratch_database_url: str) -> None:  # noqa: F811
    """Every project gets the built-in template; someone with every earlier type off gets
    the three bid types off too, everyone else the defaults (immediate: no rows)."""
    config = alembic_config(make_settings(database_url=scratch_database_url).sqlalchemy_url)
    command.upgrade(config, "0015")
    projects = [uuid.uuid4(), uuid.uuid4()]
    with psycopg.connect(_dsn(scratch_database_url)) as connection:
        for number, project in enumerate(projects):
            connection.execute(
                "INSERT INTO projects (id, slug, key, name) VALUES (%s, %s, %s, 'P')",
                (project, f"p{number}", f"P{number}"),
            )
        people = _people(connection)

    command.upgrade(config, "head")
    with psycopg.connect(_dsn(scratch_database_url)) as connection:
        templates = connection.execute(
            "SELECT project_id, template FROM bid_templates ORDER BY project_id"
        ).fetchall()
        rows = connection.execute(
            "SELECT user_id, type, mode FROM notification_preferences WHERE type = ANY(%s)"
            " ORDER BY type",
            (list(NEW_TYPES),),
        ).fetchall()

    default = DEFAULT_BID_TEMPLATE.model_dump(mode="json")
    assert templates == [(project, default) for project in sorted(projects)]
    assert rows == [(people["all_off"], t, "off") for t in sorted(NEW_TYPES)]


def test_0016_downgrade_removes_bid_evaluation(scratch_database_url: str) -> None:  # noqa: F811
    """Below 0016: no call, bid, document or assessment; no assess run, bid notification or
    bid_call_changed event; an agent that only assessed bids is disabled with its key
    revoked (older code needs a purpose: research), others just lose the purpose. Everything
    else stays, and upgrading again matches the models."""
    config = alembic_config(make_settings(database_url=scratch_database_url).sqlalchemy_url)
    command.upgrade(config, "head")
    project, idea, user, call, bid = (uuid.uuid4() for _ in range(5))
    accounts = {name: uuid.uuid4() for name in ("only", "both")}
    agents = {name: uuid.uuid4() for name in accounts}
    with psycopg.connect(_dsn(scratch_database_url)) as connection:
        connection.execute(
            "INSERT INTO users (id, email, display_name) VALUES (%s, 'bob@example.com', 'Bob')",
            (user,),
        )
        connection.execute(
            "INSERT INTO projects (id, slug, key, name) VALUES (%s, 'tools', 'TOOLS', 'Tools')",
            (project,),
        )
        connection.execute(
            "INSERT INTO ideas (id, project_id, number, title) VALUES (%s, %s, 3, 'Idea')",
            (idea, project),
        )
        connection.execute(
            "INSERT INTO bid_calls (id, idea_id, title, scale) VALUES (%s, %s, 'Call', %s)",
            (call, idea, SCALE),
        )
        connection.execute(
            "INSERT INTO bids (id, call_id, bidder) VALUES (%s, %s, 'Northwind')", (bid, call)
        )
        for name, purposes in (("only", "{assess_bid}"), ("both", "{evaluate,assess_bid}")):
            connection.execute(
                "INSERT INTO users (id, email, display_name, is_service_account)"
                " VALUES (%s, %s, 'Agent', true)",
                (accounts[name], f"{name}@soundings.invalid"),
            )
            connection.execute(
                "INSERT INTO ai_agents (id, display_name, namespace, name, protocol, purposes,"
                " service_account_id) VALUES (%s, 'Agent', 'soundings', %s, 'kagent_v0_10',"
                " %s, %s)",
                (agents[name], name, purposes, accounts[name]),
            )
            connection.execute(
                "INSERT INTO api_keys (id, user_id, name, lookup_id, secret_hash, scopes,"
                " created_auth_method) VALUES (%s, %s, 'Key', %s, %s, '{read,evaluate,mcp}',"
                " 'sso')",
                (uuid.uuid4(), accounts[name], f"{name}Key0000001"[:12], "0" * 64),
            )
        for kind, bid_id, call_id in (("assess_bid", bid, call), ("evaluate", None, None)):
            connection.execute(
                "INSERT INTO ai_runs (id, idea_id, agent_id, kind, timeout_seconds, bid_id,"
                " bid_call_id) VALUES (%s, %s, %s, %s, 300, %s, %s)",
                (uuid.uuid4(), idea, agents["both"], kind, bid_id, call_id),
            )
        for type_ in (*NEW_TYPES, "owner_assigned"):
            email = uuid.uuid4()
            connection.execute(
                "INSERT INTO outbound_email (id, type, recipient_user_id, message_id)"
                " VALUES (%s, %s, %s, %s)",
                (email, type_, user, f"{email}@x"),
            )
            connection.execute(
                "INSERT INTO notifications (id, user_id, type, idea_id, dedupe_key,"
                " email_mode, email_id) VALUES (%s, %s, %s, %s, %s, 'immediate', %s)",
                (uuid.uuid4(), user, type_, idea, f"{type_}:1", email),
            )
            connection.execute(
                "INSERT INTO notification_preferences (user_id, type, mode)"
                " VALUES (%s, %s, 'digest')",
                (user, type_),
            )
        for type_ in (*PHASE10_ACTIVITY_TYPES, "owner_changed"):
            connection.execute(
                "INSERT INTO activity_events (id, project_id, idea_id, type) VALUES"
                " (%s, %s, %s, %s)",
                (uuid.uuid4(), project, idea, type_),
            )

    command.downgrade(config, "0015")
    with psycopg.connect(_dsn(scratch_database_url)) as connection:
        tables = connection.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = current_schema()"
            " AND tablename LIKE 'bid%%'"
        ).fetchall()
        columns = connection.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'ai_runs'"
            " AND column_name LIKE 'bid%%'"
        ).fetchall()
        runs = connection.execute("SELECT kind FROM ai_runs").fetchall()
        agent_rows = connection.execute(
            "SELECT a.name, a.purposes, a.enabled, k.revoked_at IS NOT NULL FROM ai_agents a"
            " JOIN api_keys k ON k.user_id = a.service_account_id ORDER BY a.name"
        ).fetchall()
        kept = {
            table: connection.execute(f"SELECT type FROM {table} ORDER BY type").fetchall()  # noqa: S608
            for table in (
                "outbound_email",
                "notifications",
                "notification_preferences",
                "activity_events",
            )
        }
        ideas = connection.execute("SELECT count(*) FROM ideas").fetchone()

    assert tables == []
    assert columns == []
    assert runs == [("evaluate",)]
    assert agent_rows == [("both", ["evaluate"], True, False), ("only", ["research"], False, True)]
    assert kept == {
        "outbound_email": [("owner_assigned",)],
        "notifications": [("owner_assigned",)],
        "notification_preferences": [("owner_assigned",)],
        "activity_events": [("owner_changed",)],
    }
    assert ideas == (1,)
    command.upgrade(config, "head")
    command.check(config)
