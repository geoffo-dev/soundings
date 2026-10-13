"""Bid documents through the routes (contract-phase10 section 6, ADR 0018): the upload's
order of checks and every refusal (type by bytes, macro files, the 25 MiB limit with a
lying Content-Length and a chunked body, the 120 s read limit, the upload slot, the caps
with extracted text counted, duplicates, filenames), no transaction open while the body is
read, the must-have link, the pricing mark, download headers, the text pages, deleting,
and who may do each."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bids.documents import UploadSlots, content_disposition, stored_filename
from app.middleware import UPLOAD_BODY_BYTES
from app.models.activity import AuditLog as AuditLogEntry
from app.models.ai import AiAgent, AiRun
from app.models.bid import (
    BID_DOCUMENT_MAX_BYTES,
    Bid,
    BidAiAssessment,
    BidCall,
    BidDocument,
    BidDocumentContent,
    BidDocumentText,
)
from app.models.enums import (
    AiRunKind,
    AiRunStatus,
    BidDocumentType,
    ExtractionState,
    MustHaveResult,
)
from app.schemas.bids import BID_FILENAME_MAX_LENGTH, BID_TEXT_PAGE_CHARS
from tests.bids import files
from tests.bids.conftest import (
    API,
    Api,
    AsUser,
    Crew,
    add_bid,
    assert_problem,
    assign,
    bid_detail,
    call_url,
    must_haves,
    ok,
    open_call,
    result_of,
    start,
    upload,
)
from tests.bids.files import DOCM_MAIN
from tests.factories import make_idea


@pytest.fixture
async def call(api: AsUser, crew: Crew) -> tuple[Api, dict[str, Any], dict[str, Any]]:
    """An open call with one bid, and Technical / Commercial (price) assessors."""
    owner = await api(crew.owner)
    view = await start(owner, crew)
    view = await open_call(owner, crew, view)
    await assign(owner, crew, view, {"Technical": [crew.tech1], "Commercial": [crew.commercial]})
    bid = await add_bid(owner, crew, "Northwind Data Ltd", price="120000.00")
    view = ok(await owner.get(call_url(crew)))
    return owner, view, bid


# --- Pure helpers ------------------------------------------------------------------------------
def test_the_upload_route_limit_is_the_stored_file_limit() -> None:
    assert UPLOAD_BODY_BYTES == BID_DOCUMENT_MAX_BYTES == 25 * 1024 * 1024


@pytest.mark.parametrize(
    ("given", "kind", "stored"),
    [
        ("Form of tender.pdf", BidDocumentType.PDF, "Form of tender.pdf"),
        ("Form of tender.PDF", BidDocumentType.PDF, "Form of tender.PDF"),
        ("invoice.exe", BidDocumentType.PDF, "invoice.exe.pdf"),
        ("tender.docx", BidDocumentType.PDF, "tender.docx.pdf"),
        ("photo.jpeg", BidDocumentType.JPEG, "photo.jpeg"),
        ("photo", BidDocumentType.JPEG, "photo.jpg"),
        ("prices.csv", BidDocumentType.CSV, "prices.csv"),
    ],
)
def test_stored_names_end_with_their_types_extension(
    given: str, kind: BidDocumentType, stored: str
) -> None:
    assert stored_filename(given, kind) == stored


def test_a_long_name_gets_its_stem_cut_to_fit_the_extension() -> None:
    name = "a" * BID_FILENAME_MAX_LENGTH
    stored = stored_filename(name, BidDocumentType.PDF)
    assert len(stored) == BID_FILENAME_MAX_LENGTH
    assert stored.endswith(".pdf")


def test_content_disposition_is_an_attachment_with_a_safe_fallback() -> None:
    header = content_disposition('Résumé "final"; x.pdf')
    assert header.startswith('attachment; filename="Resume _final__ x.pdf"; ')
    assert "filename*=UTF-8''R%C3%A9sum%C3%A9%20%22final%22%3B%20x.pdf" in header
    assert "inline" not in header


# --- Upload: types ----------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("data", "filename", "kind", "media"),
    [
        (files.pdf("Signed form of tender"), "Form of tender.pdf", "pdf", "application/pdf"),
        (
            files.docx("We accept your standard terms."),
            "Response.docx",
            "docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        (
            files.xlsx("Item", "Price"),
            "Prices.xlsx",
            "xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
        (
            files.pptx("Our team"),
            "Pitch.pptx",
            "pptx",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ),
        (files.odt("Plan"), "Plan.odt", "odt", "application/vnd.oasis.opendocument.text"),
        (
            files.ods("Prices"),
            "Prices.ods",
            "ods",
            "application/vnd.oasis.opendocument.spreadsheet",
        ),
        (b"Plain notes\n", "Notes.txt", "txt", "text/plain; charset=utf-8"),
        (files.csv_file("a,b"), "Prices.csv", "csv", "text/csv; charset=utf-8"),
        (files.png(), "Logo.png", "png", "image/png"),
        (files.jpeg(), "Photo.jpg", "jpeg", "image/jpeg"),
    ],
    ids=lambda value: value if isinstance(value, str) and len(value) < 40 else None,
)
async def test_each_type_is_accepted_by_its_bytes(
    call: tuple[Api, dict[str, Any], dict[str, Any]],
    crew: Crew,
    data: bytes,
    filename: str,
    kind: str,
    media: str,
) -> None:
    owner, _, bid = call

    document = ok(await upload(owner, crew, bid["id"], data, filename), 201)

    assert document["type"] == kind
    assert document["content_type"] == media
    assert document["filename"] == filename
    assert document["size_bytes"] == len(data)
    assert document["extraction"] == {
        "state": "pending",
        "error": None,
        "chars": None,
        "truncated": False,
        "page_count": 0,
    }
    assert document["pricing"] is False
    assert document["uploaded_by"]["id"] == str(crew.owner.id)


async def test_the_request_content_type_is_ignored(
    call: tuple[Api, dict[str, Any], dict[str, Any]], crew: Crew
) -> None:
    owner, _, bid = call
    document = ok(
        await upload(
            owner, crew, bid["id"], files.pdf("x"), "x.pdf", headers={"Content-Type": "image/png"}
        ),
        201,
    )
    assert document["type"] == "pdf"


@pytest.mark.parametrize(
    ("data", "filename", "code"),
    [
        (
            b"MZ\x90\x00\x03\x00\x00\x00" + b"\x00" * 64,
            "Form of tender.pdf",
            "unsupported_document_type",
        ),
        (b"", "empty.txt", "unsupported_document_type"),
        (
            b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 504,
            "secret.docx",
            "unsupported_document_type",
        ),
        (
            files.docx("x", main=DOCM_MAIN, extra={"word/vbaProject.bin": b"\x00"}),
            "Response.docx",
            "macro_document",
        ),
        (
            files.docx("x", extra={"word/embeddings/oleObject1.bin": b"\x00"}),
            "a.docx",
            "macro_document",
        ),
        (files.docx("x", extra={"word/embeddings/inner.docm": b"PK"}), "a.docx", "macro_document"),
        (files.odt("x", extra={"Basic/Standard/Module1.xml": "x"}), "a.odt", "macro_document"),
        (files.lying_zip(3, 2001), "a.docx", "unsupported_document_type"),
    ],
    ids=lambda value: value if isinstance(value, str) and len(value) < 40 else None,
)
async def test_refused_uploads(
    call: tuple[Api, dict[str, Any], dict[str, Any]],
    crew: Crew,
    db_session: AsyncSession,
    data: bytes,
    filename: str,
    code: str,
) -> None:
    owner, _, bid = call

    response = await upload(owner, crew, bid["id"], data, filename)

    assert_problem(response, 415, code)
    assert await db_session.scalar(select(func.count()).select_from(BidDocument)) == 0


@pytest.mark.parametrize(
    "filename",
    [
        "../etc/passwd.pdf",
        "folder/a.pdf",
        "a\\b.pdf",
        ".hidden.pdf",
        "a\r\nb.pdf",
        "a\u202eb.pdf",
        "",
    ],
)
async def test_unsafe_filenames_are_refused(
    call: tuple[Api, dict[str, Any], dict[str, Any]], crew: Crew, filename: str
) -> None:
    owner, _, bid = call
    response = await upload(owner, crew, bid["id"], files.pdf("x"), filename)
    assert_problem(response, 422, "validation_error")


async def test_a_two_hundred_character_name_gets_an_extension(
    call: tuple[Api, dict[str, Any], dict[str, Any]], crew: Crew
) -> None:
    owner, _, bid = call
    document = ok(await upload(owner, crew, bid["id"], files.pdf("x"), "n" * 200), 201)
    assert len(document["filename"]) == 200
    assert document["filename"].endswith(".pdf")


# --- Upload: size and time -----------------------------------------------------------------------
async def test_the_largest_file_is_accepted(
    call: tuple[Api, dict[str, Any], dict[str, Any]], crew: Crew
) -> None:
    owner, _, bid = call
    data = b"a" * BID_DOCUMENT_MAX_BYTES
    document = ok(await upload(owner, crew, bid["id"], data, "big.txt"), 201)
    assert document["size_bytes"] == BID_DOCUMENT_MAX_BYTES


async def test_one_byte_more_is_413_by_content_length(
    call: tuple[Api, dict[str, Any], dict[str, Any]], crew: Crew
) -> None:
    owner, _, bid = call
    response = await upload(owner, crew, bid["id"], b"a" * (BID_DOCUMENT_MAX_BYTES + 1), "big.txt")
    problem = assert_problem(response, 413, "content_too_large")
    assert "25 MiB" in problem["detail"]


async def test_a_body_longer_than_its_content_length_is_413(
    call: tuple[Api, dict[str, Any], dict[str, Any]], crew: Crew
) -> None:
    owner, _, bid = call
    response = await upload(
        owner,
        crew,
        bid["id"],
        b"a" * (BID_DOCUMENT_MAX_BYTES + 1),
        "big.txt",
        headers={"Content-Length": "10"},
    )
    assert_problem(response, 413, "content_too_large")


async def _chunked(size: int, *, pause: float = 0.0) -> AsyncIterator[bytes]:
    sent = 0
    while sent < size:
        chunk = b"a" * min(1024 * 1024, size - sent)
        sent += len(chunk)
        if pause:
            await asyncio.sleep(pause)
        yield chunk


async def test_a_chunked_body_is_counted_and_stopped(
    call: tuple[Api, dict[str, Any], dict[str, Any]], crew: Crew
) -> None:
    owner, _, bid = call
    response = await owner.http.post(
        API + call_url(crew, f"/bids/{bid['id']}/documents"),
        params={"filename": "big.txt"},
        content=_chunked(BID_DOCUMENT_MAX_BYTES + 1),
    )
    assert_problem(response, 413, "content_too_large")


async def test_other_routes_keep_the_one_mebibyte_limit(api: AsUser, crew: Crew) -> None:
    owner = await api(crew.owner)
    response = await owner.http.post(
        API + call_url(crew),
        content=b"{" + b" " * (1024 * 1024 + 1),
        headers={"Content-Type": "application/json"},
    )
    problem = assert_problem(response, 413, "content_too_large")
    assert "1 MiB" in problem["detail"]


async def test_a_slow_body_is_408(
    call: tuple[Api, dict[str, Any], dict[str, Any]], crew: Crew, app: FastAPI
) -> None:
    owner, _, bid = call
    app.state.bid_upload_read_timeout = 0.3
    try:
        response = await owner.http.post(
            API + call_url(crew, f"/bids/{bid['id']}/documents"),
            params={"filename": "slow.txt"},
            content=_chunked(3 * 1024 * 1024, pause=0.2),
        )
    finally:
        del app.state.bid_upload_read_timeout
    assert_problem(response, 408, "upload_timeout")


async def test_no_transaction_is_open_while_the_body_is_read(
    call: tuple[Api, dict[str, Any], dict[str, Any]],
    crew: Crew,
    settings: Any,
    db_session: AsyncSession,
) -> None:
    owner, _, bid = call
    await db_session.rollback()
    seen: list[int] = []

    async def body() -> AsyncIterator[bytes]:
        yield b"first line\n"
        async with await psycopg.AsyncConnection.connect(settings.database_dsn) as connection:
            cursor = await connection.execute(
                "SELECT count(*) FROM pg_stat_activity WHERE state LIKE 'idle in transaction%'"
                " AND application_name = 'soundings-api' AND pid <> pg_backend_pid()"
                " AND datname = current_database()"
            )
            row = await cursor.fetchone()
            assert row is not None
            seen.append(int(row[0]))
        yield b"second line\n"

    response = await owner.http.post(
        API + call_url(crew, f"/bids/{bid['id']}/documents"),
        params={"filename": "notes.txt"},
        content=body(),
    )

    ok(response, 201)
    assert seen == [0]


async def test_a_full_slot_is_503_after_the_403s(
    call: tuple[Api, dict[str, Any], dict[str, Any]], crew: Crew, api: AsUser, app: FastAPI
) -> None:
    owner, _, bid = call
    member = await api(crew.member)
    slots = UploadSlots(0)
    app.state.bid_upload_slots = slots
    try:
        refused = await upload(member, crew, bid["id"], files.pdf("x"))
        busy = await upload(owner, crew, bid["id"], files.pdf("x"))
    finally:
        del app.state.bid_upload_slots
    assert_problem(refused, 403, "forbidden")
    assert_problem(busy, 503, "upload_busy")
    assert busy.headers["Retry-After"] == "5"


# --- Upload: caps and duplicates ---------------------------------------------------------------
async def test_the_same_file_twice_on_one_bid_is_409(
    call: tuple[Api, dict[str, Any], dict[str, Any]], crew: Crew
) -> None:
    owner, _, bid = call
    data = files.pdf("Form of tender")
    ok(await upload(owner, crew, bid["id"], data, "a.pdf"), 201)
    assert_problem(await upload(owner, crew, bid["id"], data, "b.pdf"), 409, "duplicate_document")
    other = await add_bid(owner, crew, "Tessellate Software", price="96000.00")
    ok(await upload(owner, crew, other["id"], data, "a.pdf"), 201)  # another bid may


async def _fill(
    db: AsyncSession, bid_id: UUID, call_id: UUID, count: int, size: int, text_chars: int = 0
) -> None:
    """``count`` document rows claiming ``size`` bytes each (1-byte contents)."""
    for _ in range(count):
        document = BidDocument(
            id=uuid4(),
            bid_id=bid_id,
            call_id=call_id,
            filename="filler.txt",
            type=BidDocumentType.TXT,
            content_type="text/plain; charset=utf-8",
            size_bytes=size,
            sha256=uuid4().hex + uuid4().hex,
            extraction_state=ExtractionState.DONE if text_chars else ExtractionState.PENDING,
            extracted_at=None,
            text_chars=text_chars if text_chars else None,
        )
        if text_chars:
            from app.models.base import utcnow

            document.extracted_at = utcnow()
        db.add(document)
        await db.flush()
        db.add(BidDocumentContent(document_id=document.id, data=b"x"))
    await db.commit()


async def test_thirty_documents_per_bid(
    call: tuple[Api, dict[str, Any], dict[str, Any]], crew: Crew, db_session: AsyncSession
) -> None:
    owner, view, bid = call
    await _fill(db_session, UUID(bid["id"]), UUID(view["call"]["id"]), 30, 1)
    assert_problem(await upload(owner, crew, bid["id"], files.pdf("x")), 409, "too_many_documents")


async def test_the_call_cap_counts_extracted_text(
    call: tuple[Api, dict[str, Any], dict[str, Any]], crew: Crew, db_session: AsyncSession
) -> None:
    owner, view, bid = call
    call_id = UUID(view["call"]["id"])
    other = await add_bid(owner, crew, "Tessellate Software", price="96000.00")
    # 19 files of 25 MiB = 475 MiB; with 2,000,000 characters of text on each of 13 of
    # them the call holds 475 MiB + 26,000,000 bytes: an upload of 1 MiB passes 500 MiB.
    await _fill(db_session, UUID(bid["id"]), call_id, 13, BID_DOCUMENT_MAX_BYTES, 2_000_000)
    await _fill(db_session, UUID(other["id"]), call_id, 6, BID_DOCUMENT_MAX_BYTES)
    small = files.pdf("x")
    ok(await upload(owner, crew, other["id"], small, "small.pdf"), 201)
    big = b"b" * (1024 * 1024)
    assert_problem(await upload(owner, crew, other["id"], big, "big.txt"), 409, "call_storage_full")


async def test_the_project_cap(
    call: tuple[Api, dict[str, Any], dict[str, Any]], crew: Crew, db_session: AsyncSession
) -> None:
    owner, _, bid = call
    # Another idea of the project with a call holding 5 GiB (as far as the cap counts).
    idea = await make_idea(db_session, crew.project, title="Old platform", owner=crew.owner)
    other_call = BidCall(
        id=uuid4(),
        idea_id=idea.id,
        title="Old call",
        scale=["0", "1", "2", "3", "4", "5"],
        created_by_id=crew.owner.id,
    )
    db_session.add(other_call)
    await db_session.flush()
    other_bid = Bid(id=uuid4(), call_id=other_call.id, bidder="Old bidder")
    db_session.add(other_bid)
    await db_session.commit()
    await _fill(db_session, other_bid.id, other_call.id, 205, BID_DOCUMENT_MAX_BYTES)
    assert_problem(
        await upload(owner, crew, bid["id"], files.pdf("x")), 409, "project_storage_full"
    )


# --- Must-haves and pricing ----------------------------------------------------------------
async def test_linking_a_required_document_meets_it_and_deleting_it_unmeets_it(
    call: tuple[Api, dict[str, Any], dict[str, Any]], crew: Crew
) -> None:
    owner, view, bid = call
    tender = must_haves(view)["Signed form of tender"]
    before = result_of(await bid_detail(owner, crew, bid["id"]), "Signed form of tender")
    assert before["result"] == "missing"

    document = ok(
        await upload(owner, crew, bid["id"], files.pdf("Signed"), must_have_id=tender["id"]), 201
    )
    linked = result_of(await bid_detail(owner, crew, bid["id"]), "Signed form of tender")
    assert linked["result"] == "met"
    assert linked["automatic"] is True
    assert linked["document_ids"] == [document["id"]]

    # A person's met is about that file: deleting it makes the must-have missing again.
    ok(
        await owner.put(
            call_url(crew, f"/bids/{bid['id']}/must-haves/{tender['id']}"),
            {"result": "met", "note": "Checked the signature."},
        )
    )
    deleted = await owner.delete(call_url(crew, f"/bids/{bid['id']}/documents/{document['id']}"))
    assert deleted.status_code == 204
    after = result_of(await bid_detail(owner, crew, bid["id"]), "Signed form of tender")
    assert after["result"] == "missing"
    assert after["decided_by"] is None


async def test_a_not_met_stays_when_the_file_goes(
    call: tuple[Api, dict[str, Any], dict[str, Any]], crew: Crew
) -> None:
    owner, view, bid = call
    tender = must_haves(view)["Signed form of tender"]
    document = ok(
        await upload(owner, crew, bid["id"], files.pdf("Unsigned"), must_have_id=tender["id"]),
        201,
    )
    ok(
        await owner.put(
            call_url(crew, f"/bids/{bid['id']}/must-haves/{tender['id']}"),
            {"result": "not_met", "note": "Not signed."},
        )
    )
    unlinked = ok(
        await owner.put(
            call_url(crew, f"/bids/{bid['id']}/documents/{document['id']}"),
            {"must_have_id": None, "pricing": False},
        )
    )
    assert unlinked["must_have_id"] is None
    result = result_of(await bid_detail(owner, crew, bid["id"]), "Signed form of tender")
    assert result["result"] == "not_met"


async def test_invalid_must_have_links(
    call: tuple[Api, dict[str, Any], dict[str, Any]], crew: Crew
) -> None:
    owner, view, bid = call
    links = must_haves(view)
    confirmation = links["Accepts our standard terms"]["id"]
    pricing = links["Pricing schedule"]["id"]
    for params in (
        {"must_have_id": confirmation},
        {"must_have_id": str(uuid4())},
        {"must_have_id": pricing, "pricing": False},
    ):
        response = await upload(owner, crew, bid["id"], files.pdf(str(params)), **params)
        assert_problem(response, 422, "invalid_must_have")


async def test_pricing_documents_are_only_for_bid_view_price(
    call: tuple[Api, dict[str, Any], dict[str, Any]], crew: Crew, api: AsUser
) -> None:
    owner, view, bid = call
    schedule = must_haves(view)["Pricing schedule"]
    priced = ok(
        await upload(
            owner,
            crew,
            bid["id"],
            files.xlsx("Total", "120000"),
            "Prices.xlsx",
            must_have_id=schedule["id"],
        ),
        201,
    )
    assert priced["pricing"] is True
    plain = ok(await upload(owner, crew, bid["id"], files.pdf("Plan"), "Plan.pdf"), 201)
    marked = ok(
        await upload(owner, crew, bid["id"], files.pdf("Rates"), "Rates.pdf", pricing=True), 201
    )
    assert marked["pricing"] is True

    technical = await api(crew.tech1)
    commercial = await api(crew.commercial)
    tech_view = await bid_detail(technical, crew, bid["id"])
    assert [d["id"] for d in tech_view["documents"]] == [plain["id"]]
    assert tech_view["document_count"] == 1
    assert tech_view["restricted_document_count"] == 2
    tech_result = result_of(tech_view, "Pricing schedule")
    assert tech_result["document_ids"] == []
    assert tech_result["restricted_document_count"] == 1
    assert "Prices.xlsx" not in str(tech_view)
    for document in (priced, marked):
        base = call_url(crew, f"/bids/{bid['id']}/documents/{document['id']}")
        assert_problem(await technical.get(base + "/content"), 404, "not_found")
        assert_problem(await technical.get(base + "/text"), 404, "not_found")

    commercial_view = await bid_detail(commercial, crew, bid["id"])
    assert {d["id"] for d in commercial_view["documents"]} == {
        priced["id"],
        plain["id"],
        marked["id"],
    }
    assert commercial_view["restricted_document_count"] == 0
    content = await commercial.http.get(
        API + call_url(crew, f"/bids/{bid['id']}/documents/{priced['id']}/content")
    )
    assert content.status_code == 200


async def test_marking_a_document_pricing_clears_the_ai_and_cancels_its_runs(
    call: tuple[Api, dict[str, Any], dict[str, Any]],
    crew: Crew,
    db_session: AsyncSession,
) -> None:
    owner, view, bid = call
    document = ok(await upload(owner, crew, bid["id"], files.pdf("Rates"), "Rates.pdf"), 201)
    from tests.ai.helpers import make_agent

    agent = await make_agent(db_session, [crew.project], purposes=[AiRunKind.ASSESS_BID])
    db_session.add(BidAiAssessment(id=uuid4(), bid_id=UUID(bid["id"]), agent_id=agent.id))
    run = AiRun(
        id=uuid4(),
        idea_id=crew.idea.id,
        agent_id=agent.id,
        kind=AiRunKind.ASSESS_BID,
        bid_id=UUID(bid["id"]),
        bid_call_id=UUID(view["call"]["id"]),
        requested_by_id=crew.owner.id,
        status=AiRunStatus.QUEUED,
        timeout_seconds=600,
    )
    db_session.add(run)
    await db_session.commit()
    run_id = run.id

    ok(
        await owner.put(
            call_url(crew, f"/bids/{bid['id']}/documents/{document['id']}"),
            {"must_have_id": None, "pricing": True},
        )
    )

    assert await db_session.scalar(select(func.count()).select_from(BidAiAssessment)) == 0
    stored = await db_session.get(AiRun, run_id, populate_existing=True)
    assert stored is not None
    assert stored.status is AiRunStatus.CANCELLED
    entry = await db_session.scalar(
        select(AuditLogEntry).where(AuditLogEntry.action == "bid_document.update")
    )
    assert entry is not None
    assert entry.details["fields"] == ["pricing"]
    assert entry.details["ai_assessments_deleted"] == 1
    assert entry.details["cancelled_runs"] == 1
    assert "Rates" not in str(entry.details)
    # Unmarking changes nothing else and is audited too.
    ok(
        await owner.put(
            call_url(crew, f"/bids/{bid['id']}/documents/{document['id']}"),
            {"must_have_id": None, "pricing": False},
        )
    )
    assert isinstance(agent.agent, AiAgent)


async def test_a_pricing_must_have_link_keeps_the_mark(
    call: tuple[Api, dict[str, Any], dict[str, Any]], crew: Crew
) -> None:
    owner, view, bid = call
    schedule = must_haves(view)["Pricing schedule"]["id"]
    document = ok(await upload(owner, crew, bid["id"], files.pdf("Rates"), "Rates.pdf"), 201)
    response = await owner.put(
        call_url(crew, f"/bids/{bid['id']}/documents/{document['id']}"),
        {"must_have_id": schedule, "pricing": False},
    )
    assert_problem(response, 422, "invalid_must_have")


# --- Download and text --------------------------------------------------------------------------
async def test_download_headers_and_bytes(
    call: tuple[Api, dict[str, Any], dict[str, Any]], crew: Crew
) -> None:
    owner, _, bid = call
    data = files.pdf("Form of tender")
    document = ok(await upload(owner, crew, bid["id"], data, "Tender (signed).docx"), 201)
    assert document["filename"] == "Tender (signed).docx.pdf"

    response = await owner.http.get(
        API + call_url(crew, f"/bids/{bid['id']}/documents/{document['id']}/content")
    )

    assert response.status_code == 200
    assert response.content == data
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].startswith("attachment; ")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-security-policy"] == "default-src 'none'; sandbox"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["content-length"] == str(len(data))


async def test_a_large_download_comes_in_chunks_intact(
    call: tuple[Api, dict[str, Any], dict[str, Any]], crew: Crew
) -> None:
    owner, _, bid = call
    data = bytes(range(32, 127)) * (3 * 1024 * 1024 // 95 + 7)
    document = ok(await upload(owner, crew, bid["id"], data, "big.txt"), 201)
    response = await owner.http.get(
        API + call_url(crew, f"/bids/{bid['id']}/documents/{document['id']}/content")
    )
    assert response.content == data


async def test_text_pages(
    call: tuple[Api, dict[str, Any], dict[str, Any]], crew: Crew, db_session: AsyncSession
) -> None:
    owner, _, bid = call
    document = ok(await upload(owner, crew, bid["id"], b"pending\n", "a.txt"), 201)
    base = call_url(crew, f"/bids/{bid['id']}/documents/{document['id']}/text")
    pending = ok(await owner.get(base))
    assert pending == {
        "document_id": document["id"],
        "state": "pending",
        "page": 1,
        "page_count": 0,
        "text": "",
        "truncated": False,
    }
    assert_problem(await owner.get(base, page=2), 404, "not_found")

    text = "é" * (BID_TEXT_PAGE_CHARS + 5)
    row = await db_session.get(BidDocument, UUID(document["id"]))
    assert row is not None
    from app.models.base import utcnow

    row.extraction_state = ExtractionState.DONE
    row.extracted_at = utcnow()
    row.text_chars = len(text)
    db_session.add(BidDocumentText(document_id=row.id, text=text))
    await db_session.commit()

    first = ok(await owner.get(base))
    second = ok(await owner.get(base, page=2))
    assert first["page_count"] == second["page_count"] == 2
    assert first["text"] == "é" * BID_TEXT_PAGE_CHARS
    assert second["text"] == "é" * 5
    assert_problem(await owner.get(base, page=3), 404, "not_found")
    detail = await bid_detail(owner, crew, bid["id"])
    assert detail["documents"][0]["extraction"]["page_count"] == 2


# --- Who may --------------------------------------------------------------------------------------
async def test_who_may_upload_and_read(
    call: tuple[Api, dict[str, Any], dict[str, Any]], crew: Crew, api: AsUser
) -> None:
    owner, _, bid = call
    document = ok(await upload(owner, crew, bid["id"], files.pdf("Plan"), "Plan.pdf"), 201)
    base = call_url(crew, f"/bids/{bid['id']}/documents/{document['id']}")
    technical = await api(crew.tech1)
    member = await api(crew.member)
    outsider = await api(crew.outsider)
    admin = await api(crew.admin)
    platform = await api(crew.platform)

    # Assessors read documents but don't upload, link or delete them.
    assert (await technical.http.get(API + base + "/content")).status_code == 200
    ok(await technical.get(base + "/text"))
    assert_problem(await upload(technical, crew, bid["id"], files.pdf("y")), 403, "forbidden")
    assert_problem(
        await technical.put(base, {"must_have_id": None, "pricing": False}), 403, "forbidden"
    )
    assert_problem(await technical.delete(base), 403, "forbidden")
    # A member sees only that a call exists: the same 403 for a real and an unknown id.
    assert_problem(await member.get(base + "/text"), 403, "forbidden")
    unknown = call_url(crew, f"/bids/{uuid4()}/documents/{uuid4()}/text")
    assert_problem(await member.get(unknown), 403, "forbidden")
    assert_problem(await upload(member, crew, bid["id"], files.pdf("z")), 403, "forbidden")
    # Someone who can't see the idea: 404.
    assert_problem(await outsider.get(base + "/text"), 404, "not_found")
    # Project and platform admins are call managers.
    ok(await upload(admin, crew, bid["id"], files.pdf("admin"), "a.pdf"), 201)
    ok(await upload(platform, crew, bid["id"], files.pdf("platform"), "p.pdf"), 201)


async def test_another_bids_document_is_404(
    call: tuple[Api, dict[str, Any], dict[str, Any]], crew: Crew
) -> None:
    owner, _, bid = call
    other = await add_bid(owner, crew, "Tessellate Software", price="96000.00")
    document = ok(await upload(owner, crew, bid["id"], files.pdf("Plan"), "Plan.pdf"), 201)
    wrong = call_url(crew, f"/bids/{other['id']}/documents/{document['id']}")
    assert_problem(await owner.get(wrong + "/text"), 404, "not_found")
    assert_problem(await owner.delete(wrong), 404, "not_found")


async def test_documents_are_read_only_after_the_award(
    call: tuple[Api, dict[str, Any], dict[str, Any]], crew: Crew, db_session: AsyncSession
) -> None:
    owner, view, bid = call
    document = ok(await upload(owner, crew, bid["id"], files.pdf("Plan"), "Plan.pdf"), 201)
    stored = await db_session.get(BidCall, UUID(view["call"]["id"]))
    assert stored is not None
    from app.models.base import utcnow
    from app.models.enums import BidCallStatus

    stored.status = BidCallStatus.CANCELLED
    stored.cancelled_at = utcnow()
    await db_session.commit()
    base = call_url(crew, f"/bids/{bid['id']}/documents/{document['id']}")
    assert_problem(
        await upload(owner, crew, bid["id"], files.pdf("late")), 409, "bid_call_finished"
    )
    assert_problem(
        await owner.put(base, {"must_have_id": None, "pricing": True}), 409, "bid_call_finished"
    )
    assert_problem(await owner.delete(base), 409, "bid_call_finished")
    # Reading stays.
    assert (await owner.http.get(API + base + "/content")).status_code == 200


async def test_the_upload_is_audited_without_the_name(
    call: tuple[Api, dict[str, Any], dict[str, Any]], crew: Crew, db_session: AsyncSession
) -> None:
    owner, _, bid = call
    document = ok(
        await upload(owner, crew, bid["id"], files.pdf("x"), "Ada Price CV.pdf", pricing=True), 201
    )
    entry = await db_session.scalar(
        select(AuditLogEntry).where(AuditLogEntry.action == "bid_document.upload")
    )
    assert entry is not None
    assert entry.details["document_id"] == document["id"]
    assert entry.details["pricing"] is True
    assert "Ada" not in str(entry.details)
    deleted = await owner.delete(call_url(crew, f"/bids/{bid['id']}/documents/{document['id']}"))
    assert deleted.status_code == 204
    gone = await db_session.scalar(
        select(AuditLogEntry).where(AuditLogEntry.action == "bid_document.delete")
    )
    assert gone is not None
    assert "Ada" not in str(gone.details)


async def test_an_upload_defers_its_extraction_job(
    call: tuple[Api, dict[str, Any], dict[str, Any]], crew: Crew, db_session: AsyncSession
) -> None:
    owner, _, bid = call
    document = ok(await upload(owner, crew, bid["id"], files.pdf("x"), "x.pdf"), 201)
    from sqlalchemy import text

    jobs = (
        await db_session.execute(
            text(
                "SELECT queue_name, args->>'document_id' FROM procrastinate_jobs"
                " WHERE task_name = 'extract_bid_document'"
            )
        )
    ).all()
    assert jobs == [("bid_documents", document["id"])]


async def test_a_key_cant_upload(
    call: tuple[Api, dict[str, Any], dict[str, Any]],
    crew: Crew,
    db_session: AsyncSession,
    app: FastAPI,
) -> None:
    _, _, bid = call
    from tests.api_keys.helpers import key_client, make_key

    secret = await make_key(db_session, crew.owner, scopes=["read", "write", "evaluate", "mcp"])
    async with key_client(app, secret) as http:
        response = await http.post(
            API + call_url(crew, f"/bids/{bid['id']}/documents"),
            params={"filename": "x.pdf"},
            content=files.pdf("x"),
        )
    assert_problem(response, 403, "insufficient_scope")


async def test_a_must_have_result_of_a_deleted_link_is_recomputed(
    call: tuple[Api, dict[str, Any], dict[str, Any]], crew: Crew
) -> None:
    owner, view, bid = call
    insurance = must_haves(view)["Insurance certificate"]["id"]
    first = ok(
        await upload(owner, crew, bid["id"], files.pdf("one"), "1.pdf", must_have_id=insurance),
        201,
    )
    ok(await upload(owner, crew, bid["id"], files.pdf("two"), "2.pdf", must_have_id=insurance), 201)
    gone = await owner.delete(call_url(crew, f"/bids/{bid['id']}/documents/{first['id']}"))
    assert gone.status_code == 204
    # One file is still linked: still met.
    result = result_of(await bid_detail(owner, crew, bid["id"]), "Insurance certificate")
    assert result["result"] == MustHaveResult.MET.value


async def test_a_call_and_an_idea_go_with_their_linked_documents(
    call: tuple[Api, dict[str, Any], dict[str, Any]],
    crew: Crew,
    db_session: AsyncSession,
    api: AsUser,
) -> None:
    """The documents' composite key to the must-haves is NO ACTION: deleting the call (or
    the idea) unlinks them first, so the cascade takes everything."""
    owner, view, bid = call
    tender = must_haves(view)["Signed form of tender"]["id"]
    ok(await upload(owner, crew, bid["id"], files.pdf("Signed"), must_have_id=tender), 201)
    ok(await owner.post(call_url(crew, "/cancellation"), {"reason": "Budget withdrawn."}))
    deleted = await owner.delete(call_url(crew))
    assert deleted.status_code == 204, deleted.text
    assert await db_session.scalar(select(func.count()).select_from(BidDocument)) == 0
    assert await db_session.scalar(select(func.count()).select_from(BidDocumentContent)) == 0

    # Again, then the idea itself.
    view = await start(owner, crew)
    view = await open_call(owner, crew, view)
    bid = await add_bid(owner, crew, "Northwind Data Ltd", price="120000.00")
    tender = must_haves(view)["Signed form of tender"]["id"]
    ok(await upload(owner, crew, bid["id"], files.pdf("Signed"), must_have_id=tender), 201)
    platform = await api(crew.platform)
    gone = await platform.delete(f"/ideas/{crew.key}")
    assert gone.status_code == 204, gone.text
    assert await db_session.scalar(select(func.count()).select_from(BidDocument)) == 0
