"""Bid documents (contract-phase10 section 6, ADR 0018): the upload, its checks and caps,
the link to a required-document must-have and the pricing mark, deleting, the download
and the extracted text.

**The upload** (``upload_bid_document``) reads the raw file as the request body, in this
order (review S5): authentication, the 404s and 403s (:func:`app.bids.access.load_call`,
``load_bid``), then an **upload slot** (:class:`UploadSlots`: at most
:data:`BID_UPLOADS_PER_PROCESS` per API process and one per person, else 503
``upload_busy``), then the body into one buffer with **no transaction open** (the route
ends the checks' transaction first), counted as it arrives
(``app.middleware.BodySizeLimitMiddleware`` gives this route alone
:data:`app.models.bid.BID_DOCUMENT_MAX_BYTES`: 413 ``content_too_large``) within
:data:`BID_UPLOAD_READ_TIMEOUT` and above :data:`UPLOAD_MIN_RATE` (408
``upload_timeout``); then its type from the bytes,
off the event loop (:func:`inspect`: :mod:`app.bids.sniff`, 415); then, in one short
transaction under the call's lock, the 422s (``invalid_must_have``) and the 409s (the
call's state, then 30 documents per bid, 500 MiB per call and 5 GiB per project with
extracted text counted, the same file twice) and the rows (:func:`add_document`). The
worker extracts its text afterwards (:mod:`app.bids.extraction`).

**Pricing documents** (section 6.4): marked at upload or later, or linked to a pricing
must-have (which they must then stay). Only ``bid.view_price`` reaches their file, text,
quotes and link (:func:`load_document`: 404 otherwise). Marking one deletes the bid's AI
assessments and cancels its active assess runs (the AI may have read it).

Downloads are always attachments with the type's media type (never the client's),
``nosniff``, a sandboxing CSP and ``private, no-store``, streamed from the database in
1 MiB chunks (:func:`download_response`).
"""

from __future__ import annotations

import hashlib
import math
import unicodedata
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Final
from urllib.parse import quote, unquote
from uuid import UUID, uuid4

import anyio
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import StreamingResponse
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import LargeBinary, Text, delete, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import ClientDisconnect

from app.authz import Rule
from app.bids import runs
from app.bids.access import LoadedCall, sees_price
from app.bids.extraction import defer_extraction
from app.bids.problems import conflict, unprocessable
from app.bids.service import sync_document_must_have
from app.bids.sniff import RefusedDocument, sniff
from app.db import SessionMaker
from app.domain.principal import Principal
from app.errors import ProblemError
from app.models.base import utcnow
from app.models.bid import (
    Bid,
    BidAiAssessment,
    BidCall,
    BidCallMustHave,
    BidDocument,
    BidDocumentContent,
    BidDocumentText,
)
from app.models.enums import BidDocumentType, ExtractionState, MustHaveKind
from app.models.idea import Idea
from app.schemas.bids import (
    BID_CALL_STORAGE_MAX_BYTES,
    BID_DOCUMENT_TYPES,
    BID_DOCUMENTS_PER_BID_MAX,
    BID_FILENAME_MAX_LENGTH,
    BID_PROJECT_STORAGE_MAX_BYTES,
    BID_TEXT_PAGE_CHARS,
    BID_UPLOAD_READ_TIMEOUT,
    BID_UPLOADS_PER_PROCESS,
    BidDocumentFilename,
    BidDocumentUpdate,
)
from app.schemas.bids import BidDocumentText as BidDocumentTextOut
from app.services import audit

__all__ = [
    "DOWNLOAD_CHUNK_BYTES",
    "UPLOAD_MIN_RATE",
    "UPLOAD_RETRY_AFTER",
    "UploadSlots",
    "add_document",
    "content_disposition",
    "delete_document",
    "document_text",
    "download_response",
    "inspect",
    "load_document",
    "page_count",
    "read_body",
    "stored_filename",
    "unlink_documents",
    "update_document",
    "upload_filename",
    "upload_slots",
]

DOWNLOAD_CHUNK_BYTES: Final = 1024 * 1024
"""Downloads are read from the database in chunks of this size (``STORAGE EXTERNAL``
makes each a cheap range read)."""
UPLOAD_RETRY_AFTER: Final = 5
"""``Retry-After`` of a 503 ``upload_busy``."""
DOWNLOAD_CSP: Final = "default-src 'none'; sandbox"


# --- Names ---------------------------------------------------------------------------------
def stored_filename(given: str, kind: BidDocumentType) -> str:
    """The stored name: the given one (already validated: one line, no folders, no leading
    dot), ending with an extension of the type its bytes are. The type's first extension
    is appended when the name has none of them (``invoice.exe`` holding a PDF is stored as
    ``invoice.exe.pdf``); when that would pass :data:`BID_FILENAME_MAX_LENGTH`, the stem is
    cut so both fit (review S12)."""
    extensions = BID_DOCUMENT_TYPES[kind].extensions
    if given.lower().endswith(extensions):
        return given
    extension = extensions[0]
    stem = given[: BID_FILENAME_MAX_LENGTH - len(extension)].rstrip()
    return (stem or "document") + extension


_ASCII_SAFE: Final = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 ._-()[]+,"
)


def content_disposition(filename: str) -> str:
    """``attachment`` with an ASCII fallback name (accents dropped, anything unusual
    replaced by ``_``) and the stored name in UTF-8 (RFC 6266 / 5987). Never ``inline``."""
    folded = unicodedata.normalize("NFKD", filename).encode("ascii", "ignore").decode("ascii")
    fallback = "".join(c if c in _ASCII_SAFE else "_" for c in folded).strip() or "document"
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"


def page_count(document: BidDocument) -> int:
    """Pages of :data:`BID_TEXT_PAGE_CHARS` characters of its text (0 unless done)."""
    if document.extraction_state is not ExtractionState.DONE:
        return 0
    return math.ceil((document.text_chars or 0) / BID_TEXT_PAGE_CHARS)


# --- The upload, before the transaction --------------------------------------------------------
_FILENAME: Final = TypeAdapter(BidDocumentFilename)


def upload_filename(query: str | None, header: str | None) -> str:
    """The upload's file name: the ``X-Filename`` header (percent-encoded UTF-8, ASCII on
    the wire; review N2: proxies log query strings) when sent, else the ``filename`` query
    parameter (already validated); 422 ``validation_error`` naming the one to blame."""
    if header is None:
        if query is None:
            raise RequestValidationError(
                [{"loc": ("query", "filename"), "msg": "Field required", "type": "missing"}]
            )
        return query
    try:
        if not header.isascii():
            raise UnicodeError
        decoded = unquote(header, encoding="utf-8", errors="strict")
    except UnicodeError:
        raise RequestValidationError(
            [
                {
                    "loc": ("header", "X-Filename"),
                    "msg": "The name must be percent-encoded UTF-8.",
                    "type": "value_error",
                }
            ]
        ) from None
    try:
        return _FILENAME.validate_python(decoded)
    except ValidationError as invalid:
        raise RequestValidationError(
            [
                {"loc": ("header", "X-Filename", *e["loc"]), "msg": e["msg"], "type": e["type"]}
                for e in invalid.errors(include_input=False, include_url=False)
            ]
        ) from None


class UploadSlots:
    """At most ``size`` uploads read and checked at once in this API process (each holds
    up to 25 MiB in memory), and one per person (review L4: one person can't hold them
    all; the SPA sends one file at a time): beyond, 503 ``upload_busy`` at once (never
    queued)."""

    def __init__(self, size: int = BID_UPLOADS_PER_PROCESS) -> None:
        self.size = size
        self.busy = 0
        self.holders: set[UUID] = set()

    @contextmanager
    def take(self, holder: UUID | None = None) -> Iterator[None]:
        if self.busy >= self.size or (holder is not None and holder in self.holders):
            raise ProblemError(
                503,
                "upload_busy",
                detail="Other uploads are in progress. Try again in a few seconds.",
                headers={"Retry-After": str(UPLOAD_RETRY_AFTER)},
            )
        self.busy += 1
        if holder is not None:
            self.holders.add(holder)
        try:
            yield
        finally:
            self.busy -= 1
            if holder is not None:
                self.holders.discard(holder)


def upload_slots(request: Request) -> UploadSlots:
    """The app's slots (created on first use)."""
    slots = getattr(request.app.state, "bid_upload_slots", None)
    if not isinstance(slots, UploadSlots):
        slots = UploadSlots()
        request.app.state.bid_upload_slots = slots
    return slots


UPLOAD_MIN_RATE: Final = (15.0, 16 * 1024)
"""Review L4: after this many seconds a body must have arrived at this many bytes a second
on average (a 128 kbit/s line), else 408 ``upload_timeout`` at once: a trickle can't hold
an upload slot for the whole 120 s."""


async def read_body(request: Request) -> bytes:
    """The whole body into one buffer within :data:`BID_UPLOAD_READ_TIMEOUT`, and never
    slower than :data:`UPLOAD_MIN_RATE` (both 408 ``upload_timeout``); the size limit is
    the middleware's (413). The app's ``bid_upload_read_timeout`` state (seconds) and
    ``bid_upload_min_rate`` (grace seconds, bytes a second) replace them in tests."""
    state = request.app.state
    timeout = float(
        getattr(state, "bid_upload_read_timeout", BID_UPLOAD_READ_TIMEOUT.total_seconds())
    )
    grace, floor = getattr(state, "bid_upload_min_rate", UPLOAD_MIN_RATE)
    buffer = bytearray()
    started = anyio.current_time()
    deadline = started + timeout
    chunks = request.stream().__aiter__()
    try:
        while True:
            # The next chunk must come before the average falls under the floor.
            due = min(deadline, started + max(float(grace), len(buffer) / float(floor)))
            with anyio.fail_after(max(due - anyio.current_time(), 0)):
                try:
                    chunk = await chunks.__anext__()
                except StopAsyncIteration:
                    break
            buffer += chunk
    except TimeoutError:
        raise ProblemError(
            408,
            "upload_timeout",
            detail="The file didn't arrive in time. Try again on a faster connection.",
            headers={"Connection": "close"},
        ) from None
    except ClientDisconnect:
        raise ProblemError(400, "bad_request", detail="The upload was interrupted.") from None
    data = bytes(buffer)
    del buffer
    return data


@dataclass(frozen=True, slots=True)
class Inspected:
    type: BidDocumentType
    sha256: str


def _inspect(data: bytes, filename: str) -> Inspected:
    return Inspected(type=sniff(data, filename), sha256=hashlib.sha256(data).hexdigest())


async def inspect(data: bytes, filename: str) -> Inspected:
    """The type (415 ``unsupported_document_type`` / ``macro_document``) and SHA-256,
    off the event loop (up to 25 MiB of hashing, decoding and archive reading)."""
    try:
        return await anyio.to_thread.run_sync(_inspect, data, filename)
    except RefusedDocument as refused:
        detail = (
            "Office files with macros, ActiveX controls or embedded packages, and "
            "OpenDocument files with scripts, can't be uploaded."
            if refused.code == "macro_document"
            else (
                "Upload a PDF, Word, Excel, PowerPoint, OpenDocument text or spreadsheet, "
                "plain text, CSV, PNG or JPEG file."
            )
        )
        raise ProblemError(415, refused.code, detail=detail) from None


# --- The upload's transaction -----------------------------------------------------------------
async def _must_have(
    db: AsyncSession, call_id: UUID, must_have_id: UUID | None, pricing: bool | None
) -> tuple[BidCallMustHave | None, bool]:
    """The document must-have a file is linked to and its pricing mark: a confirmation or
    another call's must-have, or ``pricing=false`` with a pricing must-have, is 422
    ``invalid_must_have``. ``pricing=None`` follows the must-have (false without one)."""
    if must_have_id is None:
        return None, bool(pricing)
    must_have: BidCallMustHave | None = await db.scalar(
        select(BidCallMustHave).where(
            BidCallMustHave.id == must_have_id, BidCallMustHave.call_id == call_id
        )
    )
    if must_have is None or must_have.kind is not MustHaveKind.DOCUMENT:
        raise unprocessable("invalid_must_have", loc=["query", "must_have_id"])
    if must_have.pricing:
        if pricing is False:
            raise unprocessable("invalid_must_have", loc=["query", "pricing"])
        return must_have, True
    return must_have, bool(pricing)


def _stored_bytes() -> Any:
    return func.coalesce(
        func.sum(BidDocument.size_bytes + func.coalesce(BidDocument.text_chars, 0)), 0
    )


async def _check_caps(
    db: AsyncSession, call: BidCall, bid: Bid, project_id: UUID, size: int, sha256: str
) -> None:
    """The 409s of an upload, in the contract's order (the call is locked, so the per-bid
    and per-call counts can't race; the per-project one is a bound, not a lock)."""
    documents = int(
        await db.scalar(
            select(func.count()).select_from(BidDocument).where(BidDocument.bid_id == bid.id)
        )
        or 0
    )
    if documents >= BID_DOCUMENTS_PER_BID_MAX:
        raise conflict("too_many_documents")
    used_call = int(
        await db.scalar(select(_stored_bytes()).where(BidDocument.call_id == call.id)) or 0
    )
    if used_call + size > BID_CALL_STORAGE_MAX_BYTES:
        raise conflict("call_storage_full")
    used_project = int(
        await db.scalar(
            select(_stored_bytes())
            .select_from(BidDocument)
            .join(BidCall, BidCall.id == BidDocument.call_id)
            .join(Idea, Idea.id == BidCall.idea_id)
            .where(Idea.project_id == project_id)
        )
        or 0
    )
    if used_project + size > BID_PROJECT_STORAGE_MAX_BYTES:
        raise conflict("project_storage_full")
    duplicate = await db.scalar(
        select(exists().where(BidDocument.bid_id == bid.id, BidDocument.sha256 == sha256))
    )
    if duplicate:
        raise conflict("duplicate_document")


async def add_document(
    db: AsyncSession,
    principal: Principal,
    loaded: LoadedCall,
    bid: Bid,
    *,
    data: bytes,
    inspected: Inspected,
    filename: str,
    must_have_id: UUID | None,
    pricing: bool | None,
) -> BidDocument:
    """The upload's rows (``loaded`` with ``write=True``, ``bid`` locked): the 422s, the
    deferred 409s and the call's state, the caps, then the document (``pending``), its
    bytes, the must-have's result, the audit entry and the extraction job."""
    call = loaded.call
    must_have, pricing_mark = await _must_have(db, call.id, must_have_id, pricing)
    loaded.require_not_finished()
    await _check_caps(db, call, bid, loaded.idea.project_id, len(data), inspected.sha256)
    info = BID_DOCUMENT_TYPES[inspected.type]
    document = BidDocument(
        id=uuid4(),
        bid_id=bid.id,
        call_id=call.id,
        must_have_id=must_have.id if must_have is not None else None,
        filename=stored_filename(filename, inspected.type),
        type=inspected.type,
        content_type=info.media_type,
        size_bytes=len(data),
        sha256=inspected.sha256,
        pricing=pricing_mark,
        uploaded_by_id=principal.user_id,
        uploaded_at=utcnow(),
        extraction_state=ExtractionState.PENDING,
    )
    db.add(document)
    await db.flush()  # the composite foreign keys need the row before its content
    db.add(BidDocumentContent(document_id=document.id, data=data))
    await db.flush()
    if must_have is not None:
        await sync_document_must_have(db, call.id, bid.id, must_have.id)
    await audit.record(
        db,
        "bid_document.upload",
        actor=principal,
        target_type="idea",
        target_id=loaded.idea.id,
        project_id=loaded.idea.project_id,
        details={
            "rule": Rule.BID_UPLOAD_DOCUMENT,
            "call_id": call.id,
            "bid_id": bid.id,
            "document_id": document.id,
            "type": inspected.type,
            "size_bytes": len(data),
            "must_have_id": document.must_have_id,
            "pricing": pricing_mark,
        },
    )
    await defer_extraction(db, document.id)
    await db.flush()
    return document


# --- Reading one ---------------------------------------------------------------------------
async def load_document(
    db: AsyncSession,
    principal: Principal,
    loaded: LoadedCall,
    bid: Bid,
    document_id: UUID,
    *,
    for_update: bool = False,
) -> BidDocument:
    """Step 4 of the order of checks: a document of this bid (another's or unknown: 404),
    and a pricing document only with ``bid.view_price`` (404 otherwise: it isn't there for
    them)."""
    statement = select(BidDocument).where(
        BidDocument.id == document_id,
        BidDocument.bid_id == bid.id,
        BidDocument.call_id == loaded.call.id,
    )
    if for_update:
        statement = statement.with_for_update()
    document: BidDocument | None = await db.scalar(
        statement.execution_options(populate_existing=True)
    )
    if document is None or (document.pricing and not sees_price(principal, loaded.resource)):
        from app.authz import not_found

        raise not_found()
    return document


async def document_text(db: AsyncSession, document: BidDocument, page: int) -> BidDocumentTextOut:
    """One page of the extracted text (Postgres counts characters as Python does). Page 1
    of a document without text is empty; past the last page: 404."""
    pages = page_count(document)
    if page > max(1, pages):
        from app.authz import not_found

        raise not_found()
    text = ""
    if pages:
        text = (
            await db.scalar(
                select(
                    func.substring(
                        BidDocumentText.text,
                        (page - 1) * BID_TEXT_PAGE_CHARS + 1,
                        BID_TEXT_PAGE_CHARS,
                        type_=Text,
                    )
                ).where(BidDocumentText.document_id == document.id)
            )
            or ""
        )
    return BidDocumentTextOut(
        document_id=document.id,
        state=document.extraction_state,
        page=page,
        page_count=pages,
        text=text,
        truncated=document.text_truncated,
    )


async def _chunks(sessionmaker: SessionMaker, document_id: UUID, size: int) -> AsyncIterator[bytes]:
    """The stored bytes in :data:`DOWNLOAD_CHUNK_BYTES` chunks, each read in a short
    transaction of its own (no connection is held while the client reads)."""
    offset = 0
    while offset < size:
        async with sessionmaker() as db:
            chunk = await db.scalar(
                select(
                    func.substring(
                        BidDocumentContent.data, offset + 1, DOWNLOAD_CHUNK_BYTES, type_=LargeBinary
                    )
                ).where(BidDocumentContent.document_id == document_id)
            )
        if not chunk:
            return  # deleted meanwhile: the client sees a short body (Content-Length)
        yield bytes(chunk)
        offset += len(chunk)


def download_response(sessionmaker: SessionMaker, document: BidDocument) -> StreamingResponse:
    """The file as stored: always an attachment, the type's media type, ``nosniff``, a
    sandboxing CSP and ``private, no-store``."""
    return StreamingResponse(
        _chunks(sessionmaker, document.id, document.size_bytes),
        media_type=BID_DOCUMENT_TYPES[document.type].media_type,
        headers={
            "Content-Disposition": content_disposition(document.filename),
            "Content-Length": str(document.size_bytes),
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": DOWNLOAD_CSP,
            "Cache-Control": "private, no-store",
        },
    )


# --- Changing one --------------------------------------------------------------------------
async def _clear_ai(
    db: AsyncSession, principal: Principal, call: BidCall, bid: Bid
) -> tuple[int, int]:
    """The bid's AI assessments deleted and its active assess runs cancelled (a pricing
    mark: the AI may have read the file). ``(assessments deleted, runs cancelled)``."""
    deleted = (
        await db.execute(
            delete(BidAiAssessment)
            .where(BidAiAssessment.bid_id == bid.id)
            .returning(BidAiAssessment.id)
            .execution_options(synchronize_session=False)
        )
    ).all()
    cancelled = await runs.cancel_assess_runs(db, principal, call, bid_id=bid.id)
    return len(deleted), cancelled


async def update_document(
    db: AsyncSession,
    principal: Principal,
    loaded: LoadedCall,
    bid: Bid,
    document: BidDocument,
    body: BidDocumentUpdate,
) -> None:
    """``bid.upload_document`` (session only), before the award: the link and the pricing
    mark, the complete new state (422 ``invalid_must_have``). Unlinking a must-have's last
    file makes it missing again; marking pricing deletes the bid's AI assessments and
    cancels its runs. Audited ``bid_document.update`` (what changed)."""
    call = loaded.call
    must_have, pricing = await _must_have(db, call.id, body.must_have_id, body.pricing)
    loaded.require_not_finished()
    new_link = must_have.id if must_have is not None else None
    changed = [
        name
        for name, before, after in (
            ("must_have_id", document.must_have_id, new_link),
            ("pricing", document.pricing, pricing),
        )
        if before != after
    ]
    if not changed:
        return
    old_link, was_pricing = document.must_have_id, document.pricing
    document.must_have_id, document.pricing = new_link, pricing
    await db.flush()
    for linked in {old_link, new_link} - {None}:
        assert linked is not None  # noqa: S101 - filtered above
        await sync_document_must_have(db, call.id, bid.id, linked)
    cleared = cancelled = 0
    if pricing and not was_pricing:
        cleared, cancelled = await _clear_ai(db, principal, call, bid)
    await audit.record(
        db,
        "bid_document.update",
        actor=principal,
        target_type="idea",
        target_id=loaded.idea.id,
        project_id=loaded.idea.project_id,
        details={
            "rule": Rule.BID_UPLOAD_DOCUMENT,
            "call_id": call.id,
            "bid_id": bid.id,
            "document_id": document.id,
            "fields": changed,
            "must_have_id": new_link,
            "pricing": pricing,
            "ai_assessments_deleted": cleared,
            "cancelled_runs": cancelled,
        },
    )
    await db.flush()


async def delete_document(
    db: AsyncSession, principal: Principal, loaded: LoadedCall, bid: Bid, document: BidDocument
) -> None:
    """``bid.upload_document`` (session only), before the award: the file, its text and
    its link (a must-have left without a file is missing again, a person's met included;
    a not met stays). Audited ``bid_document.delete``."""
    loaded.require_not_finished()
    linked = document.must_have_id
    await audit.record(
        db,
        "bid_document.delete",
        actor=principal,
        target_type="idea",
        target_id=loaded.idea.id,
        project_id=loaded.idea.project_id,
        details={
            "rule": Rule.BID_UPLOAD_DOCUMENT,
            "call_id": loaded.call.id,
            "bid_id": bid.id,
            "document_id": document.id,
            "type": document.type,
            "pricing": document.pricing,
        },
    )
    await db.delete(document)
    await db.flush()
    if linked is not None:
        await sync_document_must_have(db, loaded.call.id, bid.id, linked)


async def unlink_documents(
    db: AsyncSession, *, call_id: UUID | None = None, idea_id: UUID | None = None
) -> None:
    """Unlink a call's (or an idea's call's) documents from their must-haves before the
    call goes with everything in it: the documents' composite key to the must-haves is NO
    ACTION (the service unlinks before a must-have is deleted; review S7), and Postgres
    checks it while the cascade from the call deletes the must-haves before the bids'
    documents. For ``delete_call`` and ``delete_idea``."""
    from sqlalchemy import update

    if call_id is None and idea_id is None:  # pragma: no cover - a programming error
        raise ValueError("a call or an idea")
    where = (
        BidDocument.call_id == call_id
        if call_id is not None
        else BidDocument.call_id.in_(select(BidCall.id).where(BidCall.idea_id == idea_id))
    )
    await db.execute(
        update(BidDocument)
        .where(where, BidDocument.must_have_id.is_not(None))
        .values(must_have_id=None)
        .execution_options(synchronize_session=False)
    )
