"""Text extraction (contract-phase10 section 6.3, ADR 0018 decision 5): each type, the
archive and XML guards (zip bombs by ratio, one part and the total as they stream, too
many entries, nested archives, DOCTYPE), damaged and encrypted files, the text cap, hidden
characters removed, active content, and the child process itself (its environment, the
time limit, the memory cap, stdin/stdout), then the worker's job: attempts, crashes, the
stored text, and the sweep."""

from __future__ import annotations

import asyncio
import io
import os
import re
import tempfile
import zlib
from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.bids import extraction
from app.bids.extract_child import Limits, extract
from app.bids.extraction import (
    CHILD_LIMITS,
    ChildOutcome,
    _child_environment,
    _read,
    _TooMuchOutput,
    extract_document,
    run_child,
    sweep_documents,
)
from app.models.base import utcnow
from app.models.bid import BidDocument, BidDocumentContent, BidDocumentText
from app.models.enums import BidDocumentType, ExtractionError, ExtractionState
from app.schemas.bids import BID_EXTRACTION_MAX_ATTEMPTS
from tests.bids import files
from tests.bids.conftest import Api, AsUser, Crew, add_bid, ok, open_call, start
from tests.bids.files import zip_of

LIMITS = Limits(**CHILD_LIMITS)


def small(**changes: int) -> Limits:
    return Limits(**{**CHILD_LIMITS, **changes})


# --- In process: each type -------------------------------------------------------------------
@pytest.mark.parametrize(
    ("kind", "data", "expected"),
    [
        (
            "pdf",
            files.pdf("Signed form of tender", "Second line"),
            "Signed form of tender\nSecond line",
        ),
        ("docx", files.docx("We accept", "your terms"), "We accept\nyour terms"),
        ("xlsx", files.xlsx("Item", "Total 120000"), "Item\nTotal 120000"),
        ("pptx", files.pptx("Our team"), "Our team"),
        ("odt", files.odt("Plan", "Phase two"), "Plan\nPhase two"),
        ("ods", files.ods("Prices"), "Prices"),
        ("txt", "Ünïcode notes\r\n".encode(), "Ünïcode notes"),
        ("txt", "caf\xe9 notes".encode("cp1252"), "café notes"),
        ("csv", files.csv_file("item,price", "a,1"), "item,price\r\na,1"),
    ],
)
def test_each_type(kind: str, data: bytes, expected: str) -> None:
    result = extract(kind, data, LIMITS)
    assert result.state == "done", result
    assert result.text == expected
    assert not result.truncated
    assert not result.active_content


@pytest.mark.parametrize("kind", ["png", "jpeg"])
def test_images_have_no_text(kind: str) -> None:
    assert extract(kind, files.png(), LIMITS).state == "no_text"


def test_a_document_without_text() -> None:
    assert extract("docx", files.docx(), LIMITS).state == "no_text"
    assert extract("pdf", files.pdf(), LIMITS).state == "no_text"


def test_shared_strings_and_values_come_out_in_cells() -> None:
    sheet = (
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetData><row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1"><v>96000</v></c>'
        '<c r="C1" t="inlineStr"><is><t>GBP</t></is></c></row></sheetData></worksheet>'
    )
    data = files.xlsx("Total", extra={"xl/worksheets/sheet1.xml": sheet})
    assert extract("xlsx", data, LIMITS).text == "Total\t96000\tGBP"


# --- Archive and XML guards --------------------------------------------------------------------
def test_a_zip_bomb_by_ratio() -> None:
    body = "<w:p/>" * (3 * 1024 * 1024)  # 18 MB of XML that compresses about 1000 times
    result = extract("docx", files.docx(body_xml=body), LIMITS)
    assert (result.state, result.error) == ("failed", "archive_limits")


def test_a_ratio_claimed_honestly_is_counted_as_it_streams() -> None:
    """Sizes the archive claims can lie: what decompresses is counted."""
    body = "<w:p/>" * (3 * 1024 * 1024)
    data = bytearray(files.docx(body_xml=body))
    # Claim a tiny uncompressed size for word/document.xml in the central directory.
    import struct

    at = data.find(b"PK\x01\x02")
    while at >= 0:
        name_length = struct.unpack_from("<H", data, at + 28)[0]
        if bytes(data[at + 46 : at + 46 + name_length]) == b"word/document.xml":
            struct.pack_into("<I", data, at + 24, 100)
        at = data.find(b"PK\x01\x02", at + 4)
    result = extract("docx", bytes(data), LIMITS)
    assert result.state == "failed"
    assert result.error in ("archive_limits", "damaged")


def test_one_part_over_its_cap() -> None:
    body = "".join(f"<w:p><w:r><w:t>{os.urandom(32).hex()}</w:t></w:r></w:p>" for _ in range(500))
    result = extract("docx", files.docx(body_xml=body), small(part_max_bytes=10_000))
    assert (result.state, result.error) == ("failed", "archive_limits")


def test_all_parts_over_the_total_cap() -> None:
    header = "".join(f"<w:p><w:r><w:t>{os.urandom(16).hex()}</w:t></w:r></w:p>" for _ in range(80))
    header_xml = (
        '<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        + header
        + "</w:hdr>"
    )
    data = files.docx(
        body_xml=header, extra={f"word/header{n}.xml": header_xml for n in range(1, 6)}
    )
    limits = small(part_max_bytes=20_000, total_max_bytes=30_000)
    result = extract("docx", data, limits)
    assert (result.state, result.error) == ("failed", "archive_limits")


def test_too_many_entries() -> None:
    data = files.docx("x", extra={f"customXml/item{n}.xml": "<x/>" for n in range(10)})
    result = extract("docx", data, small(max_entries=5))
    assert (result.state, result.error) == ("failed", "archive_limits")


def test_nested_archives_are_never_opened() -> None:
    inner = files.docx("Secret inside")
    data = files.docx("Outer text", extra={"word/embeddings/inner.docx": inner})
    result = extract("docx", data, LIMITS)
    assert result.text == "Outer text"


def test_a_doctype_is_refused() -> None:
    laughs = (
        '<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">'
        '<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">]>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body><w:p><w:r><w:t>&lol2;</w:t></w:r></w:p></w:body></w:document>"
    )
    data = zip_of(
        {
            "[Content_Types].xml": files._content_types(files.DOCX_MAIN, "word/document.xml"),
            "word/document.xml": laughs,
        }
    )
    result = extract("docx", data, LIMITS)
    assert (result.state, result.error) == ("failed", "damaged")


@pytest.mark.parametrize(
    ("kind", "data"),
    [
        ("docx", files.docx("Hello")[:200]),
        ("pdf", b"%PDF-1.4\n" + os.urandom(2000)),
        ("odt", b"PK\x03\x04 broken"),
        ("docx", zip_of({"word/document.xml": "<w:document><unclosed>"})),
    ],
)
def test_damaged_files(kind: str, data: bytes) -> None:
    result = extract(kind, data, LIMITS)
    assert (result.state, result.error) == ("failed", "damaged")


def _encrypted_pdf(user_password: str, owner_password: str = "owner") -> bytes:  # noqa: S107
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(files.pdf("Confidential price list"))))
    writer.encrypt(user_password=user_password, owner_password=owner_password, algorithm="AES-128")
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def test_an_encrypted_pdf() -> None:
    result = extract("pdf", _encrypted_pdf("secret"), LIMITS)
    assert (result.state, result.error) == ("failed", "encrypted")


def test_a_pdf_with_only_an_owner_password_is_read() -> None:
    result = extract("pdf", _encrypted_pdf(""), LIMITS)
    assert result.state == "done"
    assert result.text == "Confidential price list"


def test_the_text_cap() -> None:
    result = extract("txt", b"a" * 500, small(max_chars=100))
    assert result.state == "done"
    assert result.text == "a" * 100
    assert result.truncated
    paragraphs = [os.urandom(40).hex() for _ in range(100)]
    huge = extract("docx", files.docx(*paragraphs), small(max_chars=1000))
    assert huge.truncated
    assert len(huge.text) == 1000


def test_hidden_characters_are_removed() -> None:
    sneaky = "Ac\u00adcepts\u200b our\u202e terms\U000e0041\U000e0042 fully"
    for kind, data in (
        ("txt", sneaky.encode()),
        ("docx", files.docx(sneaky)),
        ("pdf", files.pdf("Accepts our terms")),
    ):
        result = extract(kind, data, LIMITS)
        assert "\u00ad" not in result.text
        assert "\u200b" not in result.text
        assert "\u202e" not in result.text
        assert "\U000e0041" not in result.text
    assert extract("txt", sneaky.encode(), LIMITS).text == "Accepts our terms fully"


# --- Active content ----------------------------------------------------------------------------
def test_pdf_javascript_is_active_content() -> None:
    data = files.pdf("Open me", catalog_extra="/OpenAction << /S /JavaScript /JS (app.alert(1)) >>")
    result = extract("pdf", data, LIMITS)
    assert result.state == "done"
    assert result.active_content


def test_a_pdf_launch_action_and_attached_files_are_active_content() -> None:
    launch = files.pdf("x", catalog_extra="/OpenAction << /S /Launch /F (calc.exe) >>")
    attached = files.pdf("y", catalog_extra="/Names << /EmbeddedFiles 6 0 R >>", objects=["<< >>"])
    assert extract("pdf", launch, LIMITS).active_content
    assert extract("pdf", attached, LIMITS).active_content


def test_a_plain_pdf_isnt_active() -> None:
    assert not extract("pdf", files.pdf("Plain"), LIMITS).active_content


_RELS = (
    '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.'
    'openxmlformats.org/package/2006/relationships">{}</Relationships>'
)


def test_a_remote_template_is_active_content() -> None:
    rels = _RELS.format(
        '<Relationship Id="rId9" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
        'relationships/attachedTemplate" Target="https://evil.example/t.dotm" '
        'TargetMode="External"/>'
    )
    data = files.docx("Hello", document_rels=rels)
    result = extract("docx", data, LIMITS)
    assert result.text == "Hello"
    assert result.active_content


def test_a_hyperlink_isnt_active_content() -> None:
    rels = _RELS.format(
        '<Relationship Id="rId9" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
        'relationships/hyperlink" Target="https://example.com" TargetMode="External"/>'
    )
    assert not extract("docx", files.docx("Hello", document_rels=rels), LIMITS).active_content


def test_a_dde_field_is_active_content() -> None:
    body = (
        '<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText> DDEAUTO '
        'c:\\\\windows\\\\system32\\\\cmd.exe "/k calc"</w:instrText></w:r>'
        "<w:r><w:t>Click</w:t></w:r></w:p>"
    )
    assert extract("docx", files.docx(body_xml=body), LIMITS).active_content


def test_excel_external_links_are_active_content() -> None:
    data = files.xlsx("Total", extra={"xl/externalLinks/externalLink1.xml": "<externalLink/>"})
    assert extract("xlsx", data, LIMITS).active_content


# --- Review M3, L2, L3: active content without false alarms, kept on failures ----------------
def test_active_names_inside_page_content_arent_active_content() -> None:
    """Review M3: the names were matched in the raw bytes, compressed streams included, so
    text (or random compressed bytes) reading ``/JS`` or ``/Launch`` raised the warning."""
    data = files.pdf("Our /JS and /Launch plans", "see /JavaScript /EmbeddedFiles")
    result = extract("pdf", data, LIMITS)
    assert result.state == "done"
    assert not result.active_content


def test_binary_streams_arent_active_content() -> None:
    """A stream's bytes (an image, a compressed font) may hold ``/JS`` by chance: about
    once per 25 MB of random data (review M3)."""
    binary = (b"\x00\x9c\xff /JS (x) /Launch\n\x01" + zlib.compress(b"x" * 999)) * 50
    data = files.pdf("Plain", objects=[files.pdf_stream(binary)])
    assert re.search(rb"/(?:JS|Launch)(?![A-Za-z0-9])", data)
    assert not extract("pdf", data, LIMITS).active_content


@pytest.mark.parametrize(
    "catalog",
    [
        "/OpenAction 6 0 R",  # an action dictionary held by reference
        "/Names << /JavaScript << /Names [(a) 6 0 R] >> >>",
    ],
)
def test_javascript_held_by_reference_is_active_content(catalog: str) -> None:
    data = files.pdf(
        "x", catalog_extra=catalog, objects=["<< /S /JavaScript /JS (app.alert(1)) >>"]
    )
    assert extract("pdf", data, LIMITS).active_content


def test_a_file_attachment_annotation_is_active_content() -> None:
    data = files.pdf(
        "x",
        page_extra="/Annots [6 0 R]",
        objects=[
            "<< /Type /Annot /Subtype /FileAttachment /Rect [0 0 1 1] /FS 7 0 R >>",
            "<< /Type /Filespec /F (a.exe) >>",
        ],
    )
    assert extract("pdf", data, LIMITS).active_content


def test_a_damaged_pdf_keeps_its_active_content() -> None:
    """Review L2: a damaged file's raw objects (outside streams) still show the action."""
    data = files.pdf("Open me", catalog_extra="/OpenAction << /S /JavaScript /JS (x) >>")
    broken = data[: data.index(b"xref")].replace(b"/Type /Pages", b"/Type /Pagez")
    broken = broken.replace(b"/Kids [3 0 R]", b"/Kids [9 0 R]")
    result = extract("pdf", broken, LIMITS)
    assert result.state == "failed"
    assert result.active_content


_SCRIPT = "urn:oasis:names:tc:opendocument:xmlns:script:1.0"
_XLINK = "http://www.w3.org/1999/xlink"


def test_opendocument_event_listeners_are_active_content() -> None:
    """Review L3: a macro bound to an event (``script:event-listener``)."""
    body = (
        f'<office:scripts><office:event-listeners xmlns:script="{_SCRIPT}" '
        f'xmlns:xlink="{_XLINK}"><script:event-listener script:language="ooo:script" '
        'script:event-name="dom:load" xlink:href="vnd.sun.star.script:Standard.M.Run"/>'
        "</office:event-listeners></office:scripts>"
    )
    data = files.odt("Hello", head=body)
    result = extract("odt", data, LIMITS)
    assert result.text == "Hello"
    assert result.active_content


def test_opendocument_external_objects_and_dde_are_active_content() -> None:
    linked = files.odt(
        "Hello",
        body_extra=f'<draw:object xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" '
        f'xmlns:xlink="{_XLINK}" xlink:href="https://evil.example/o.odt"/>',
    )
    dde = files.odt(
        "Hello",
        body_extra='<office:dde-source office:dde-application="cmd" office:dde-topic="x" '
        'office:dde-item="y"/>',
    )
    assert extract("odt", linked, LIMITS).active_content
    assert extract("odt", dde, LIMITS).active_content


def test_opendocument_hyperlinks_and_own_pictures_arent_active_content() -> None:
    data = files.odt(
        "Hello",
        body_extra=f'<text:p><text:a xmlns:xlink="{_XLINK}" xlink:href="https://example.com">'
        "link</text:a></text:p>"
        f'<draw:image xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" '
        f'xmlns:xlink="{_XLINK}" xlink:href="Pictures/1.png"/>',
    )
    assert not extract("odt", data, LIMITS).active_content


# --- Review N1: UTF-16 text and bytes before a PDF's header ----------------------------------
@pytest.mark.parametrize("encoding", ["utf-16", "utf-16-le", "utf-16-be"])
def test_utf16_text_is_read(encoding: str) -> None:
    bom = {"utf-16": b"", "utf-16-le": b"\xff\xfe", "utf-16-be": b"\xfe\xff"}[encoding]
    result = extract("csv", bom + "item\tprice\r\nCafé\t12\r\n".encode(encoding), LIMITS)
    assert result.state == "done"
    assert result.text == "item\tprice\r\nCafé\t12"


def test_a_pdf_with_bytes_before_its_header_is_read() -> None:
    result = extract("pdf", b"\r\n\xef\xbb\xbf" + files.pdf("Signed form of tender"), LIMITS)
    assert result.state == "done"
    assert result.text == "Signed form of tender"


# --- The child process -------------------------------------------------------------------------
def test_the_childs_environment_is_allow_listed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOUNDINGS_DATABASE_URL", "postgresql://secret")
    monkeypatch.setenv("SOUNDINGS_SECRET_KEY", "secret")
    monkeypatch.setenv("SOUNDINGS_SMTP_PASSWORD", "secret")
    monkeypatch.setenv("LC_ALL", "C.UTF-8")
    env = _child_environment("/tmp/scratch")  # noqa: S108
    assert not any(name.startswith("SOUNDINGS_") for name in env)
    assert env["TMPDIR"] == env["HOME"] == "/tmp/scratch"  # noqa: S108
    assert env["LC_ALL"] == "C.UTF-8"
    allowed = {"PATH", "LANG", "LANGUAGE", "TZ", "TMPDIR", "HOME", "PYTHONDONTWRITEBYTECODE"}
    assert {name for name in env if not name.startswith("LC_")} <= allowed


async def test_the_child_reads_stdin_and_answers_on_stdout() -> None:
    outcome = await run_child("docx", files.docx("From the child", "Line two"))
    assert outcome == ChildOutcome(
        state=ExtractionState.DONE, text="From the child\nLine two", truncated=False
    )


async def test_the_child_sees_no_secrets(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """The child runs ``python -I -B -m app.bids.extract_child`` with the allow-listed
    environment: a stand-in interpreter that prints its environment shows what it gets."""
    monkeypatch.setenv("SOUNDINGS_SECRET_KEY", "must-not-leak")
    script = tmp_path / "python"
    script.write_text(
        "#!/bin/sh\ncat > /dev/null\nenv | grep -c SOUNDINGS_ > /dev/null && exit 3\n"
        'printf \'{"state":"no_text","error":null,"text":"","truncated":false,'
        '"active_content":false}\'\n'
    )
    script.chmod(0o755)
    outcome = await run_child("txt", b"hello", python=str(script))
    assert outcome.state is ExtractionState.NO_TEXT


async def test_the_time_limit_kills_the_child() -> None:
    scratch = tempfile.gettempdir()
    before = set(os.listdir(scratch))
    outcome = await run_child("txt", b"hello", time_limit=0.01)
    assert outcome == ChildOutcome.failed(ExtractionError.TIMEOUT)
    left = set(os.listdir(scratch)) - before
    assert not any(name.startswith("soundings-extract-") for name in left)


async def test_the_time_limit_holds_when_the_child_stops_reading(tmp_path: Any) -> None:
    """Review L1: a child that never reads stdin (a full pipe) must not hold the feeder,
    and so the worker, past the time limit."""
    script = tmp_path / "python"
    script.write_text("#!/bin/sh\nsleep 30\n")
    script.chmod(0o755)
    started = asyncio.get_running_loop().time()
    outcome = await run_child("txt", b"x" * (4 * 1024 * 1024), python=str(script), time_limit=1)
    assert outcome == ChildOutcome.failed(ExtractionError.TIMEOUT)
    assert asyncio.get_running_loop().time() - started < 8


async def test_the_memory_cap() -> None:
    big = b"a" * (20 * 1024 * 1024)
    outcome = await run_child(
        "txt", big, limits={"memory_bytes": 64 * 1024 * 1024, "max_chars": 30_000_000}
    )
    assert outcome == ChildOutcome.failed(ExtractionError.MEMORY)


async def test_a_crash_is_reported_as_one(tmp_path: Any) -> None:
    script = tmp_path / "python"
    script.write_text("#!/bin/sh\ncat > /dev/null\nkill -SEGV $$\n")
    script.chmod(0o755)
    assert (await run_child("txt", b"x", python=str(script))).crashed
    garbage = tmp_path / "garbage"
    garbage.write_text("#!/bin/sh\ncat > /dev/null\necho not json\n")
    garbage.chmod(0o755)
    assert (await run_child("txt", b"x", python=str(garbage))).crashed


async def test_output_is_read_up_to_a_bound() -> None:
    reader = asyncio.StreamReader()
    reader.feed_data(b"x" * 1000)
    reader.feed_eof()
    with pytest.raises(_TooMuchOutput):
        await _read(reader, 999)


async def test_too_much_output_kills_the_child(tmp_path: Any) -> None:
    script = tmp_path / "python"
    script.write_text("#!/bin/sh\ncat > /dev/null\nyes x | head -c 2000000\n")
    script.chmod(0o755)
    outcome = await run_child("txt", b"x", python=str(script), limits={"max_chars": 100})
    assert outcome == ChildOutcome.failed(ExtractionError.INTERNAL_ERROR)


# --- The job -------------------------------------------------------------------------------------
@pytest.fixture
async def stored(api: AsUser, crew: Crew, db_session: AsyncSession) -> Callable[..., Any]:
    owner: Api = await api(crew.owner)
    view = await start(owner, crew)
    await open_call(owner, crew, view)
    bid = await add_bid(owner, crew, "Northwind Data Ltd", price="120000.00")

    async def store(data: bytes, kind: BidDocumentType, **values: Any) -> UUID:
        call_id = UUID(view["call"]["id"])
        document = BidDocument(
            id=uuid4(),
            bid_id=UUID(bid["id"]),
            call_id=call_id,
            filename=f"doc.{kind.value}",
            type=kind,
            content_type="application/octet-stream",
            size_bytes=len(data),
            sha256=uuid4().hex + uuid4().hex,
            extraction_state=ExtractionState.PENDING,
            **values,
        )
        db_session.add(document)
        await db_session.flush()
        db_session.add(BidDocumentContent(document_id=document.id, data=data))
        await db_session.commit()
        return document.id

    store.bid_id = UUID(bid["id"])  # type: ignore[attr-defined]
    store.owner = owner  # type: ignore[attr-defined]
    return store


async def _document(db: AsyncSession, document_id: UUID) -> BidDocument:
    document = await db.get(BidDocument, document_id, populate_existing=True)
    assert document is not None
    return document


async def test_the_job_stores_the_text(
    stored: Callable[..., Any], app: FastAPI, db_session: AsyncSession, crew: Crew
) -> None:
    document_id = await stored(files.docx("We accept your standard terms."), BidDocumentType.DOCX)
    done: list[UUID] = []

    async def on_done(bid_id: UUID) -> None:
        done.append(bid_id)

    state = await extract_document(app.state.sessionmaker, document_id, on_done=on_done)

    assert state is ExtractionState.DONE
    document = await _document(db_session, document_id)
    assert document.extraction_attempts == 1
    assert document.text_chars == len("We accept your standard terms.")
    assert document.extracted_at is not None
    assert (
        await db_session.scalar(
            select(BidDocumentText.text).where(BidDocumentText.document_id == document_id)
        )
        == "We accept your standard terms."
    )
    assert done == [stored.bid_id]  # type: ignore[attr-defined]
    owner = stored.owner  # type: ignore[attr-defined]
    page = ok(
        await owner.get(
            f"/ideas/{crew.key}/bid-call/bids/{stored.bid_id}/documents/{document_id}/text"  # type: ignore[attr-defined]
        )
    )
    assert page["text"] == "We accept your standard terms."
    assert page["page_count"] == 1
    # Run again (a duplicate job): nothing changes.
    assert await extract_document(app.state.sessionmaker, document_id) is ExtractionState.DONE
    assert (await _document(db_session, document_id)).extraction_attempts == 1


async def test_failures_and_no_text_are_stored(
    stored: Callable[..., Any], app: FastAPI, db_session: AsyncSession
) -> None:
    image = await stored(files.png(), BidDocumentType.PNG)
    broken = await stored(b"%PDF-1.4 garbage", BidDocumentType.PDF)
    assert await extract_document(app.state.sessionmaker, image) is ExtractionState.NO_TEXT
    assert await extract_document(app.state.sessionmaker, broken) is ExtractionState.FAILED
    failed = await _document(db_session, broken)
    assert failed.extraction_error is ExtractionError.DAMAGED
    assert failed.text_chars is None


async def test_crashes_count_and_end_in_internal_error(
    stored: Callable[..., Any],
    app: FastAPI,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_id = await stored(files.pdf("x"), BidDocumentType.PDF)

    async def crash(*_args: Any, **_kwargs: Any) -> ChildOutcome:
        return ChildOutcome(crashed=True)

    monkeypatch.setattr(extraction, "run_child", crash)
    for attempt in range(1, BID_EXTRACTION_MAX_ATTEMPTS):
        assert await extract_document(app.state.sessionmaker, document_id) is None
        document = await _document(db_session, document_id)
        assert document.extraction_attempts == attempt
        assert document.extraction_state is ExtractionState.PENDING
    retries = await db_session.scalar(
        text(
            "SELECT count(*) FROM procrastinate_jobs WHERE task_name = 'extract_bid_document'"
            " AND scheduled_at IS NOT NULL"
        )
    )
    assert retries == BID_EXTRACTION_MAX_ATTEMPTS - 1
    assert await extract_document(app.state.sessionmaker, document_id) is ExtractionState.FAILED
    document = await _document(db_session, document_id)
    assert document.extraction_error is ExtractionError.INTERNAL_ERROR
    assert document.extraction_attempts == BID_EXTRACTION_MAX_ATTEMPTS


async def test_a_worker_that_died_mid_way_counted_its_attempt(
    stored: Callable[..., Any], app: FastAPI, db_session: AsyncSession
) -> None:
    """The attempt is committed before the child starts: a document whose attempts ran out
    while the worker kept dying is failed without running again."""
    document_id = await stored(
        files.pdf("x"), BidDocumentType.PDF, extraction_attempts=BID_EXTRACTION_MAX_ATTEMPTS
    )
    assert await extract_document(app.state.sessionmaker, document_id) is ExtractionState.FAILED
    assert (await _document(db_session, document_id)).extraction_error is (
        ExtractionError.INTERNAL_ERROR
    )


async def test_the_sweep_requeues_lost_documents(
    stored: Callable[..., Any], app: FastAPI, db_session: AsyncSession
) -> None:
    old = await stored(files.pdf("x"), BidDocumentType.PDF)
    fresh = await stored(files.pdf("y"), BidDocumentType.PDF)
    document = await _document(db_session, old)
    document.uploaded_at = utcnow().replace(year=2025)
    await db_session.commit()

    assert await sweep_documents(app.state.sessionmaker) == 1
    assert await sweep_documents(app.state.sessionmaker) == 0  # its job is waiting now
    jobs = list(
        await db_session.scalars(
            text(
                "SELECT args->>'document_id' FROM procrastinate_jobs"
                " WHERE task_name = 'extract_bid_document'"
            )
        )
    )
    assert jobs == [str(old)]
    assert fresh not in [UUID(j) for j in jobs]
    assert await db_session.scalar(select(func.count()).select_from(BidDocument)) == 2


async def test_a_calls_backlog_waits_behind_other_calls(
    stored: Callable[..., Any], app: FastAPI, db_session: AsyncSession
) -> None:
    """Review L6: one worker extracts one document at a time, so a call with hundreds of
    documents waiting would hold up every other call for hours. Each job's priority is
    minus the number of the call's older documents still waiting: a call's first document
    goes before another call's hundredth."""
    from datetime import timedelta

    from app.bids.extraction import defer_extraction

    ids = [await stored(files.pdf(f"Doc {n}"), BidDocumentType.PDF) for n in range(3)]
    for offset, document_id in enumerate(ids):
        document = await _document(db_session, document_id)
        document.uploaded_at = utcnow() - timedelta(minutes=10 - offset)
    await db_session.commit()
    first = await _document(db_session, ids[0])
    first.extraction_state = ExtractionState.NO_TEXT  # read already: it no longer counts
    first.extracted_at = utcnow()
    await db_session.commit()
    for document_id in reversed(ids[1:]):
        await defer_extraction(db_session, document_id)
    await db_session.commit()

    rows = (
        await db_session.execute(
            text(
                "SELECT args->>'document_id', priority FROM procrastinate_jobs"
                " WHERE task_name = 'extract_bid_document'"
            )
        )
    ).all()
    assert {UUID(document): priority for document, priority in rows} == {ids[1]: 0, ids[2]: -1}
