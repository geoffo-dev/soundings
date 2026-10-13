"""What an upload is, from its bytes alone (contract-phase10 section 6.1, review M5): every
allowed type, every refusal, and the bounds of the ZIP inspection. Pure functions, no
database."""

from __future__ import annotations

import struct

import pytest

from app.bids.sniff import (
    MACRO_DOCUMENT,
    UNSUPPORTED,
    RefusedDocument,
    archive_entry_count,
    central_directory_names,
    sniff,
)
from app.models.enums import BidDocumentType
from app.schemas.bids import BID_ARCHIVE_MAX_ENTRIES, BID_CONTENT_TYPES_MAX_BYTES
from tests.bids import files
from tests.bids.files import DOCM_MAIN, DOTX_MAIN, zip_of


def refused(data: bytes, name: str = "file.bin") -> str:
    with pytest.raises(RefusedDocument) as caught:
        sniff(data, name)
    return caught.value.code


@pytest.mark.parametrize(
    ("data", "name", "expected"),
    [
        (files.pdf("Hello"), "tender.pdf", BidDocumentType.PDF),
        (files.png(), "logo.png", BidDocumentType.PNG),
        (files.jpeg(), "photo.jpg", BidDocumentType.JPEG),
        (files.docx("Hello"), "tender.docx", BidDocumentType.DOCX),
        (files.xlsx("Hello"), "prices.xlsx", BidDocumentType.XLSX),
        (files.pptx("Hello"), "pitch.pptx", BidDocumentType.PPTX),
        (files.odt("Hello"), "tender.odt", BidDocumentType.ODT),
        (files.ods("Hello"), "prices.ods", BidDocumentType.ODS),
        ("Plain text, café\n".encode(), "notes.txt", BidDocumentType.TXT),
        ("Windows text, caf\xe9\n".encode("cp1252"), "notes.txt", BidDocumentType.TXT),
        (files.csv_file("item,price", "a,1"), "prices.csv", BidDocumentType.CSV),
        (files.csv_file("item,price", "a,1"), "PRICES.CSV", BidDocumentType.CSV),
        # The name never decides the type: only whether plain text is labelled CSV.
        (files.csv_file("item,price"), "prices.txt", BidDocumentType.TXT),
        (files.pdf("Hello"), "tender.docx", BidDocumentType.PDF),
        (files.docx("Hello"), "tender.pdf", BidDocumentType.DOCX),
        (files.png(), "prices.csv", BidDocumentType.PNG),
    ],
)
def test_types_come_from_the_bytes(data: bytes, name: str, expected: BidDocumentType) -> None:
    assert sniff(data, name) is expected


def test_an_empty_file_is_refused() -> None:
    assert refused(b"", "empty.txt") == UNSUPPORTED


def test_a_renamed_executable_is_refused() -> None:
    exe = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00" + b"\x00" * 64
    assert refused(exe, "tender.pdf") == UNSUPPORTED
    elf = b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 56
    assert refused(elf, "tender.docx") == UNSUPPORTED


def test_text_with_a_nul_or_undecodable_bytes_is_refused() -> None:
    assert refused(b"hello\x00world", "a.txt") == UNSUPPORTED
    # UTF-16 text has NULs; 0x81 is undefined in Windows-1252 and invalid UTF-8.
    assert refused("hello".encode("utf-16"), "a.txt") == UNSUPPORTED
    assert refused(b"abc\x81def", "a.txt") == UNSUPPORTED


def test_an_ole_container_is_refused() -> None:
    """Old Office files, and Office files encrypted with a password (an OLE container
    holding EncryptedPackage), have no readable text for us."""
    ole = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 504
    assert refused(ole, "tender.docx") == UNSUPPORTED


def test_a_docm_renamed_docx_is_a_macro_document() -> None:
    docm = files.docx("Hello", main=DOCM_MAIN, extra={"word/vbaProject.bin": b"\x00VBA"})
    assert refused(docm, "tender.docx") == MACRO_DOCUMENT


def test_a_macro_enabled_content_type_alone_is_a_macro_document() -> None:
    assert refused(files.docx("Hello", main=DOCM_MAIN), "tender.docx") == MACRO_DOCUMENT


@pytest.mark.parametrize(
    "entry",
    [
        "word/vbaProject.bin",
        "xl/vbaProject.bin",
        "word/vbaData.xml",
        "word/activeX/activeX1.xml",
        "word/embeddings/oleObject1.bin",
        "ppt/embeddings/Microsoft_Word_Macro-Enabled_Document.docm",
        "word/embeddings/package.xlsm",
        "word/embeddings/sheet.XLSB",
        "xl/oleObject7.bin",
    ],
)
def test_active_office_parts_are_refused_by_name(entry: str) -> None:
    assert refused(files.docx("Hello", extra={entry: b"\x00"}), "tender.docx") == MACRO_DOCUMENT


@pytest.mark.parametrize("folder", ["Basic/Standard/Module1.xml", "Scripts/python/run.py"])
def test_opendocument_scripts_are_refused(folder: str) -> None:
    assert refused(files.odt("Hello", extra={folder: "x"}), "tender.odt") == MACRO_DOCUMENT


def test_an_embedded_docx_without_macros_is_allowed() -> None:
    """Embedded documents are fine unless they are OLE packages or macro-enabled."""
    data = files.docx("Hello", extra={"word/embeddings/Microsoft_Word_Document.docx": b"PK"})
    assert sniff(data, "tender.docx") is BidDocumentType.DOCX


def test_templates_and_other_office_formats_are_refused() -> None:
    assert refused(files.docx("Hello", main=DOTX_MAIN), "tender.dotx") == UNSUPPORTED
    plain_zip = zip_of({"readme.txt": "hello"})
    assert refused(plain_zip, "archive.zip") == UNSUPPORTED
    odg = zip_of(
        {"mimetype": "application/vnd.oasis.opendocument.graphics", "content.xml": "<x/>"},
        stored=["mimetype"],
    )
    assert refused(odg, "drawing.odg") == UNSUPPORTED
    ott = zip_of(
        {"mimetype": "application/vnd.oasis.opendocument.text-template", "content.xml": "<x/>"},
        stored=["mimetype"],
    )
    assert refused(ott, "template.ott") == UNSUPPORTED


def test_more_than_two_thousand_entries_in_the_end_record_is_refused_first() -> None:
    lying = files.lying_zip(real_entries=3, claimed=BID_ARCHIVE_MAX_ENTRIES + 1)
    assert archive_entry_count(lying) == BID_ARCHIVE_MAX_ENTRIES + 1
    assert refused(lying, "tender.docx") == UNSUPPORTED


def test_a_directory_longer_than_its_end_record_says_is_refused() -> None:
    """The end record claims 3 entries; the directory holds 2,001: the walk stops at the
    cap instead of building every entry."""
    entries = {"[Content_Types].xml": files._content_types(files.DOCX_MAIN, "word/document.xml")}
    entries.update({f"f{n}.xml": "x" for n in range(BID_ARCHIVE_MAX_ENTRIES)})
    data = bytearray(zip_of(entries))
    at = data.rfind(b"PK\x05\x06")
    struct.pack_into("<HH", data, at + 8, 3, 3)
    with pytest.raises(RefusedDocument):
        central_directory_names(bytes(data))
    assert refused(bytes(data), "tender.docx") == UNSUPPORTED


def test_exactly_two_thousand_entries_are_allowed() -> None:
    entries: dict[str, bytes | str] = {
        "[Content_Types].xml": files._content_types(files.DOCX_MAIN, "word/document.xml")
    }
    entries.update({f"f{n}.xml": "x" for n in range(BID_ARCHIVE_MAX_ENTRIES - 1)})
    assert sniff(zip_of(entries), "big.docx") is BidDocumentType.DOCX


def test_an_oversized_content_types_part_is_refused() -> None:
    padding = "<!--" + "x" * BID_CONTENT_TYPES_MAX_BYTES + "-->"
    types = files._content_types(files.DOCX_MAIN, "word/document.xml") + padding
    data = zip_of({"[Content_Types].xml": types, "word/document.xml": "<x/>"})
    assert refused(data, "tender.docx") == UNSUPPORTED


def test_names_come_from_the_central_directory_not_the_local_headers() -> None:
    """A local header naming a harmless part can't hide a vbaProject.bin listed in the
    central directory (and the other way round, the directory decides)."""
    data = bytearray(files.docx("Hello", extra={"word/vbaProject.bin": b"\x00"}))
    # Rename the entry in its local header only.
    at = data.find(b"word/vbaProject.bin")
    data[at : at + len("word/vbaProject.bin")] = b"word/harmlessss.bin"
    assert refused(bytes(data), "tender.docx") == MACRO_DOCUMENT


def test_an_encrypted_entry_is_refused() -> None:
    data = bytearray(files.docx("Hello"))
    # Set the encryption flag on [Content_Types].xml in the central directory.
    at = data.find(b"PK\x01\x02")
    flags = struct.unpack_from("<H", data, at + 8)[0]
    struct.pack_into("<H", data, at + 8, flags | 0x1)
    assert refused(bytes(data), "tender.docx") == UNSUPPORTED


def test_a_truncated_zip_is_refused() -> None:
    data = files.docx("Hello")
    assert refused(data[: len(data) // 2], "tender.docx") == UNSUPPORTED
    assert refused(b"PK\x03\x04garbage", "tender.docx") == UNSUPPORTED


def test_a_zip64_archive_is_read() -> None:
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", allowZip64=True) as archive:
        archive.writestr(
            "[Content_Types].xml", files._content_types(files.DOCX_MAIN, "word/document.xml")
        )
        with archive.open("word/document.xml", "w", force_zip64=True) as part:
            part.write(b"<x/>")
    assert sniff(buffer.getvalue(), "tender.docx") is BidDocumentType.DOCX
