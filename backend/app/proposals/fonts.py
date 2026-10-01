"""The fonts bundled for PDF exports (ADR 0011; docs/api/contract-phase4.md 3.10).

The files in ``app/assets/fonts/`` are the ``@fontsource`` 5.3.0 builds (``woff2``,
``latin`` and ``latin-ext`` subsets) of the four branding fonts plus IBM Plex Mono for
code, each with its SIL Open Font License text (``*-LICENSE.txt``). The PDF stylesheet
names them only as ``soundings-font:<name>`` URLs, which the renderer's URL fetcher
answers from :data:`FONT_FILES` (a fixed name -> file map): no part of a URL ever
becomes a file path.

This module is plain data (no imports from the application), so the PDF child
process can use it without loading the database layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

__all__ = [
    "BRAND_EXT_FAMILY",
    "BRAND_FAMILY",
    "BRAND_FONTS",
    "FONT_DIR",
    "FONT_FACES",
    "FONT_FILES",
    "FONT_SCHEME",
    "MONO_EXT_FAMILY",
    "MONO_FAMILY",
    "MONO_FONT",
    "FontFace",
    "faces_for",
]

FONT_DIR: Final = Path(__file__).resolve().parent.parent / "assets" / "fonts"
FONT_SCHEME: Final = "soundings-font:"

BRAND_FAMILY: Final = "Soundings Brand"
"""The CSS family of the chosen branding font's ``latin`` subset (never a system name,
so an installed font of the same name can't stand in for it)."""
BRAND_EXT_FAMILY: Final = "Soundings Brand Ext"
"""Its ``latin-ext`` subset: a family of its own, so the PDF names the two subsets
apart (sharing one name confuses text extraction); the font stack lists both, then
DejaVu (in the image) for anything else."""
MONO_FAMILY: Final = "Soundings Mono"
MONO_EXT_FAMILY: Final = "Soundings Mono Ext"
MONO_FONT: Final = "mono"
"""Key of the code font (IBM Plex Mono): not a branding choice."""

_FILE_STEMS: Final[dict[str, str]] = {
    # BrandFont value -> @fontsource file prefix
    "inter": "inter",
    "ibm_plex_sans": "ibm-plex-sans",
    "source_serif_4": "source-serif-4",
    "atkinson_hyperlegible": "atkinson-hyperlegible",
    MONO_FONT: "ibm-plex-mono",
}

_STYLES: Final[dict[str, tuple[tuple[int, str], ...]]] = {
    "inter": ((400, "normal"), (600, "normal"), (700, "normal"), (400, "italic")),
    "ibm_plex_sans": ((400, "normal"), (600, "normal"), (700, "normal"), (400, "italic")),
    "source_serif_4": ((400, "normal"), (600, "normal"), (700, "normal"), (400, "italic")),
    # Atkinson Hyperlegible has no 600: CSS font matching uses the 700 for it.
    "atkinson_hyperlegible": ((400, "normal"), (700, "normal"), (400, "italic")),
    MONO_FONT: ((400, "normal"),),
}

BRAND_FONTS: Final = frozenset(key for key in _STYLES if key != MONO_FONT)
"""The branding font keys (``BrandFont`` values; a test pins the two together)."""


@dataclass(frozen=True, slots=True)
class FontFace:
    """One ``@font-face`` rule: a family's weight and style in one subset."""

    font: str
    weight: int
    style: str
    subset: str  # "latin" | "latin-ext"

    @property
    def name(self) -> str:
        """The URL name: ``inter-600``, ``inter-600-ext``, ``inter-400-italic``..."""
        name = f"{self.font}-{self.weight}"
        if self.style == "italic":
            name += "-italic"
        if self.subset == "latin-ext":
            name += "-ext"
        return name

    @property
    def url(self) -> str:
        return FONT_SCHEME + self.name

    @property
    def file_name(self) -> str:
        return f"{_FILE_STEMS[self.font]}-{self.subset}-{self.weight}-{self.style}.woff2"

    @property
    def family(self) -> str:
        if self.font == MONO_FONT:
            return MONO_EXT_FAMILY if self.subset == "latin-ext" else MONO_FAMILY
        return BRAND_EXT_FAMILY if self.subset == "latin-ext" else BRAND_FAMILY


FONT_FACES: Final[tuple[FontFace, ...]] = tuple(
    FontFace(font, weight, style, subset)
    for font, styles in _STYLES.items()
    for weight, style in styles
    for subset in ("latin", "latin-ext")
)

FONT_FILES: Final[dict[str, str]] = {face.name: face.file_name for face in FONT_FACES}
"""``soundings-font:`` name -> file in :data:`FONT_DIR`: the only fonts a PDF can use."""


def faces_for(font: str) -> tuple[FontFace, ...]:
    """The faces of one font key (unknown keys have none)."""
    return tuple(face for face in FONT_FACES if face.font == font)
