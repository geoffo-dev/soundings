"""Branding: app name, logo, favicon, colours, font and email footer (SPEC section 10).

One global profile (Admin settings -> Branding, ``platform.edit_branding``) and an
optional override per project (project settings -> Branding, ``project.edit_settings``).
Every field may be left empty to inherit: project override -> global -> built-in
default (:data:`DEFAULT_BRANDING`). Where each applies (contract-phase4 section 3.10):
the signed-in app always uses the **global** branding; a project's override shows where
the project faces outward: its public form and tracking page, its emails to public
submitters, and its exported proposals.

Every value that can reach CSS is validated here (and again by the database): colours
are ``#rrggbb`` hex only, fonts a :class:`~app.models.enums.BrandFont` key, so no
branding input can inject CSS. Images are uploaded separately (raw body, see
``app/api/v1/branding.py``) and referenced by id.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Final, Literal
from uuid import UUID

from pydantic import AfterValidator, Field, StringConstraints

from app.models.enums import BrandAssetKind, BrandFont
from app.schemas.base import RequestModel, ResponseModel, SingleLine, reject_control
from app.schemas.users import UserRef

__all__ = [
    "APP_NAME_MAX_LENGTH",
    "DEFAULT_BRANDING",
    "EMAIL_FOOTER_MAX_LENGTH",
    "EMAIL_FOOTER_MAX_LINES",
    "AppName",
    "BrandAsset",
    "BrandAssetKind",
    "BrandFont",
    "BrandImageType",
    "BrandingDefaults",
    "BrandingSettings",
    "BrandingUpdate",
    "EffectiveBranding",
    "EmailFooter",
    "HexColor",
    "InheritedBranding",
    "normalise_hex_color",
]

APP_NAME_MAX_LENGTH: Final = 40
EMAIL_FOOTER_MAX_LENGTH: Final = 500
EMAIL_FOOTER_MAX_LINES: Final = 5

_HEX_COLOR = re.compile(r"#[0-9A-Fa-f]{6}")


def normalise_hex_color(value: str) -> str:
    """``#RRGGBB`` -> ``#rrggbb``; anything else (names, ``#abc``, alpha, ``rgb()``,
    trailing text) is a ``ValueError``. The only colour format branding accepts."""
    if not _HEX_COLOR.fullmatch(value):
        raise ValueError("must be a hex colour such as #1d5fa8")
    return value.lower()


HexColor = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=7, max_length=7),
    AfterValidator(normalise_hex_color),
]
"""A colour: ``#`` and six hex digits, stored and returned lower-case."""

AppName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=APP_NAME_MAX_LENGTH),
    SingleLine,
]
"""The product name shown in the header, page titles, emails and PDFs: one line."""


def _footer(value: str) -> str:
    lines = value.split("\n")
    if len(lines) > EMAIL_FOOTER_MAX_LINES:
        raise ValueError(f"at most {EMAIL_FOOTER_MAX_LINES} lines")
    for line in lines:
        reject_control(line)  # tabs, CR, other controls and bidi controls
    return "\n".join(line.rstrip() for line in lines)


EmailFooter = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=EMAIL_FOOTER_MAX_LENGTH),
    AfterValidator(_footer),
]
"""Plain text (no Markdown or HTML: shown escaped), up to 5 lines (``\\n``), e.g. the
company's name and address. Emails show it under the message, before the unsubscribe
links."""

BrandImageType = Literal["image/png", "image/svg+xml"]
"""What a stored image is: uploads are re-encoded as PNG, or checked and re-serialised
SVG (contract-phase4 section 3.11)."""


@dataclass(frozen=True, slots=True)
class BrandingDefaults:
    app_name: str = "Soundings"
    primary_color: str = "#1d5fa8"
    accent_color: str = "#1d5fa8"
    font: BrandFont = BrandFont.INTER


DEFAULT_BRANDING: Final = BrandingDefaults()
"""Built-in values for fields neither the project nor the global profile sets (ADR 0009:
Soundings, deep ocean blue, Inter). No default logo (the app name is the wordmark), no
default footer; the favicon is the SPA's bundled one."""


class BrandAsset(ResponseModel):
    """An uploaded logo or favicon. Immutable: a new image is a new asset (new URL)."""

    id: UUID
    kind: BrandAssetKind
    content_type: BrandImageType
    byte_size: int
    width: int | None = Field(description="Pixels; null for an SVG without a size.")
    height: int | None
    url: str = Field(
        description=(
            "Where the image is served, relative to the app: /api/v1/branding/assets/{id} "
            "(public, cached for a year: the content of an id never changes)."
        )
    )
    created_at: datetime


class EffectiveBranding(ResponseModel):
    """What to show: every field resolved (override -> global -> default).

    Apply ``primary_color``, ``accent_color`` and ``font`` through the CSS variables
    (``--brand-primary``, ``--brand-accent``, ``--brand-font``; the SPA derives
    contrast-safe tokens from them, lib/branding.ts)."""

    app_name: str
    primary_color: str = Field(description="#rrggbb")
    accent_color: str = Field(description="#rrggbb")
    font: BrandFont
    logo_url: str | None = Field(description="Null: show app_name as the wordmark.")
    favicon_url: str | None = Field(description="Null: the bundled favicon.")


class InheritedBranding(ResponseModel):
    """What an empty field of this profile falls back to: for the global profile the
    built-in defaults, for a project the global profile's effective values."""

    app_name: str
    primary_color: str
    accent_color: str
    font: BrandFont
    email_footer: str | None
    logo: BrandAsset | None
    favicon: BrandAsset | None


class BrandingSettings(ResponseModel):
    """A branding profile as stored (null = inherit), for its settings form."""

    scope: Literal["global", "project"]
    app_name: str | None
    primary_color: str | None = Field(description="#rrggbb, or null to inherit.")
    accent_color: str | None
    font: BrandFont | None
    email_footer: str | None
    logo: BrandAsset | None
    favicon: BrandAsset | None
    inherited: InheritedBranding = Field(description="What each null field falls back to.")
    effective: EffectiveBranding = Field(description="The result: what people see.")
    updated_at: datetime | None = Field(description="Null: never saved (all inherited).")
    updated_by: UserRef | None


class BrandingUpdate(RequestModel):
    """``PUT``: the complete profile. Omitted or null fields inherit (so an empty body
    resets the profile). ``logo_asset_id`` / ``favicon_asset_id`` must be images uploaded
    for this profile (same scope) and of that kind (else 422 ``invalid_asset``)."""

    app_name: AppName | None = None
    primary_color: HexColor | None = None
    accent_color: HexColor | None = None
    font: BrandFont | None = None
    email_footer: EmailFooter | None = None
    logo_asset_id: UUID | None = None
    favicon_asset_id: UUID | None = None
