"""The PDF child process: WeasyPrint with the bundled fonts and a local-only fetcher
(contract-phase4 3.4, ADR 0011). Imported only in the child (and by tests).

:class:`LocalOnlyFetcher` answers exactly two kinds of URL and raises for everything
else (``http(s)``, ``file:``, ``ftp:``, relative paths, link-local addresses...):

* ``data:`` URIs of a PNG or SVG (the logo), decoded here;
* ``soundings-font:<name>`` looked up in :data:`FONTS`, the bundled font files read
  once at import from the fixed name -> file table (:data:`app.proposals.fonts
  .FONT_FILES`): no part of a URL ever reaches the file system.

It never calls WeasyPrint's default ``URLFetcher.fetch`` (which follows
``HTTP(S)_PROXY`` and redirects), not even as a fallback.
"""

from __future__ import annotations

import base64
import binascii
import io
import logging
import resource
import signal
from dataclasses import replace
from multiprocessing.connection import Connection
from typing import Any, Final
from xml.parsers import expat

from PIL import Image, ImageFile
from weasyprint import HTML
from weasyprint.text.fonts import FontConfiguration
from weasyprint.urls import URLFetcher, URLFetcherResponse

from app.proposals.document import LOGO_TYPES, ExportBranding, ExportDocument, build_html
from app.proposals.fonts import FONT_DIR, FONT_FILES, FONT_SCHEME
from app.proposals.pdf import IDLE_EXIT

__all__ = [
    "FONTS",
    "MAX_DATA_URI_BYTES",
    "MEMORY_LIMIT",
    "BlockedURL",
    "LocalOnlyFetcher",
    "decode_data_uri",
    "logo_readable",
    "render_document",
    "render_html",
    "serve",
]

FONTS: Final[dict[str, bytes]] = {
    name: (FONT_DIR / file_name).read_bytes() for name, file_name in FONT_FILES.items()
}
"""``soundings-font:`` name -> the font file's bytes (fixed at import)."""

MAX_DATA_URI_BYTES: Final = 2 * 1024 * 1024
MAX_LOGO_PIXELS: Final = 4096 * 4096
MEMORY_LIMIT: Final = 2 * 1024 * 1024 * 1024
"""Address space of the child: a runaway render fails instead of starving the node."""


class BlockedURL(ValueError):
    """A URL the export may not load (never followed, never retried)."""


def decode_data_uri(url: str) -> tuple[str, bytes]:
    """``data:image/png;base64,...`` -> (media type, bytes); only base64 PNG or SVG."""
    header, comma, payload = url.partition(",")
    if not comma or not header.startswith("data:") or not header.endswith(";base64"):
        raise BlockedURL("unsupported data: URI")
    media_type = header[len("data:") : -len(";base64")].strip().lower()
    if media_type not in LOGO_TYPES or len(payload) > MAX_DATA_URI_BYTES * 4 // 3 + 4:
        raise BlockedURL("unsupported data: URI")
    try:
        return media_type, base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        raise BlockedURL("invalid data: URI") from None


class LocalOnlyFetcher(URLFetcher):  # type: ignore[misc]  # WeasyPrint is untyped
    """WeasyPrint's resource loader for exports: bundled fonts and ``data:`` only."""

    def __init__(self) -> None:
        super().__init__(timeout=1, allowed_protocols=frozenset(), allow_redirects=False)

    def fetch(self, url: str, headers: Any = None) -> URLFetcherResponse:
        if url.startswith(FONT_SCHEME):
            font = FONTS.get(url[len(FONT_SCHEME) :])
            if font is None:
                raise BlockedURL("unknown font")
            return URLFetcherResponse(url, font, {"Content-Type": "font/woff2"})
        if url.startswith("data:"):
            media_type, data = decode_data_uri(url)
            return URLFetcherResponse(url, data, {"Content-Type": media_type})
        raise BlockedURL("exports load no remote or local resources")

    def open(self, url: Any, data: Any = None, timeout: Any = None) -> URLFetcherResponse:
        return self.fetch(url if isinstance(url, str) else str(getattr(url, "full_url", "")))

    def __call__(self, url: str) -> URLFetcherResponse:
        return self.fetch(url)


def render_html(html: str) -> bytes:
    """The PDF for ``html`` (fonts and images through :class:`LocalOnlyFetcher`)."""
    pdf: bytes = HTML(string=html, url_fetcher=LocalOnlyFetcher()).write_pdf(
        font_config=FontConfiguration()
    )
    return pdf


def _refuse(*_: object) -> None:
    raise ValueError("no DTDs or entities in an embedded SVG")


def logo_readable(branding: ExportBranding) -> bool:
    """Whether the logo decodes: a complete PNG, or well-formed SVG without a DTD. The
    upload checks (contract 3.11) already guarantee both; this keeps a damaged row from
    leaving an empty space where the wordmark should be."""
    if branding.logo is None:
        return False
    try:
        if branding.logo_type == "image/png":
            # WeasyPrint sets Pillow's LOAD_TRUNCATED_IMAGES at import; a truncated logo
            # must count as unreadable here.
            lenient, ImageFile.LOAD_TRUNCATED_IMAGES = ImageFile.LOAD_TRUNCATED_IMAGES, False
            try:
                with Image.open(io.BytesIO(branding.logo), formats=("PNG",)) as image:
                    if image.width * image.height > MAX_LOGO_PIXELS:
                        return False
                    image.load()
            finally:
                ImageFile.LOAD_TRUNCATED_IMAGES = lenient
            return True
        if branding.logo_type == "image/svg+xml":
            parser = expat.ParserCreate()
            parser.StartDoctypeDeclHandler = _refuse
            parser.EntityDeclHandler = _refuse
            parser.Parse(branding.logo, True)
            return True
    except Exception:  # noqa: BLE001 - any decoding failure means "not readable"
        return False
    return False


def render_document(document: ExportDocument) -> bytes:
    """The document's PDF. A logo that doesn't decode (or makes the render fail) is
    replaced by the app name as the wordmark."""
    without_logo = replace(document, branding=replace(document.branding, logo=None, logo_type=None))
    if document.branding.logo is not None and not logo_readable(document.branding):
        return render_html(build_html(without_logo))
    try:
        return render_html(build_html(document))
    except Exception:
        if document.branding.logo is None:
            raise
    return render_html(build_html(without_logo))


def _limit_memory() -> None:
    try:
        _, hard = resource.getrlimit(resource.RLIMIT_AS)
        limit = MEMORY_LIMIT if hard == resource.RLIM_INFINITY else min(MEMORY_LIMIT, hard)
        resource.setrlimit(resource.RLIMIT_AS, (limit, hard))
    except (ValueError, OSError):  # pragma: no cover - platform without the limit
        pass


def serve(connection: Connection) -> None:
    """Render each :class:`ExportDocument` received; exit after :data:`IDLE_EXIT`
    seconds without one, or when the API process closes the pipe. Replies
    ``("ok", pdf)`` or ``("error", <exception class name>)``: never document text."""
    signal.signal(signal.SIGINT, signal.SIG_IGN)  # Ctrl+C is for the API process
    _limit_memory()
    # WeasyPrint logs refused URLs and CSS it skips; nothing to report from here.
    logging.getLogger("weasyprint").setLevel(logging.CRITICAL)
    while connection.poll(IDLE_EXIT):
        try:
            document = connection.recv()
        except (EOFError, OSError):
            return
        try:
            if not isinstance(document, ExportDocument):
                raise TypeError("not an ExportDocument")
            reply: tuple[str, object] = ("ok", render_document(document))
        except Exception as error:  # noqa: BLE001 - reported to the parent by class name
            reply = ("error", type(error).__name__)
        try:
            connection.send(reply)
        except (EOFError, OSError):
            return
