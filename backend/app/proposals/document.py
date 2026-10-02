"""An exported proposal: what goes in it, as Markdown and as the HTML the PDF is made of
(docs/api/contract-phase4.md 3.4).

:class:`ExportDocument` is plain data (gathered from the database by
:mod:`app.proposals.export`, picklable for the PDF child process). Both formats carry
the idea's title; a metadata block (project, idea key, status label, owner, "Exported
<date> by <name>" and, only for people who may see scores, the aggregate line); then
the eight sections in template order, an empty one as "Not written yet". Comments are
never exported.

Safety of the HTML (the PDF): every value goes through Jinja's autoescaping; section
Markdown goes through :func:`app.proposals.markdown.render_html` (no raw HTML, no
images, http(s)/mailto links only); the stylesheet takes nothing user-controlled but
colours that match ``#rrggbb`` here (else the default) and the font key mapped to the
fixed faces in :mod:`app.proposals.fonts` (else Inter). The logo is embedded as a
``data:`` URI (PNG or SVG only); fonts are ``soundings-font:`` URLs. Nothing in the
document names any other URL a renderer could fetch.

No database or application imports beyond plain modules: the PDF child imports this.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Final

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from markupsafe import Markup

from app.proposals.fonts import (
    BRAND_EXT_FAMILY,
    BRAND_FAMILY,
    BRAND_FONTS,
    MONO_EXT_FAMILY,
    MONO_FAMILY,
    MONO_FONT,
    faces_for,
)
from app.proposals.markdown import RenderBudget, close_open_blocks, demote_headings, render_html

__all__ = [
    "DEFAULT_COLOR",
    "DEFAULT_FONT",
    "EMPTY_SECTION",
    "INK",
    "LOGO_TYPES",
    "SHORT_DOCUMENT",
    "SHORT_TITLE",
    "TEMPLATE_DIR",
    "WHITE",
    "ExportBranding",
    "ExportDocument",
    "ExportSection",
    "build_html",
    "build_markdown",
    "contrast",
    "font_face_css",
    "logo_data_uri",
    "readable_on_white",
    "safe_color",
    "text_color_on",
]

TEMPLATE_DIR: Final = Path(__file__).resolve().parent.parent / "templates" / "pdf"
DEFAULT_COLOR: Final = "#1d5fa8"
DEFAULT_FONT: Final = "inter"
INK: Final = "#1f2328"
WHITE: Final = "#ffffff"
MUTED: Final = "#57606a"
"""Secondary text: 6.4:1 on white."""
EMPTY_SECTION: Final = "Not written yet."
SHORT_DOCUMENT: Final = 8_000
"""Section text (characters, all sections) up to which the contents go on the cover
rather than a page of their own (about three pages of prose)..."""
SHORT_TITLE: Final = 90
"""... when the title is short enough to leave the cover room for them."""
LOGO_TYPES: Final = frozenset({"image/png", "image/svg+xml"})
BRAND_STACK: Final = f'"{BRAND_FAMILY}", "{BRAND_EXT_FAMILY}", "DejaVu Sans", sans-serif'
MONO_STACK: Final = f'"{MONO_FAMILY}", "{MONO_EXT_FAMILY}", "DejaVu Sans Mono", monospace'
_HEX: Final = re.compile(r"#[0-9a-f]{6}")
_MD_SPECIAL: Final = re.compile(r"([\\`*_\[\]<>#|~]|&(?=#?[0-9A-Za-z]+;))")
_YAML_BREAKS: Final = {chr(0x85): "\\N", chr(0x2028): "\\L", chr(0x2029): "\\P"}


@dataclass(frozen=True, slots=True)
class ExportSection:
    key: str
    title: str
    body_md: str

    @property
    def empty(self) -> bool:
        return not self.body_md.strip()


@dataclass(frozen=True, slots=True)
class ExportBranding:
    """The project's effective branding, as validated values (contract 3.10)."""

    app_name: str
    primary_color: str = DEFAULT_COLOR
    accent_color: str = DEFAULT_COLOR
    font: str = DEFAULT_FONT
    logo_type: str | None = None
    logo: bytes | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class ExportDocument:
    title: str
    idea_key: str
    project_name: str
    status_label: str
    owner_name: str | None
    exported_at: datetime
    """In the instance time zone."""
    exported_by: str
    sections: tuple[ExportSection, ...]
    branding: ExportBranding
    score: Decimal | None = None
    """The aggregate, only when the exporter may see scores (else ``None``)."""
    score_count: int = 0

    @property
    def score_line(self) -> str | None:
        if self.score is None:
            return None
        count = self.score_count
        return (
            f"Aggregate score {self.score:.1f} from {count} evaluation{'' if count == 1 else 's'}"
        )

    @property
    def exported_on(self) -> str:
        return f"{self.exported_at.day} {self.exported_at:%B %Y}"

    @property
    def owner_label(self) -> str:
        return self.owner_name or "Unassigned"


# --- Markdown --------------------------------------------------------------------------
def _yaml(value: str | None) -> str:
    """A YAML scalar: JSON's double-quoted string (valid YAML) or ``null``."""
    if value is None:
        return "null"
    text = json.dumps(value, ensure_ascii=False)
    for raw, escaped in _YAML_BREAKS.items():
        text = text.replace(raw, escaped)
    return text


def _md_text(value: str) -> str:
    """Text that must stay text inside Markdown (a title, a name)."""
    return _MD_SPECIAL.sub(lambda match: "\\" + match[0], " ".join(value.split()))


def build_markdown(document: ExportDocument) -> str:
    """The Markdown export: front matter, the title and metadata, then each section's
    text verbatim except for the heading demotion (and a closing fence for a section
    that leaves one open). UTF-8, ``\\n`` line endings."""
    front = [
        "---",
        f"title: {_yaml(document.title)}",
        f"idea: {_yaml(document.idea_key)}",
        f"project: {_yaml(document.project_name)}",
        f"status: {_yaml(document.status_label)}",
        f"owner: {_yaml(document.owner_name)}",
        f"exported: {_yaml(document.exported_at.date().isoformat())}",
        f"exported_by: {_yaml(document.exported_by)}",
    ]
    if document.score is not None:
        front += [
            f"aggregate_score: {document.score:.1f}",
            f"evaluations: {document.score_count}",
        ]
    front.append("---")
    meta = [
        f"- Project: {_md_text(document.project_name)}",
        f"- Idea: {_md_text(document.idea_key)}",
        f"- Status: {_md_text(document.status_label)}",
        f"- Owner: {_md_text(document.owner_label)}",
        f"- Exported {document.exported_on} by {_md_text(document.exported_by)}",
    ]
    if document.score_line:
        meta.append(f"- {document.score_line}")
    parts = ["\n".join(front), f"# {_md_text(document.title)}", "\n".join(meta)]
    for section in document.sections:
        body = (
            f"_{EMPTY_SECTION}_"
            if section.empty
            else close_open_blocks(demote_headings(section.body_md)).rstrip("\n")
        )
        parts.append(f"## {_md_text(section.title)}\n\n{body}")
    return "\n\n".join(parts) + "\n"


# --- HTML for the PDF ------------------------------------------------------------------
def safe_color(value: str | None, default: str = DEFAULT_COLOR) -> str:
    """``value`` lower-cased if it is ``#rrggbb``, else ``default``: the only way a colour
    reaches the stylesheet."""
    candidate = (value or "").lower()
    return candidate if _HEX.fullmatch(candidate) else default


def _luminance(color: str) -> float:
    def channel(hex_pair: str) -> float:
        value = int(hex_pair, 16) / 255
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    red, green, blue = (channel(color[i : i + 2]) for i in (1, 3, 5))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast(first: str, second: str) -> float:
    """WCAG contrast ratio of two ``#rrggbb`` colours."""
    light, dark = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def text_color_on(background: str) -> str:
    """White or ink, whichever reads on ``background`` (>= 4.5:1, white preferred)."""
    if contrast(WHITE, background) >= 4.5:
        return WHITE
    if contrast(INK, background) >= 4.5:
        return INK
    return max((WHITE, INK), key=lambda color: contrast(color, background))


def readable_on_white(color: str) -> str:
    """``color``, darkened just enough to reach 4.5:1 on white (brand-coloured text and
    links on the page), else ink."""
    red, green, blue = (int(color[i : i + 2], 16) for i in (1, 3, 5))
    for step in range(21):
        factor = 1 - step / 20
        candidate = "#" + "".join(f"{round(value * factor):02x}" for value in (red, green, blue))
        if contrast(candidate, WHITE) >= 4.5:
            return candidate
    return INK  # pragma: no cover - black always reaches it


def font_face_css(font: str) -> str:
    """``@font-face`` rules for the branding font and the code font, from the fixed
    table only (unknown keys get Inter)."""
    key = font if font in BRAND_FONTS else DEFAULT_FONT
    return "\n".join(
        f'@font-face {{ font-family: "{face.family}"; font-weight: {face.weight}; '
        f'font-style: {face.style}; src: url("{face.url}") format("woff2"); }}'
        for face in (*faces_for(key), *faces_for(MONO_FONT))
    )


def logo_data_uri(branding: ExportBranding) -> str | None:
    if branding.logo is None or branding.logo_type not in LOGO_TYPES:
        return None
    return f"data:{branding.logo_type};base64,{base64.b64encode(branding.logo).decode('ascii')}"


_jinja: Final = Environment(
    loader=FileSystemLoader(TEMPLATE_DIR),
    autoescape=True,
    undefined=StrictUndefined,
    keep_trailing_newline=True,
)


def build_html(document: ExportDocument) -> str:
    """The PDF's HTML: a cover in the project's branding, the contents (on the cover
    when the document is short), the sections."""
    branding = document.branding
    primary = safe_color(branding.primary_color)
    budget = RenderBudget()
    sections = [
        {
            "key": section.key,
            "title": section.title,
            "html": None if section.empty else Markup(render_html(section.body_md, budget)),  # noqa: S704 - sanitised by render_html
        }
        for section in document.sections
    ]
    colors = {
        "primary": primary,
        "brand_text": readable_on_white(primary),
        "link": readable_on_white(primary),
        "ink": INK,
        "muted": MUTED,
    }
    contents_on_cover = (
        len(document.title) <= SHORT_TITLE
        and sum(len(section.body_md) for section in document.sections) <= SHORT_DOCUMENT
    )
    return _jinja.get_template("proposal.html").render(
        document=document,
        app_name=branding.app_name,
        logo=logo_data_uri(branding),
        sections=sections,
        contents_on_cover=contents_on_cover,
        colors=colors,
        font_faces=Markup(font_face_css(branding.font)),  # noqa: S704 - fixed table
        created=document.exported_at.replace(microsecond=0).isoformat(),
        empty_section=EMPTY_SECTION,
        brand_stack=Markup(BRAND_STACK),  # noqa: S704 - constant
        mono_stack=Markup(MONO_STACK),  # noqa: S704 - constant
    )
