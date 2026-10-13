"""The text extraction child (contract-phase10 section 6.3, ADR 0018 decision 5): run by
the worker as ``python -I -B -m app.bids.extract_child <type> <limits JSON>``, the
document's bytes on stdin, one JSON object on stdout::

    {"state": "done" | "no_text" | "failed", "error": null | "<ExtractionError>",
     "text": "...", "truncated": false, "active_content": false}

It imports only the standard library and ``pypdf`` (never the app's settings, models or
database code: it holds no secrets and needs none), limits its own address space first
(``RLIMIT_AS``), and never writes a file. Its bounds (the parent passes the numbers from
:mod:`app.schemas.bids`, the one place they are defined):

* **Archives** (OOXML, OpenDocument; :mod:`zipfile`): at most ``max_entries`` entries; a
  part is read only up to ``part_max_bytes`` and all of them together up to
  ``total_max_bytes``, counting the bytes actually decompressed as they stream (never the
  sizes the archive claims); a part that decompresses to more than ``max_ratio`` times its
  compressed size is refused; nested archives are never opened. Any of these:
  ``archive_limits``.
* **XML** is parsed with :mod:`xml.parsers.expat` directly, as a stream, in document order;
  a ``DOCTYPE`` (and so any entity declaration) stops it (``damaged``): no entity is ever
  expanded and nothing external is fetched.
* **Text**: at most ``max_chars`` characters (``truncated``), after removing NULs and the
  characters :func:`app.mcp.text.visible_text` hides (soft hyphens, zero-width, bidi
  controls, tag characters: review S1), so REST, MCP and quote checks read the same text.
* **Active content** (review S3): a PDF's ``/JavaScript``, ``/JS``, ``/Launch`` or
  ``/EmbeddedFile(s)``; an Office file's external relationship that isn't a hyperlink (a
  remote ``attachedTemplate``, an external OLE object or image), ``xl/externalLinks/``, or a
  DDE field: ``active_content: true`` (the file is kept; the SPA warns before a download).

PDF text comes from ``pypdf`` (BSD-3-Clause); an encrypted PDF without an empty user
password is ``failed`` ``encrypted``. PNG and JPEG have no text (no OCR): ``no_text``.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import re
import resource
import sys
import zipfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final
from xml.parsers import expat

__all__ = [
    "Limits",
    "Result",
    "extract",
    "main",
]

_MEMORY_RESULT: Final = (
    b'{"state":"failed","error":"memory","text":"","truncated":false,"active_content":false}'
)
"""Written as is when the child runs out of memory (building anything else may fail)."""


def _load_visible_text() -> Callable[[str], str]:
    """``app.mcp.text.visible_text`` without importing the ``app.mcp`` package (whose
    ``__init__`` loads the MCP server): the module is standard-library only."""
    path = Path(__file__).resolve().parent.parent / "mcp" / "text.py"
    spec = importlib.util.spec_from_file_location("_soundings_visible_text", path)
    if spec is None or spec.loader is None:  # pragma: no cover - shipped with the app
        raise RuntimeError("app/mcp/text.py is missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    visible: Callable[[str], str] = module.visible_text
    return visible


visible_text: Final = _load_visible_text()


@dataclass(frozen=True, slots=True)
class Limits:
    """The child's bounds (from :mod:`app.schemas.bids`, passed by the parent)."""

    max_chars: int
    max_entries: int
    part_max_bytes: int
    total_max_bytes: int
    max_ratio: int
    memory_bytes: int


@dataclass(slots=True)
class Result:
    state: str
    error: str | None = None
    text: str = ""
    truncated: bool = False
    active_content: bool = False

    def as_json(self) -> bytes:
        return json.dumps(
            {
                "state": self.state,
                "error": self.error,
                "text": self.text,
                "truncated": self.truncated,
                "active_content": self.active_content,
            },
            ensure_ascii=False,
        ).encode("utf-8")


class _Failed(Exception):
    def __init__(self, error: str) -> None:
        super().__init__(error)
        self.error = error


class _Full(Exception):
    """The text cap is reached: stop reading."""


@dataclass(slots=True)
class _Text:
    """Text collected in document order, up to twice the cap before cleaning (cleaning only
    removes characters), so a huge document never builds a huge string."""

    limit: int
    pieces: list[str] = field(default_factory=list)
    size: int = 0
    full: bool = False

    def add(self, piece: str) -> None:
        if not piece:
            return
        room = 2 * self.limit - self.size
        if len(piece) >= room:
            self.pieces.append(piece[:room])
            self.size += room
            self.full = True
            raise _Full
        self.pieces.append(piece)
        self.size += len(piece)

    def result(self, *, active_content: bool = False) -> Result:
        text = visible_text("".join(self.pieces))
        truncated = self.full or len(text) > self.limit
        text = text[: self.limit]
        if not text.strip():
            return Result("no_text", active_content=active_content)
        return Result("done", text=text, truncated=truncated, active_content=active_content)


# --- XML ---------------------------------------------------------------------------------------
_W: Final = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_S: Final = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_A: Final = "http://schemas.openxmlformats.org/drawingml/2006/main"
_TEXT: Final = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
_TABLE: Final = "urn:oasis:names:tc:opendocument:xmlns:table:1.0"
_OFFICE: Final = "urn:oasis:names:tc:opendocument:xmlns:office:1.0"
_DDE: Final = re.compile(r"^\s*DDE(?:AUTO)?\b", re.IGNORECASE)
_EXCEL_DDE: Final = re.compile(r"\|.*!")


class _Handler:
    """Expat callbacks for one part; subclasses say what is text."""

    def start(self, name: str, attrs: dict[str, str]) -> None:
        pass

    def end(self, name: str) -> None:
        pass

    def data(self, text: str) -> None:
        pass


def _refuse_doctype(*_args: Any) -> None:
    raise _Failed("damaged")


def _refuse_external(*_args: Any) -> int:
    raise _Failed("damaged")


def _parser(handler: _Handler) -> Any:
    parser = expat.ParserCreate(namespace_separator=" ")
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    parser.StartDoctypeDeclHandler = _refuse_doctype
    parser.EntityDeclHandler = _refuse_doctype
    parser.ExternalEntityRefHandler = _refuse_external
    parser.StartElementHandler = handler.start
    parser.EndElementHandler = handler.end
    parser.CharacterDataHandler = handler.data
    parser.buffer_text = True
    return parser


class _WordText(_Handler):
    """``w:t`` text, tabs and breaks, a line per paragraph; DDE field codes."""

    def __init__(self, sink: _Text) -> None:
        self.sink = sink
        self.in_text = False
        self.in_instr = False
        self.instr: list[str] = []
        self.dde = False

    def start(self, name: str, attrs: dict[str, str]) -> None:
        if name == f"{_W} t":
            self.in_text = True
        elif name == f"{_W} instrText":
            self.in_instr = True
        elif name == f"{_W} tab":
            self.sink.add("\t")
        elif name in (f"{_W} br", f"{_W} cr"):
            self.sink.add("\n")
        elif name == f"{_W} fldSimple" and _DDE.search(attrs.get(f"{_W} instr", "")):
            self.dde = True

    def end(self, name: str) -> None:
        if name == f"{_W} t":
            self.in_text = False
        elif name == f"{_W} instrText":
            self.in_instr = False
            if _DDE.search("".join(self.instr)):
                self.dde = True
            self.instr.clear()
        elif name == f"{_W} p":
            self.sink.add("\n")

    def data(self, text: str) -> None:
        if self.in_text:
            self.sink.add(text)
        elif self.in_instr and len(self.instr) < 100:
            self.instr.append(text)


class _DrawingText(_Handler):
    """PowerPoint: ``a:t`` runs, a line per ``a:p``."""

    def __init__(self, sink: _Text) -> None:
        self.sink = sink
        self.in_text = False

    def start(self, name: str, attrs: dict[str, str]) -> None:
        if name == f"{_A} t":
            self.in_text = True
        elif name == f"{_A} br":
            self.sink.add("\n")

    def end(self, name: str) -> None:
        if name == f"{_A} t":
            self.in_text = False
        elif name == f"{_A} p":
            self.sink.add("\n")

    def data(self, text: str) -> None:
        if self.in_text:
            self.sink.add(text)


class _SharedStrings(_Handler):
    """Excel's shared strings, in order (each ``si`` one string, possibly in runs), up to
    twice the text cap in all (past it, the rest resolve to nothing and the text is
    marked truncated)."""

    def __init__(self, sink: _Text) -> None:
        self.sink = sink
        self.strings: list[str] = []
        self.current: list[str] | None = None
        self.in_text = False
        self.size = 0

    def start(self, name: str, attrs: dict[str, str]) -> None:
        if name == f"{_S} si":
            self.current = []
        elif name == f"{_S} t":
            self.in_text = True

    def end(self, name: str) -> None:
        if name == f"{_S} si" and self.current is not None:
            self.strings.append("".join(self.current))
            self.current = None
        elif name == f"{_S} t":
            self.in_text = False

    def data(self, text: str) -> None:
        if not (self.in_text and self.current is not None):
            return
        if self.size + len(text) > 2 * self.sink.limit:
            self.sink.full = True
            return
        self.size += len(text)
        self.current.append(text)


class _SheetText(_Handler):
    """A worksheet: each row's cells joined by tabs (shared strings resolved, inline
    strings and values as written), a line per row; DDE-style formulas."""

    def __init__(self, sink: _Text, shared: list[str]) -> None:
        self.sink = sink
        self.shared = shared
        self.cell_type = ""
        self.cells: list[str] = []
        self.value: list[str] = []
        self.formula: list[str] = []
        self.in_value = False
        self.in_inline = False
        self.in_formula = False
        self.dde = False

    def start(self, name: str, attrs: dict[str, str]) -> None:
        if name == f"{_S} c":
            self.cell_type = attrs.get("t", "")
            self.value = []
        elif name == f"{_S} v":
            self.in_value = True
        elif name == f"{_S} is":
            self.in_inline = True
        elif name == f"{_S} f":
            self.in_formula = True
            self.formula = []

    def end(self, name: str) -> None:
        if name == f"{_S} v":
            self.in_value = False
        elif name == f"{_S} is":
            self.in_inline = False
        elif name == f"{_S} f":
            self.in_formula = False
            if _EXCEL_DDE.search("".join(self.formula)):
                self.dde = True
        elif name == f"{_S} c":
            raw = "".join(self.value)
            if self.cell_type == "s":
                try:
                    raw = self.shared[int(raw)]
                except (ValueError, IndexError):
                    raw = ""
            self.cells.append(raw)
        elif name == f"{_S} row":
            line = "\t".join(self.cells).rstrip("\t")
            self.cells = []
            if line:
                self.sink.add(line + "\n")

    def data(self, text: str) -> None:
        if self.in_value or self.in_inline:
            self.value.append(text)
        elif self.in_formula and len(self.formula) < 100:
            self.formula.append(text)


class _OpenDocumentText(_Handler):
    """``content.xml`` of ODT and ODS: the text under ``office:body``, a line per
    paragraph and heading, tabs between table cells and a line per table row."""

    def __init__(self, sink: _Text) -> None:
        self.sink = sink
        self.depth = 0

    def start(self, name: str, attrs: dict[str, str]) -> None:
        if name == f"{_OFFICE} body":
            self.depth += 1
        elif self.depth:
            if name == f"{_TEXT} tab":
                self.sink.add("\t")
            elif name == f"{_TEXT} line-break":
                self.sink.add("\n")
            elif name == f"{_TEXT} s":
                self.sink.add(" " * min(int(attrs.get(f"{_TEXT} c", "1") or 1), 100))

    def end(self, name: str) -> None:
        if name == f"{_OFFICE} body":
            self.depth -= 1
        elif self.depth:
            if name in (f"{_TEXT} p", f"{_TEXT} h"):
                self.sink.add("\n")
            elif name == f"{_TABLE} table-cell":
                self.sink.add("\t")
            elif name == f"{_TABLE} table-row":
                self.sink.add("\n")

    def data(self, text: str) -> None:
        if self.depth:
            self.sink.add(text)


class _Relationships(_Handler):
    """A ``.rels`` part: an external relationship that isn't a hyperlink is active
    content (a remote template, an external OLE object, a remote image)."""

    def __init__(self) -> None:
        self.external = False

    def start(self, name: str, attrs: dict[str, str]) -> None:
        if (
            (name.endswith(" Relationship") or name == "Relationship")
            and attrs.get("TargetMode", "").lower() == "external"
            and not attrs.get("Type", "").endswith("/hyperlink")
        ):
            self.external = True


# --- Archives ----------------------------------------------------------------------------------
@dataclass(slots=True)
class _Archive:
    """A ZIP read within the caps, counting the bytes actually decompressed."""

    archive: zipfile.ZipFile
    limits: Limits
    total: int = 0

    def names(self) -> list[str]:
        return [info.filename for info in self.archive.infolist()]

    def parse(self, name: str, handler: _Handler) -> None:
        try:
            info = self.archive.getinfo(name)
        except KeyError:
            return
        parser = _parser(handler)
        part = 0
        allowed = self.limits.max_ratio * max(info.compress_size, 1)
        try:
            with self.archive.open(info) as stream:
                while chunk := stream.read(64 * 1024):
                    part += len(chunk)
                    self.total += len(chunk)
                    if (
                        part > self.limits.part_max_bytes
                        or self.total > self.limits.total_max_bytes
                        or part > allowed
                    ):
                        raise _Failed("archive_limits")
                    parser.Parse(chunk, False)
                parser.Parse(b"", True)
        except (_Failed, _Full, MemoryError):
            raise
        except expat.ExpatError:
            raise _Failed("damaged") from None
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError, EOFError):
            # RuntimeError: an encrypted part; NotImplementedError: an unknown compression.
            raise _Failed("damaged") from None


def _open_archive(data: bytes, limits: Limits) -> _Archive:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, OSError, ValueError, EOFError):
        raise _Failed("damaged") from None
    if len(archive.infolist()) > limits.max_entries:
        raise _Failed("archive_limits")
    return _Archive(archive, limits)


def _numbered(names: Iterable[str], pattern: str) -> list[str]:
    """Parts like ``ppt/slides/slide12.xml`` in their number's order."""
    found = []
    regex = re.compile(pattern)
    for name in names:
        match = regex.fullmatch(name)
        if match:
            found.append((int(match.group(1)), name))
    return [name for _, name in sorted(found)]


def _office_active(zipped: _Archive) -> bool:
    names = zipped.names()
    if any(name.startswith("xl/externalLinks/") for name in names):
        return True
    for name in names:
        if name.endswith(".rels"):
            rels = _Relationships()
            zipped.parse(name, rels)
            if rels.external:
                return True
    return False


def _docx(data: bytes, limits: Limits) -> Result:
    zipped = _open_archive(data, limits)
    sink = _Text(limits.max_chars)
    words = _WordText(sink)
    names = zipped.names()
    parts = [
        "word/document.xml",
        *_numbered(names, r"word/header(\d+)\.xml"),
        *_numbered(names, r"word/footer(\d+)\.xml"),
        "word/footnotes.xml",
        "word/endnotes.xml",
    ]
    try:
        for part in parts:
            zipped.parse(part, words)
            sink.add("\n")
    except _Full:
        pass
    active = _office_active(zipped) or words.dde
    return sink.result(active_content=active)


def _xlsx(data: bytes, limits: Limits) -> Result:
    zipped = _open_archive(data, limits)
    sink = _Text(limits.max_chars)
    shared = _SharedStrings(sink)
    dde = False
    try:
        zipped.parse("xl/sharedStrings.xml", shared)
        for part in _numbered(zipped.names(), r"xl/worksheets/sheet(\d+)\.xml"):
            sheet = _SheetText(sink, shared.strings)
            try:
                zipped.parse(part, sheet)
            finally:
                dde = dde or sheet.dde
            sink.add("\n")
    except _Full:
        pass
    active = _office_active(zipped) or dde
    return sink.result(active_content=active)


def _pptx(data: bytes, limits: Limits) -> Result:
    zipped = _open_archive(data, limits)
    sink = _Text(limits.max_chars)
    names = zipped.names()
    try:
        for part in [
            *_numbered(names, r"ppt/slides/slide(\d+)\.xml"),
            *_numbered(names, r"ppt/notesSlides/notesSlide(\d+)\.xml"),
        ]:
            zipped.parse(part, _DrawingText(sink))
            sink.add("\n")
    except _Full:
        pass
    return sink.result(active_content=_office_active(zipped))


def _opendocument(data: bytes, limits: Limits) -> Result:
    zipped = _open_archive(data, limits)
    sink = _Text(limits.max_chars)
    with contextlib.suppress(_Full):
        zipped.parse("content.xml", _OpenDocumentText(sink))
    return sink.result()


# --- PDF ---------------------------------------------------------------------------------------
_PDF_ACTIVE: Final = re.compile(rb"/(?:JavaScript|JS|Launch|EmbeddedFiles?)(?![A-Za-z0-9])")
_ACTIVE_NAMES: Final = frozenset(
    {"/JavaScript", "/JS", "/Launch", "/EmbeddedFile", "/EmbeddedFiles"}
)


def _pdf_names(value: Any, depth: int = 0, seen: set[int] | None = None) -> bool:
    """Whether a PDF object (dictionaries and arrays, followed through references a few
    levels deep) uses one of the active names as a key or a value."""
    from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject, NameObject

    if depth > 6:
        return False
    seen = seen if seen is not None else set()
    if isinstance(value, IndirectObject):
        if value.idnum in seen:
            return False
        seen.add(value.idnum)
        try:
            value = value.get_object()
        except Exception:  # noqa: BLE001 - a broken reference is no evidence
            return False
    if isinstance(value, NameObject):
        return str(value) in _ACTIVE_NAMES
    if isinstance(value, DictionaryObject):
        for key, item in list(value.items())[:200]:
            if str(key) in _ACTIVE_NAMES or _pdf_names(item, depth + 1, seen):
                return True
    if isinstance(value, ArrayObject):
        return any(_pdf_names(item, depth + 1, seen) for item in list(value)[:200])
    return False


def _pdf(data: bytes, limits: Limits) -> Result:
    import logging

    logging.disable(logging.CRITICAL)  # pypdf warns on stderr about odd files
    from pypdf import PdfReader
    from pypdf.errors import FileNotDecryptedError, PdfReadError

    active = bool(_PDF_ACTIVE.search(data))
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            try:
                if not reader.decrypt(""):
                    raise _Failed("encrypted")
            except (FileNotDecryptedError, NotImplementedError, PdfReadError):
                raise _Failed("encrypted") from None
        root = reader.trailer.get("/Root")
        if not active and root is not None:
            root = root.get_object()
            active = any(_pdf_names(root.get(key)) for key in ("/Names", "/OpenAction", "/AA"))
        pages = reader.pages
        count = len(pages)
    except (_Failed, MemoryError):
        raise
    except Exception:  # noqa: BLE001 - pypdf raises many kinds on damaged files
        raise _Failed("damaged") from None
    sink = _Text(limits.max_chars)
    read = 0
    try:
        for number in range(count):
            try:
                page = pages[number]
                if not active and (_pdf_names(page.get("/AA")) or _pdf_names(page.get("/Annots"))):
                    active = True
                text = page.extract_text() or ""
            except MemoryError:
                raise
            except Exception:  # noqa: BLE001, S112 - one damaged page doesn't lose the rest
                continue
            read += 1
            sink.add(text)
            sink.add("\n\n")
    except _Full:
        pass
    if count and not read:
        raise _Failed("damaged")
    return sink.result(active_content=active)


# --- Plain text --------------------------------------------------------------------------------
def _plain(data: bytes, limits: Limits) -> Result:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            decoded = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        sink = _Text(limits.max_chars)
        with contextlib.suppress(_Full):
            sink.add(decoded)
        return sink.result()
    raise _Failed("damaged")


_EXTRACTORS: Final[dict[str, Callable[[bytes, Limits], Result]]] = {
    "pdf": _pdf,
    "docx": _docx,
    "xlsx": _xlsx,
    "pptx": _pptx,
    "odt": _opendocument,
    "ods": _opendocument,
    "txt": _plain,
    "csv": _plain,
}


def extract(kind: str, data: bytes, limits: Limits) -> Result:
    """The document's text (in-process: tests; the worker runs :func:`main` in a child)."""
    if kind in ("png", "jpeg"):
        return Result("no_text")
    extractor = _EXTRACTORS.get(kind)
    if extractor is None:
        return Result("failed", error="internal_error")
    try:
        return extractor(data, limits)
    except _Failed as failed:
        return Result("failed", error=failed.error)
    except RecursionError:
        return Result("failed", error="damaged")


def _limit_memory(memory_bytes: int) -> None:
    resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def main(argv: list[str] | None = None) -> int:
    """The child's entry point: limits, then stdin -> :func:`extract` -> stdout."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        return 2
    kind, raw_limits = args
    limits = Limits(**json.loads(raw_limits))
    out = sys.stdout.buffer
    try:
        _limit_memory(limits.memory_bytes)
        data = sys.stdin.buffer.read()
        output = extract(kind, data, limits).as_json()
    except MemoryError:
        output = _MEMORY_RESULT
    out.write(output)
    out.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
