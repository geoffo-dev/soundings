"""Small bid documents built in memory for the upload and extraction tests (Phase 10,
contract-phase10 section 6): every allowed type, and the hostile ones (macro files,
embedded OLE packages, zip bombs, lying archives, active content).

Each builder returns the file's bytes. Office and OpenDocument files are the minimal
parts their readers need; the PDF is hand-written with correct cross-reference offsets.
"""

from __future__ import annotations

import io
import struct
import zipfile
import zlib
from collections.abc import Iterable, Mapping
from xml.sax.saxutils import escape

__all__ = [
    "DOCX_MAIN",
    "PPTX_MAIN",
    "XLSX_MAIN",
    "csv_file",
    "docx",
    "jpeg",
    "lying_zip",
    "ods",
    "odt",
    "pdf",
    "png",
    "pptx",
    "xlsx",
    "zip_of",
]

DOCX_MAIN = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
XLSX_MAIN = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
PPTX_MAIN = "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"
DOCM_MAIN = "application/vnd.ms-word.document.macroEnabled.main+xml"
DOTX_MAIN = "application/vnd.openxmlformats-officedocument.wordprocessingml.template.main+xml"

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_OFFICE = "urn:oasis:names:tc:opendocument:xmlns:office:1.0"
_TEXT = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
_TABLE = "urn:oasis:names:tc:opendocument:xmlns:table:1.0"


def zip_of(
    entries: Mapping[str, bytes | str] | Iterable[tuple[str, bytes | str]],
    *,
    stored: Iterable[str] = (),
) -> bytes:
    """A ZIP with these entries (deflated, but those named in ``stored``)."""
    keep = set(stored)
    items = entries.items() if isinstance(entries, Mapping) else entries
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in items:
            data = content.encode("utf-8") if isinstance(content, str) else content
            method = zipfile.ZIP_STORED if name in keep else zipfile.ZIP_DEFLATED
            archive.writestr(zipfile.ZipInfo(name), data, compress_type=method)
    return buffer.getvalue()


def _content_types(main: str, part: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
        'relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
        f'<Override PartName="/{part}" ContentType="{main}"/></Types>'
    )


def _rels(part: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.'
        'openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
        f'officeDocument" Target="{part}"/></Relationships>'
    )


def docx(
    *paragraphs: str,
    main: str = DOCX_MAIN,
    extra: Mapping[str, bytes | str] | None = None,
    document_rels: str | None = None,
    body_xml: str | None = None,
) -> bytes:
    """A Word document with one paragraph per argument."""
    body = body_xml or "".join(
        f'<w:p><w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>'
        for text in paragraphs
    )
    entries: dict[str, bytes | str] = {
        "[Content_Types].xml": _content_types(main, "word/document.xml"),
        "_rels/.rels": _rels("word/document.xml"),
        "word/document.xml": (
            f'<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="{_W}"><w:body>'
            f"{body}</w:body></w:document>"
        ),
    }
    if document_rels is not None:
        entries["word/_rels/document.xml.rels"] = document_rels
    entries.update(extra or {})
    return zip_of(entries)


def xlsx(*cells: str, extra: Mapping[str, bytes | str] | None = None) -> bytes:
    """A workbook whose first sheet has one shared-string cell per argument in column A."""
    shared = "".join(f"<si><t>{escape(text)}</t></si>" for text in cells)
    rows = "".join(
        f'<row r="{n}"><c r="A{n}" t="s"><v>{n - 1}</v></c></row>' for n in range(1, len(cells) + 1)
    )
    entries: dict[str, bytes | str] = {
        "[Content_Types].xml": _content_types(XLSX_MAIN, "xl/workbook.xml"),
        "_rels/.rels": _rels("xl/workbook.xml"),
        "xl/workbook.xml": (
            f'<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="{_S}"><sheets>'
            '<sheet name="Prices" sheetId="1"/></sheets></workbook>'
        ),
        "xl/sharedStrings.xml": (
            f'<?xml version="1.0" encoding="UTF-8"?><sst xmlns="{_S}">{shared}</sst>'
        ),
        "xl/worksheets/sheet1.xml": (
            f'<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="{_S}"><sheetData>'
            f"{rows}</sheetData></worksheet>"
        ),
    }
    entries.update(extra or {})
    return zip_of(entries)


def pptx(*texts: str) -> bytes:
    """A presentation with one slide holding one text run per argument."""
    runs = "".join(f"<a:p><a:r><a:t>{escape(text)}</a:t></a:r></a:p>" for text in texts)
    return zip_of(
        {
            "[Content_Types].xml": _content_types(PPTX_MAIN, "ppt/presentation.xml"),
            "_rels/.rels": _rels("ppt/presentation.xml"),
            "ppt/presentation.xml": (
                f'<?xml version="1.0" encoding="UTF-8"?><p:presentation xmlns:p="{_P}"/>'
            ),
            "ppt/slides/slide1.xml": (
                f'<?xml version="1.0" encoding="UTF-8"?><p:sld xmlns:p="{_P}" '
                f'xmlns:a="{_A}"><p:cSld><p:spTree><p:sp><p:txBody>{runs}</p:txBody>'
                "</p:sp></p:spTree></p:cSld></p:sld>"
            ),
        }
    )


def _odf(mimetype: str, body: str, extra: Mapping[str, bytes | str] | None = None) -> bytes:
    entries: list[tuple[str, bytes | str]] = [
        ("mimetype", mimetype),
        (
            "content.xml",
            f'<?xml version="1.0" encoding="UTF-8"?><office:document-content '
            f'xmlns:office="{_OFFICE}" xmlns:text="{_TEXT}" xmlns:table="{_TABLE}">'
            f"<office:body>{body}</office:body></office:document-content>",
        ),
        ("META-INF/manifest.xml", '<?xml version="1.0" encoding="UTF-8"?><manifest/>'),
    ]
    entries.extend((extra or {}).items())
    return zip_of(entries, stored=["mimetype"])


def odt(*paragraphs: str, extra: Mapping[str, bytes | str] | None = None) -> bytes:
    body = "".join(f"<text:p>{escape(text)}</text:p>" for text in paragraphs)
    return _odf(
        "application/vnd.oasis.opendocument.text", f"<office:text>{body}</office:text>", extra
    )


def ods(*cells: str) -> bytes:
    rows = "".join(
        f"<table:table-row><table:table-cell><text:p>{escape(text)}</text:p>"
        "</table:table-cell></table:table-row>"
        for text in cells
    )
    return _odf(
        "application/vnd.oasis.opendocument.spreadsheet",
        f'<office:spreadsheet><table:table table:name="Prices">{rows}</table:table>'
        "</office:spreadsheet>",
    )


def _pdf_string(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def pdf(*lines: str, catalog_extra: str = "", objects: Iterable[str] = ()) -> bytes:
    """A one-page PDF (Helvetica) with one line of text per argument. ``catalog_extra``
    goes into the catalog dictionary (e.g. an ``/OpenAction`` with JavaScript);
    ``objects`` are more objects, numbered from 6."""
    content = (
        "BT /F1 12 Tf 72 720 Td 14 TL "
        + " ".join(f"({_pdf_string(line)}) Tj T*" for line in lines)
        + " ET"
    )
    bodies = [
        f"<< /Type /Catalog /Pages 2 0 R {catalog_extra} >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(content.encode('latin-1'))} >>\nstream\n{content}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        *objects,
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(bodies, start=1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n{body}\nendobj\n".encode("latin-1"))
    xref = out.tell()
    out.write(f"xref\n0 {len(bodies) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(
        f"trailer\n<< /Size {len(bodies) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return out.getvalue()


def png() -> bytes:
    """A 1x1 PNG."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    pixels = zlib.compress(b"\x00\xff\x00\x00")
    return (
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", pixels) + chunk(b"IEND", b"")
    )


def jpeg() -> bytes:
    """Enough of a JPEG for its signature (never decoded: no OCR)."""
    return b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"


def csv_file(*rows: str) -> bytes:
    return ("\r\n".join(rows) + "\r\n").encode("utf-8")


def lying_zip(real_entries: int, claimed: int) -> bytes:
    """A ZIP of ``real_entries`` tiny files whose end record claims ``claimed`` entries."""
    data = bytearray(zip_of({f"f{n}.txt": b"x" for n in range(real_entries)}))
    at = data.rfind(b"PK\x05\x06")
    struct.pack_into("<HH", data, at + 8, min(claimed, 0xFFFF), min(claimed, 0xFFFF))
    return bytes(data)
