"""Uploaded logos and favicons: checking, storing, serving and expiring them
(contract-phase4 section 3.11, ADR 0012).

**The bytes decide**, never the ``Content-Type`` header or a file name: a PNG by its
signature, an SVG by parsing it. Nothing else is accepted (no ICO, WebP, GIF or JPEG
decoder is ever reached by an upload).

* **PNG** is decoded by Pillow's PNG plugin only (``formats=("PNG",)``), with
  ``MAX_IMAGE_PIXELS`` at 2048 x 2048, the decompression-bomb warning turned into an
  error and the size checked before any pixel is decoded; then it is **re-encoded**
  (no text chunks, EXIF, ICC profile or trailing bytes: no metadata, no polyglots).
* **SVG** is parsed with the standard library's expat (not ``xml.etree``: it expands
  internal entities and can't refuse a DOCTYPE) and checked against an **allow-list**,
  never "cleaned": no DOCTYPE, entity or processing instruction; at most 2,000
  elements nested at most 32 deep (counted while parsing, so a hostile file stops at
  the first element over); only drawing elements in the SVG namespace; only
  presentation attributes, no ``style``, event handlers, ``href`` or foreign
  attributes; ``url(#id)`` only in ``fill``/``stroke`` (a gradient), ``clip-path`` (a
  ``clipPath``) and ``mask`` (a ``mask``), nothing inside a ``clipPath``, ``mask`` or
  gradient may reference anything (no chains), and counting every reference as a
  copy of what it names the drawing stays within 10,000 elements (SVG rendering is
  exponential in reference depth: ADR 0012). The stored bytes are the checked tree
  **re-serialised** by :func:`_serialise` with the SVG namespace as the default.

Uploads are immutable rows (``brand_assets``) served by id with a fixed content type,
``nosniff`` and a sandboxing CSP; a new image is a new id, so URLs are cached for a
year. Identical bytes uploaded again for the same profile and kind return the existing
asset (sha256), and each profile may add 20 images a day. Images no profile references
are deleted by the hourly cleanup 24 hours after upload (:func:`delete_unreferenced`).
Logs never carry image bytes.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import math
import re
import warnings
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Final, NoReturn
from uuid import UUID, uuid4
from xml.parsers import expat

from fastapi.responses import Response
from sqlalchemy import ColumnElement, delete, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import NotFoundProblem, ProblemError
from app.models.branding import MAX_ASSET_BYTES, BrandingProfile
from app.models.branding import BrandAsset as BrandAssetRow
from app.models.enums import BrandAssetKind
from app.schemas.branding import BrandAsset

__all__ = [
    "ASSET_CSP",
    "ASSET_URL_PREFIX",
    "PNG_MAX_SIDE",
    "SVG_MAX_DEPTH",
    "SVG_MAX_ELEMENTS",
    "SVG_REFERENCE_BUDGET",
    "UNREFERENCED_GRACE",
    "UPLOADS_PER_DAY",
    "CheckedImage",
    "asset_out",
    "asset_response",
    "asset_url",
    "check_image",
    "delete_unreferenced",
    "store_upload",
]

logger = logging.getLogger(__name__)

ASSET_URL_PREFIX: Final = "/api/v1/branding/assets/"
ASSET_CSP: Final = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
"""An SVG opened directly can never run script or load anything (defence in depth
behind the allow-list)."""
CACHE_FOREVER: Final = "public, max-age=31536000, immutable"

UPLOADS_PER_DAY: Final = 20
"""New images per profile (the global one, or one project's) per 24 hours."""
UPLOAD_WINDOW: Final = timedelta(hours=24)
UNREFERENCED_GRACE: Final = timedelta(hours=24)
"""An image no profile uses is deleted this long after its upload (the old URL keeps
working meanwhile, for caches and open pages)."""
CLEANUP_BATCH: Final = 500
DEDUPE_WINDOW: Final = timedelta(hours=12)
"""An unused image is reused for identical bytes only while it is this young (well
before the cleanup's 24 hours)."""

PNG_SIGNATURE: Final = b"\x89PNG\r\n\x1a\n"
PNG_MAX_SIDE: Final[Mapping[BrandAssetKind, int]] = {
    BrandAssetKind.LOGO: 2_048,
    BrandAssetKind.FAVICON: 512,
}
"""Largest width and height in pixels."""
PNG_MAX_PIXELS: Final = 2_048 * 2_048

SVG_NS: Final = "http://www.w3.org/2000/svg"
XML_NS: Final = "http://www.w3.org/XML/1998/namespace"
SVG_MAX_ELEMENTS: Final = 2_000
SVG_MAX_DEPTH: Final = 32
SVG_REFERENCE_BUDGET: Final = 10_000
_SVG_MAX_ATTRIBUTE_LENGTH: Final = 100_000

_UPLOAD_LOCK_SALT: Final = 0x4252_4E44
"""First key of the advisory lock that serialises one profile's uploads (the quota)."""


@dataclass(frozen=True, slots=True)
class CheckedImage:
    """What gets stored: the normalised bytes, their type and pixel size."""

    content_type: str
    data: bytes = field(repr=False)
    width: int | None
    height: int | None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


def _invalid(detail: str) -> NoReturn:
    raise ProblemError(422, "invalid_image", detail=detail)


def check_image(data: bytes, kind: BrandAssetKind) -> CheckedImage:
    """The image to store for an upload of ``kind``, or 422 ``invalid_image``.
    CPU-bound (up to a few hundred ms for a large PNG): call it off the event loop."""
    if data.startswith(PNG_SIGNATURE):
        return _check_png(data, kind)
    head = data.lstrip(b"\xef\xbb\xbf \t\r\n")[:1]
    if head == b"<":
        return _check_svg(data)
    _invalid("Upload a PNG or an SVG image.")


# --- PNG --------------------------------------------------------------------------------
def _check_png(data: bytes, kind: BrandAssetKind) -> CheckedImage:
    from PIL import Image  # Pillow comes with WeasyPrint; imported only for uploads

    Image.MAX_IMAGE_PIXELS = PNG_MAX_PIXELS
    limit = PNG_MAX_SIDE[kind]
    try:
        with warnings.catch_warnings():
            # Pillow only *warns* between 1x and 2x MAX_IMAGE_PIXELS.
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data), formats=("PNG",)) as image:
                width, height = image.size
                if width > limit or height > limit:  # before a single pixel is decoded
                    _invalid(
                        f"The image is {width} x {height} pixels: at most {limit} x {limit} "
                        f"for a {kind.value}."
                    )
                image.load()
                out = io.BytesIO()
                # Only what is passed here is written: no text chunks, EXIF or ICC
                # profile (icc_profile=None overrides the one read from the file).
                image.save(out, format="PNG", icc_profile=None)
    except ProblemError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        _invalid("The image has too many pixels.")
    except Exception:  # noqa: BLE001 - any decoder failure is a broken upload
        _invalid("The PNG file is damaged or not supported.")
    stored = out.getvalue()
    if len(stored) > MAX_ASSET_BYTES:
        _invalid("The image is too large once re-encoded: use a smaller or simpler PNG.")
    return CheckedImage("image/png", stored, width, height)


# --- SVG --------------------------------------------------------------------------------
_ELEMENTS: Final = frozenset(
    {
        "svg",
        "g",
        "defs",
        "title",
        "desc",
        "path",
        "rect",
        "circle",
        "ellipse",
        "line",
        "polyline",
        "polygon",
        "linearGradient",
        "radialGradient",
        "stop",
        "clipPath",
        "mask",
        "text",
        "tspan",
    }
)
_TEXT_ELEMENTS: Final = frozenset({"title", "desc", "text", "tspan"})
_NO_REFERENCES_INSIDE: Final = frozenset({"clipPath", "mask", "linearGradient", "radialGradient"})

_ATTRIBUTES: Final = frozenset(
    {
        # Paint and compositing
        "fill",
        "fill-opacity",
        "fill-rule",
        "stroke",
        "stroke-width",
        "stroke-linecap",
        "stroke-linejoin",
        "stroke-miterlimit",
        "stroke-dasharray",
        "stroke-dashoffset",
        "stroke-opacity",
        "opacity",
        "clip-rule",
        "clip-path",
        "mask",
        "color",
        "display",
        "visibility",
        "paint-order",
        "vector-effect",
        "shape-rendering",
        # Geometry
        "transform",
        "d",
        "points",
        "x",
        "y",
        "x1",
        "y1",
        "x2",
        "y2",
        "cx",
        "cy",
        "r",
        "rx",
        "ry",
        "fx",
        "fy",
        "fr",
        "dx",
        "dy",
        "width",
        "height",
        "viewBox",
        "preserveAspectRatio",
        "pathLength",
        # Gradients, clip paths and masks
        "offset",
        "stop-color",
        "stop-opacity",
        "gradientUnits",
        "gradientTransform",
        "spreadMethod",
        "clipPathUnits",
        "maskUnits",
        "maskContentUnits",
        # Text
        "font-family",
        "font-size",
        "font-weight",
        "font-style",
        "font-variant",
        "font-stretch",
        "text-anchor",
        "dominant-baseline",
        "alignment-baseline",
        "baseline-shift",
        "letter-spacing",
        "word-spacing",
        "text-decoration",
        "textLength",
        "lengthAdjust",
        # Document
        "id",
        "class",
        "version",
        "baseProfile",
        f"{XML_NS} space",
        f"{XML_NS} lang",
    }
)

_FUNCTIONS: Final[Mapping[str, frozenset[str]]] = {
    "transform": frozenset({"matrix", "translate", "scale", "rotate", "skewx", "skewy"}),
    "gradientTransform": frozenset({"matrix", "translate", "scale", "rotate", "skewx", "skewy"}),
    "fill": frozenset({"url", "rgb", "rgba", "hsl", "hsla"}),
    "stroke": frozenset({"url", "rgb", "rgba", "hsl", "hsla"}),
    "stop-color": frozenset({"rgb", "rgba", "hsl", "hsla"}),
    "color": frozenset({"rgb", "rgba", "hsl", "hsla"}),
    "clip-path": frozenset({"url"}),
    "mask": frozenset({"url"}),
}
"""CSS functions an attribute may use; any other ``(`` is refused."""
_REFERENCE_TARGETS: Final[Mapping[str, frozenset[str]]] = {
    "fill": frozenset({"linearGradient", "radialGradient"}),
    "stroke": frozenset({"linearGradient", "radialGradient"}),
    "clip-path": frozenset({"clipPath"}),
    "mask": frozenset({"mask"}),
}
_REFERENCE_NAMES: Final = {
    "fill": "a gradient",
    "stroke": "a gradient",
    "clip-path": "a clipPath",
    "mask": "a mask",
}

_FUNCTION: Final = re.compile(r"([A-Za-z_-]*)\s*\(")
_URL: Final = re.compile(r"""url\(\s*(['"]?)#([A-Za-z_][A-Za-z0-9_.:-]{0,127})\1\s*\)""")
_FORBIDDEN_CHARACTERS: Final = re.compile(r"[\\<>{}@;\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
"""Never in an attribute value: CSS escapes (``\\75rl(``), blocks, at-rules, rule
separators and control characters."""
_ID: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_.:-]{0,127}")
_FONT_FAMILY: Final = re.compile(r"""[A-Za-z0-9 ,'"_-]{1,200}""")
_LENGTH: Final = re.compile(r"\s*([0-9]+(?:\.[0-9]*)?|\.[0-9]+)\s*(px)?\s*")
_VIEW_BOX: Final = re.compile(
    r"\s*[-+0-9.eE]+[\s,]+[-+0-9.eE]+[\s,]+([0-9.eE+]+)[\s,]+([0-9.eE+]+)\s*"
)


@dataclass(slots=True)
class _Node:
    tag: str
    attributes: dict[str, str]
    depth: int
    children: list[_Node | str] = field(default_factory=list)
    parent: _Node | None = None

    def within(self, names: frozenset[str]) -> bool:
        node: _Node | None = self
        while node is not None:
            if node.tag in names:
                return True
            node = node.parent
        return False

    def size(self) -> int:
        """Elements in this subtree (itself included); iterative (no recursion)."""
        count, stack = 0, [self]
        while stack:
            node = stack.pop()
            count += 1
            stack.extend(child for child in node.children if isinstance(child, _Node))
        return count


class _SvgParser:
    """Builds the checked tree with expat, refusing as it goes."""

    def __init__(self) -> None:
        self.root: _Node | None = None
        self.current: _Node | None = None
        self.elements = 0
        self.ids: dict[str, _Node] = {}
        self.nodes: list[_Node] = []
        parser = expat.ParserCreate(namespace_separator=" ")
        parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
        parser.buffer_text = True
        parser.ordered_attributes = True
        parser.StartDoctypeDeclHandler = self._refuse("a DOCTYPE")
        parser.EntityDeclHandler = self._refuse("an entity declaration")
        parser.UnparsedEntityDeclHandler = self._refuse("an entity declaration")
        parser.NotationDeclHandler = self._refuse("a notation declaration")
        parser.ExternalEntityRefHandler = self._refuse("an external entity")
        parser.SkippedEntityHandler = self._refuse("an entity reference")
        parser.ProcessingInstructionHandler = self._refuse("a processing instruction")
        parser.CommentHandler = lambda _text: None  # dropped
        parser.StartElementHandler = self._start
        parser.EndElementHandler = self._end
        parser.CharacterDataHandler = self._text
        self.parser = parser

    @staticmethod
    def _refuse(what: str) -> Callable[..., NoReturn]:
        def refuse(*_args: object) -> NoReturn:
            _invalid(f"SVG images can't contain {what}.")

        return refuse

    def _start(self, name: str, attributes: list[str]) -> None:
        namespace, _, local = name.rpartition(" ")
        if namespace != SVG_NS:
            where = f"in the namespace {namespace}" if namespace else "without the SVG namespace"
            _invalid(f"The SVG element <{local}> is {where}: only SVG elements are allowed.")
        if local not in _ELEMENTS:
            _invalid(f"SVG images can't contain <{local}> elements.")
        if self.root is None and local != "svg":
            _invalid(f"The image's root element is <{local}>, not <svg>.")
        self.elements += 1
        if self.elements > SVG_MAX_ELEMENTS:
            _invalid(f"The SVG has more than {SVG_MAX_ELEMENTS:,} elements.")
        depth = 1 if self.current is None else self.current.depth + 1
        if depth > SVG_MAX_DEPTH:
            _invalid(f"The SVG is nested too deep (more than {SVG_MAX_DEPTH} levels).")
        node = _Node(local, self._attributes(local, attributes), depth, parent=self.current)
        if self.current is None:
            if self.root is not None:  # expat refuses a second root anyway
                _invalid("The SVG has more than one root element.")
            self.root = node
        else:
            self.current.children.append(node)
        identifier = node.attributes.get("id")
        if identifier is not None:
            if identifier in self.ids:
                _invalid(f'The id "{identifier}" is used twice.')
            self.ids[identifier] = node
        self.nodes.append(node)
        self.current = node

    def _attributes(self, element: str, flat: list[str]) -> dict[str, str]:
        checked: dict[str, str] = {}
        for name, value in zip(flat[::2], flat[1::2], strict=True):
            namespace, _, local = name.rpartition(" ")
            if name not in _ATTRIBUTES:
                if local in ("href", "style") or local.lower().startswith("on"):
                    _invalid(f'SVG images can\'t use the "{local}" attribute (on <{element}>).')
                where = f" (namespace {namespace})" if namespace else ""
                _invalid(f'SVG images can\'t use the "{local}"{where} attribute (on <{element}>).')
            checked[name] = _check_value(element, local if not namespace else name, value)
        return checked

    def _end(self, _name: str) -> None:
        assert self.current is not None  # noqa: S101 - expat pairs the tags
        self.current = self.current.parent

    def _text(self, text: str) -> None:
        if self.current is not None and self.current.tag in _TEXT_ELEMENTS:
            self.current.children.append(text)
        # Text anywhere else is never drawn: dropped.

    def parse(self, data: bytes) -> _Node:
        try:
            self.parser.Parse(data, True)
        except expat.ExpatError as exc:
            _invalid(f"The SVG file is not well-formed XML ({expat.ErrorString(exc.code)}).")
        if self.root is None:
            _invalid("The file has no <svg> element.")
        return self.root


def _check_value(element: str, name: str, value: str) -> str:
    label = f'"{name}" on <{element}>'
    if len(value) > _SVG_MAX_ATTRIBUTE_LENGTH:
        _invalid(f"The attribute {label} is too long.")
    if _FORBIDDEN_CHARACTERS.search(value):
        _invalid(f"The attribute {label} contains characters SVG images can't use here.")
    if name == "id" and not _ID.fullmatch(value):
        _invalid(f"The id {value!r} isn't a plain name.")
    if name == "font-family" and not _FONT_FAMILY.fullmatch(value):
        _invalid(f"The attribute {label} isn't a plain list of font names.")
    allowed = _FUNCTIONS.get(name, frozenset())
    functions = _FUNCTION.findall(value)
    if value.count("(") != len(functions) or value.count(")") != len(functions):
        _invalid(f"The attribute {label} has an expression SVG images can't use.")
    for function in functions:
        if function.lower() not in allowed:
            _invalid(f'The attribute {label} uses "{function}(...)", which isn\'t allowed.')
    if any(function.lower() == "url" for function in functions):
        # url(#id) of this document, alone or before a fallback colour ("url(#g) red").
        match = _URL.match(value.strip())
        if match is None or len(functions) != 1:
            _invalid(f'The attribute {label} may only reference this image ("url(#id)").')
    return value


def _references(node: _Node) -> list[tuple[str, str]]:
    found = []
    for attribute in ("fill", "stroke", "clip-path", "mask"):
        value = node.attributes.get(attribute)
        if value is not None:
            match = _URL.match(value.strip())
            if match is not None:
                found.append((attribute, match.group(2)))
    return found


def _check_references(parser: _SvgParser) -> None:
    budget = len(parser.nodes)
    for node in parser.nodes:
        references = _references(node)
        if references and node.within(_NO_REFERENCES_INSIDE):
            if node.within(frozenset({"mask"})):
                container = "a mask"
            elif node.within(frozenset({"clipPath"})):
                container = "a clipPath"
            else:
                container = "a gradient"
            _invalid(
                f"Nothing inside {container} may reference anything "
                "(no chains of masks, clip paths or gradients)."
            )
        for attribute, identifier in references:
            target = parser.ids.get(identifier)
            if target is None:
                _invalid(f'The reference "url(#{identifier})" names a missing element.')
            if target.tag not in _REFERENCE_TARGETS[attribute]:
                _invalid(
                    f'"{attribute}" must reference {_REFERENCE_NAMES[attribute]}, '
                    f"not a <{target.tag}>."
                )
            budget += target.size()
            if budget > SVG_REFERENCE_BUDGET:
                _invalid(f"The SVG's references draw more than {SVG_REFERENCE_BUDGET:,} elements.")


def _number(text: str | None) -> int | None:
    if text is None:
        return None
    match = _LENGTH.fullmatch(text)
    if match is None:
        return None
    return _pixels(float(match.group(1)))


def _pixels(value: float) -> int | None:
    if not math.isfinite(value):
        return None
    pixels = int(value)
    return pixels if 1 <= pixels <= 4_096 else None


def _size(root: _Node) -> tuple[int | None, int | None]:
    width, height = _number(root.attributes.get("width")), _number(root.attributes.get("height"))
    if width is not None and height is not None:
        return width, height
    view_box = _VIEW_BOX.fullmatch(root.attributes.get("viewBox", ""))
    if view_box is not None:
        try:
            return _pixels(float(view_box.group(1))), _pixels(float(view_box.group(2)))
        except ValueError:
            return None, None
    return None, None


def _escape(text: str, *, attribute: bool = False) -> str:
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    if attribute:
        text = (
            text.replace('"', "&quot;")
            .replace("\t", "&#9;")
            .replace("\n", "&#10;")
            .replace("\r", "&#13;")
        )
    return text


def _serialise(root: _Node) -> bytes:
    """The checked tree as XML: the SVG namespace as the default (no prefixes), only
    allow-listed names, every value escaped. Iterative over a bounded tree."""
    out: list[str] = ['<?xml version="1.0" encoding="UTF-8"?>\n']
    stack: list[tuple[_Node | str, bool]] = [(root, False)]
    while stack:
        item, closing = stack.pop()
        if isinstance(item, str):
            out.append(_escape(item))
            continue
        if closing:
            out.append(f"</{item.tag}>")
            continue
        out.append(f"<{item.tag}")
        if item is root:
            out.append(f' xmlns="{SVG_NS}"')
        for name, value in item.attributes.items():
            attribute = "xml:" + name.rpartition(" ")[2] if name.startswith(XML_NS) else name
            out.append(f' {attribute}="{_escape(value, attribute=True)}"')
        if not item.children:
            out.append("/>")
            continue
        out.append(">")
        stack.append((item, True))
        stack.extend((child, False) for child in reversed(item.children))
    out.append("\n")
    return "".join(out).encode("utf-8")


def _check_svg(data: bytes) -> CheckedImage:
    parser = _SvgParser()
    root = parser.parse(data)
    _check_references(parser)
    stored = _serialise(root)
    if len(stored) > MAX_ASSET_BYTES:
        _invalid("The SVG is too large.")
    width, height = _size(root)
    return CheckedImage("image/svg+xml", stored, width, height)


# --- Storing ----------------------------------------------------------------------------
def asset_url(asset_id: UUID) -> str:
    return f"{ASSET_URL_PREFIX}{asset_id}"


def asset_out(asset: BrandAssetRow) -> BrandAsset:
    return BrandAsset(
        id=asset.id,
        kind=asset.kind,
        content_type="image/svg+xml" if asset.content_type == "image/svg+xml" else "image/png",
        byte_size=asset.byte_size,
        width=asset.width,
        height=asset.height,
        url=asset_url(asset.id),
        created_at=asset.created_at,
    )


def _scope(project_id: UUID | None) -> ColumnElement[bool]:
    if project_id is None:
        return BrandAssetRow.project_id.is_(None)
    return BrandAssetRow.project_id == project_id


async def store_upload(
    db: AsyncSession,
    *,
    project_id: UUID | None,
    kind: BrandAssetKind,
    data: bytes,
    max_bytes: int,
    uploaded_by: UUID | None,
    now: datetime,
) -> BrandAssetRow:
    """Check and store an upload for the global profile (``project_id`` None) or a
    project's: 413 over ``max_bytes``, 422 ``invalid_image``, the same asset again for
    identical bytes, 429 beyond the daily quota. The caller checked the rule."""
    if len(data) > max_bytes:
        raise ProblemError(
            413,
            "content_too_large",
            detail=f"The image is larger than {max_bytes // 1024} KiB.",
        )
    if not data:
        _invalid("The upload is empty: send the image file as the request body.")
    checked = await asyncio.to_thread(check_image, data, kind)
    sha256 = checked.sha256
    scope = "global" if project_id is None else str(project_id)
    await db.execute(select(func.pg_advisory_xact_lock(_UPLOAD_LOCK_SALT, func.hashtext(scope))))
    # The same image again is the same asset, unless the cleanup may be about to delete
    # it (unused and nearly a day old): then it is stored again, with a new id.
    existing = await db.scalar(
        select(BrandAssetRow)
        .where(
            _scope(project_id),
            BrandAssetRow.kind == kind,
            BrandAssetRow.sha256 == sha256,
            or_(BrandAssetRow.created_at > now - DEDUPE_WINDOW, _referenced()),
        )
        .order_by(BrandAssetRow.created_at.desc())
        .limit(1)
    )
    if existing is not None:
        return existing
    recent = (
        await db.execute(
            select(func.count(), func.min(BrandAssetRow.created_at)).where(
                _scope(project_id), BrandAssetRow.created_at > now - UPLOAD_WINDOW
            )
        )
    ).one()
    if int(recent[0] or 0) >= UPLOADS_PER_DAY:
        oldest: datetime = recent[1]
        retry_after = max(1, math.ceil((oldest + UPLOAD_WINDOW - now).total_seconds()))
        raise ProblemError(
            429,
            "too_many_attempts",
            detail=f"At most {UPLOADS_PER_DAY} images a day here. Try again later.",
            headers={"Retry-After": str(retry_after)},
        )
    asset = BrandAssetRow(
        id=uuid4(),
        project_id=project_id,
        kind=kind,
        content_type=checked.content_type,
        data=checked.data,
        byte_size=len(checked.data),
        sha256=sha256,
        width=checked.width,
        height=checked.height,
        created_by_id=uploaded_by,
        created_at=now,
    )
    db.add(asset)
    await db.flush()
    logger.info(
        "brand image uploaded",
        extra={
            "asset_id": str(asset.id),
            "project_id": None if project_id is None else str(project_id),
            "kind": kind.value,
            "content_type": checked.content_type,
            "byte_size": asset.byte_size,
        },
    )
    return asset


# --- Serving ----------------------------------------------------------------------------
def _matches(if_none_match: str | None, etag: str) -> bool:
    if not if_none_match:
        return False
    candidates = [part.strip() for part in if_none_match.split(",")]
    return any(candidate == "*" or candidate.removeprefix("W/") == etag for candidate in candidates)


async def asset_response(db: AsyncSession, asset_id: UUID, if_none_match: str | None) -> Response:
    """``GET /branding/assets/{id}``: the stored bytes with their stored type only."""
    row = (
        await db.execute(
            select(
                BrandAssetRow.kind,
                BrandAssetRow.content_type,
                BrandAssetRow.sha256,
                BrandAssetRow.data,
            ).where(BrandAssetRow.id == asset_id)
        )
    ).first()
    if row is None:
        raise NotFoundProblem("Not found.")
    content_type = "image/svg+xml" if row.content_type == "image/svg+xml" else "image/png"
    extension = "svg" if content_type == "image/svg+xml" else "png"
    etag = f'"{row.sha256}"'
    headers = {
        "ETag": etag,
        "Cache-Control": CACHE_FOREVER,
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": ASSET_CSP,
        "Content-Disposition": f'inline; filename="{BrandAssetKind(row.kind).value}.{extension}"',
    }
    if _matches(if_none_match, etag):
        return Response(status_code=304, headers=headers)
    return Response(content=bytes(row.data), media_type=content_type, headers=headers)


# --- Cleanup ----------------------------------------------------------------------------
def _referenced() -> ColumnElement[bool]:
    return exists().where(
        or_(
            BrandingProfile.logo_asset_id == BrandAssetRow.id,
            BrandingProfile.favicon_asset_id == BrandAssetRow.id,
        )
    )


async def delete_unreferenced(db: AsyncSession, now: datetime) -> int:
    """The hourly cleanup (contract-phase4 section 3.13, rule 5): images uploaded more
    than 24 hours ago that no profile references.

    Two statements: the candidates are locked first (``FOR UPDATE SKIP LOCKED``, so an
    image a branding save is checking right now (``FOR KEY SHARE``) is skipped), then
    deleted only if still unreferenced in a new snapshot (a save that committed in
    between keeps its image)."""
    candidates = (
        (
            await db.execute(
                select(BrandAssetRow.id)
                .where(BrandAssetRow.created_at < now - UNREFERENCED_GRACE, ~_referenced())
                .order_by(BrandAssetRow.created_at)
                .limit(CLEANUP_BATCH)
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )
    if not candidates:
        return 0
    deleted = (
        await db.execute(
            delete(BrandAssetRow)
            .where(BrandAssetRow.id.in_(candidates), ~_referenced())
            .returning(BrandAssetRow.id)
            .execution_options(synchronize_session=False)
        )
    ).all()
    if deleted:
        logger.info("unused brand images deleted", extra={"count": len(deleted)})
    return len(deleted)
