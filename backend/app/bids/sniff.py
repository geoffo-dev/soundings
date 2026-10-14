"""What an uploaded bid document **is**, from its bytes alone (contract-phase10 section 6.1,
ADR 0018 decision 4; review M5: bounded, and never a PDF parser in the API).

* ``%PDF-`` is a PDF (never parsed here: an encrypted PDF is accepted and its extraction ends
  ``failed`` ``encrypted``), also within the first 1,024 bytes after bytes without a NUL
  (review N1, as Acrobat reads them); the PNG and JPEG signatures are images.
* ``PK\\x03\\x04`` is a ZIP container (OOXML, OpenDocument), inspected with fixed bounds:

  1. the end-of-central-directory record, found in the file's last 64 KiB like
     :mod:`zipfile` finds it (ZIP64 too): more than :data:`BID_ARCHIVE_MAX_ENTRIES` entries
     is refused **before anything else**;
  2. the central directory, walked record by record (never the local headers or the sizes
     they claim) and refused past the same count, so a record that lies about its count
     can't make :mod:`zipfile` build millions of entries; a name matching
     :data:`BID_REFUSED_ARCHIVE_ENTRY` is ``macro_document``;
  3. at most two entries decompressed (stored or deflated, from the offsets and sizes the
     central directory gives), each with a bounded read: ``[Content_Types].xml`` (up to
     :data:`BID_CONTENT_TYPES_MAX_BYTES`; bigger is refused) and ``mimetype`` (up to
     :data:`BID_ODF_MIMETYPE_MAX_BYTES`), checked **by substring**, never with an XML parser.
     :mod:`zipfile` isn't used here at all (its own end-record and directory logic could
     read a different directory from the one checked).

* two entries with one name (compared without case) are refused (review L3); so are
  macro and dialog sheets, by name or by content type.
* anything else that decodes as UTF-8, or else Windows-1252, without a NUL byte, or as
  UTF-16 after its byte order mark without a NUL character (review N1), is plain text:
  ``csv`` when the given name ends in ``.csv`` (any case), ``txt`` otherwise.

An OLE compound file (old Office formats, and Office files encrypted with a password),
an empty file, an executable (NUL bytes) and every other format are refused. CPU-bound on
up to 25 MiB: the upload route calls :func:`sniff` off the event loop
(``anyio.to_thread.run_sync``).
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from typing import Final

from app.models.enums import BidDocumentType
from app.schemas.bids import (
    BID_ARCHIVE_MAX_ENTRIES,
    BID_CONTENT_TYPES_MAX_BYTES,
    BID_ODF_MIMETYPE_MAX_BYTES,
    BID_REFUSED_ARCHIVE_ENTRY,
)

__all__ = [
    "MACRO_DOCUMENT",
    "UNSUPPORTED",
    "RefusedDocument",
    "archive_entry_count",
    "central_directory_names",
    "sniff",
]

UNSUPPORTED: Final = "unsupported_document_type"
MACRO_DOCUMENT: Final = "macro_document"

_PDF: Final = b"%PDF-"
_PNG: Final = b"\x89PNG\r\n\x1a\n"
_JPEG: Final = b"\xff\xd8\xff"
_ZIP: Final = b"PK\x03\x04"
_OLE: Final = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

_EOCD: Final = b"PK\x05\x06"
_EOCD_SIZE: Final = 22
_ZIP64_LOCATOR: Final = b"PK\x06\x07"
_ZIP64_LOCATOR_SIZE: Final = 20
_ZIP64_EOCD: Final = b"PK\x06\x06"
_CENTRAL: Final = b"PK\x01\x02"
_CENTRAL_SIZE: Final = 46
_MAX_COMMENT: Final = 0xFFFF

_CONTENT_TYPES: Final = "[Content_Types].xml"
_MIMETYPE: Final = "mimetype"
_OOXML_MAIN: Final[dict[str, BidDocumentType]] = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml": (
        BidDocumentType.DOCX
    ),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml": (
        BidDocumentType.XLSX
    ),
    "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml": (
        BidDocumentType.PPTX
    ),
}
_MACRO_CONTENT_TYPES: Final = ("macroenabled", "macrosheet", "dialogsheet")
"""Substrings of a lower-cased ``[Content_Types].xml`` that make it ``macro_document``:
macro-enabled formats, Excel 4.0 macro sheets (``macrosheet+xml``,
``intlmacrosheet+xml``) and dialog sheets (review L3)."""
_ODF: Final[dict[str, BidDocumentType]] = {
    "application/vnd.oasis.opendocument.text": BidDocumentType.ODT,
    "application/vnd.oasis.opendocument.spreadsheet": BidDocumentType.ODS,
}


class RefusedDocument(Exception):
    """The upload is refused (415) with ``code``: ``unsupported_document_type`` or
    ``macro_document``. Never carries the file's content."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _unsupported() -> RefusedDocument:
    return RefusedDocument(UNSUPPORTED)


@dataclass(frozen=True, slots=True)
class _Directory:
    entries: int
    size: int
    offset: int
    concat: int
    """Bytes before the archive (a self-extractor's stub): every stored offset shifts by it."""


def _end_record(data: bytes) -> _Directory:
    """The end-of-central-directory record, searched in the last 64 KiB, and the ZIP64
    record when a ZIP64 locator sits right before it."""
    start = max(0, len(data) - _EOCD_SIZE - _MAX_COMMENT)
    at = data.rfind(_EOCD, start)
    if at < 0 or len(data) - at < _EOCD_SIZE:
        raise _unsupported()
    (_sig, _disk, _cd_disk, _here, entries, size, offset, _comment) = struct.unpack(
        "<4sHHHHIIH", data[at : at + _EOCD_SIZE]
    )
    location = at
    locator = at - _ZIP64_LOCATOR_SIZE
    if locator >= 0 and data[locator : locator + 4] == _ZIP64_LOCATOR:
        (_sig64, _disk64, record, _disks) = struct.unpack(
            "<4sIQI", data[locator : locator + _ZIP64_LOCATOR_SIZE]
        )
        if record + 56 > locator or data[record : record + 4] != _ZIP64_EOCD:
            raise _unsupported()
        (entries, size, offset) = struct.unpack("<QQQ", data[record + 32 : record + 56])
        location = record
    elif entries == 0xFFFF or size == 0xFFFFFFFF or offset == 0xFFFFFFFF:
        raise _unsupported()
    concat = location - size - offset
    if concat < 0:
        raise _unsupported()
    return _Directory(entries=entries, size=size, offset=offset, concat=concat)


@dataclass(frozen=True, slots=True)
class _Entry:
    name: str
    flags: int
    method: int
    compressed: int
    local: int


def _zip64_fields(extra: bytes, wanted: int) -> list[int]:
    """The 8-byte values of a ZIP64 extra field (header 0x0001), the first ``wanted``."""
    at = 0
    while at + 4 <= len(extra):
        header, length = struct.unpack_from("<HH", extra, at)
        if header == 0x0001:
            body = extra[at + 4 : at + 4 + length]
            if len(body) < 8 * wanted:
                raise _unsupported()
            return list(struct.unpack_from(f"<{wanted}Q", body))
        at += 4 + length
    raise _unsupported()


def _central_directory(data: bytes) -> tuple[_Directory, list[_Entry]]:
    directory = _end_record(data)
    if directory.entries > BID_ARCHIVE_MAX_ENTRIES:
        raise _unsupported()
    at = directory.offset + directory.concat
    stop = at + directory.size
    entries: list[_Entry] = []
    while at < stop:
        if len(entries) >= BID_ARCHIVE_MAX_ENTRIES:
            raise _unsupported()  # the end record's count lied
        record = data[at : at + _CENTRAL_SIZE]
        if len(record) < _CENTRAL_SIZE or record[:4] != _CENTRAL:
            raise _unsupported()
        flags, method = struct.unpack_from("<HH", record, 8)
        compressed, uncompressed = struct.unpack_from("<II", record, 20)
        name_length, extra_length, comment_length = struct.unpack_from("<HHH", record, 28)
        local = struct.unpack_from("<I", record, 42)[0]
        tail = at + _CENTRAL_SIZE
        raw = data[tail : tail + name_length]
        extra = data[tail + name_length : tail + name_length + extra_length]
        if len(raw) < name_length or len(extra) < extra_length:
            raise _unsupported()
        if 0xFFFFFFFF in (compressed, uncompressed, local):
            wanted = [uncompressed, compressed, local].count(0xFFFFFFFF)
            values = iter(_zip64_fields(extra, wanted))
            if uncompressed == 0xFFFFFFFF:
                next(values)
            if compressed == 0xFFFFFFFF:
                compressed = next(values)
            if local == 0xFFFFFFFF:
                local = next(values)
        name = raw.decode("utf-8" if flags & 0x800 else "cp437", errors="replace")
        entries.append(_Entry(name, flags, method, compressed, local + directory.concat))
        at = tail + name_length + extra_length + comment_length
    return directory, entries


def archive_entry_count(data: bytes) -> int:
    """The entry count the end-of-central-directory record claims (415 when there is
    none). Read first: more than :data:`BID_ARCHIVE_MAX_ENTRIES` is refused before
    anything else is looked at."""
    return _end_record(data).entries


def central_directory_names(data: bytes) -> list[str]:
    """The entry names of the central directory, walked record by record within the size
    the end record gives, at most :data:`BID_ARCHIVE_MAX_ENTRIES` records (more, or a
    malformed record: 415). Never the local headers."""
    return [entry.name for entry in _central_directory(data)[1]]


def _read_entry(data: bytes, entry: _Entry, limit: int) -> bytes:
    """At most ``limit + 1`` bytes of one entry, decompressed (more than ``limit`` means
    "bigger"): stored or deflated, not encrypted, read from its local header's data with
    the central directory's compressed size."""
    if entry.flags & 0x1 or entry.method not in (0, 8):
        raise _unsupported()  # encrypted, or a compression Office files don't use
    header = data[entry.local : entry.local + 30]
    if len(header) < 30 or header[:4] != _ZIP:
        raise _unsupported()
    name_length, extra_length = struct.unpack_from("<HH", header, 26)
    begin = entry.local + 30 + name_length + extra_length
    body = data[begin : begin + entry.compressed]
    if entry.method == 0:
        return body[: limit + 1]
    try:
        return zlib.decompressobj(-zlib.MAX_WBITS).decompress(body, limit + 1)
    except zlib.error as error:
        raise _unsupported() from error


def _sniff_zip(data: bytes) -> BidDocumentType:
    if archive_entry_count(data) > BID_ARCHIVE_MAX_ENTRIES:
        raise _unsupported()
    _directory, entries = _central_directory(data)
    if any(BID_REFUSED_ARCHIVE_ENTRY.search(entry.name) for entry in entries):
        raise RefusedDocument(MACRO_DOCUMENT)
    # Two entries with one name (Office part names compare without case): readers disagree
    # on which one counts, so what is checked here might not be what is opened (review L3).
    if len({entry.name.casefold() for entry in entries}) != len(entries):
        raise _unsupported()
    by_name = {entry.name: entry for entry in entries}
    if _CONTENT_TYPES in by_name:
        raw = _read_entry(data, by_name[_CONTENT_TYPES], BID_CONTENT_TYPES_MAX_BYTES)
        if len(raw) > BID_CONTENT_TYPES_MAX_BYTES:
            raise _unsupported()
        text = raw.decode("utf-8", errors="replace").lower()
        if any(marker in text for marker in _MACRO_CONTENT_TYPES):
            raise RefusedDocument(MACRO_DOCUMENT)
        found = {kind for main, kind in _OOXML_MAIN.items() if main.lower() in text}
        if len(found) != 1:
            raise _unsupported()  # a template, another Office format, or ambiguous
        return found.pop()
    if _MIMETYPE in by_name:
        raw = _read_entry(data, by_name[_MIMETYPE], BID_ODF_MIMETYPE_MAX_BYTES)
        if len(raw) > BID_ODF_MIMETYPE_MAX_BYTES:
            raise _unsupported()
        kind = _ODF.get(raw.decode("ascii", errors="replace").strip())
        if kind is None:
            raise _unsupported()  # a template, a drawing, another OpenDocument type
        return kind
    raise _unsupported()


_UTF16_BOMS: Final = (b"\xff\xfe", b"\xfe\xff")
_PDF_HEADER_WITHIN: Final = 1024
"""Acrobat reads a PDF whose ``%PDF-`` starts within the first 1,024 bytes (review N1)."""


def _is_text(data: bytes) -> bool:
    if data.startswith(_UTF16_BOMS):
        # UTF-16 with a byte order mark (Excel's "Unicode Text"): text when it decodes
        # (an even length, no lone surrogates) to no NUL character (review N1).
        try:
            decoded = data.decode("utf-16")
        except UnicodeDecodeError:
            return False
        return "\x00" not in decoded
    if b"\x00" in data:
        return False
    for encoding in ("utf-8", "cp1252"):
        try:
            data.decode(encoding)
        except UnicodeDecodeError:
            continue
        return True
    return False


def _late_pdf_header(data: bytes) -> bool:
    """``%PDF-`` within the first 1,024 bytes after bytes that aren't binary (a mail
    gateway's line, a byte order mark), never after a NUL (an executable's stub), and a
    ``%%EOF`` in the last 1,024 bytes (so a text file that only mentions the header stays
    text)."""
    at = data.find(_PDF, 0, _PDF_HEADER_WITHIN + len(_PDF))
    return (
        0 < at <= _PDF_HEADER_WITHIN
        and b"\x00" not in data[:at]
        and b"%%EOF" in data[-_PDF_HEADER_WITHIN:]
    )


def sniff(data: bytes, filename: str) -> BidDocumentType:
    """The document's type from its bytes (``filename`` only labels plain text as CSV);
    :class:`RefusedDocument` (415) for anything not allowed."""
    if not data:
        raise _unsupported()
    if data.startswith(_PDF):
        return BidDocumentType.PDF
    if data.startswith(_PNG):
        return BidDocumentType.PNG
    if data.startswith(_JPEG):
        return BidDocumentType.JPEG
    if data.startswith(_ZIP):
        return _sniff_zip(data)
    if data.startswith(_OLE):
        raise _unsupported()  # old Office formats, and password-protected Office files
    if _late_pdf_header(data):
        return BidDocumentType.PDF
    if _is_text(data):
        return BidDocumentType.CSV if filename.lower().endswith(".csv") else BidDocumentType.TXT
    raise _unsupported()
