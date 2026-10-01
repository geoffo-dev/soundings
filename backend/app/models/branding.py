"""Branding: one global profile, optional per-project overrides, and uploaded images.

Each field of a profile is nullable: null means "inherit". The effective branding of
a project is, field by field, its override, else the global profile, else the built-in
default (``app.schemas.branding.DEFAULT_BRANDING``). The global profile is the row with
``project_id`` null (at most one: ``UNIQUE NULLS NOT DISTINCT``). Colours are stored as
lower-case ``#rrggbb`` and fonts as a :class:`~app.models.enums.BrandFont` key, both
checked here too, so nothing but a validated value can ever reach CSS.

Logos and favicons are the only uploads (``brand_assets``): small images stored in the
database and served by the app (``GET /api/v1/branding/assets/{id}``), never modified
(a new image is a new row, so URLs can be cached for ever). Raster uploads are decoded
and re-encoded as PNG; SVGs are checked against an allow-list and stored re-serialised
(ADR 0012). Assets no profile references are deleted by the hourly cleanup after 24
hours. See docs/api/contract-phase4.md section 3.10-3.12.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, utcnow
from app.models.enums import BrandAssetKind, BrandFont
from app.models.types import str_enum

__all__ = [
    "BRAND_ASSET_CONTENT_TYPES",
    "HEX_COLOR_PATTERN",
    "BrandAsset",
    "BrandingProfile",
]

HEX_COLOR_PATTERN = r"^#[0-9a-f]{6}$"
"""A stored colour: ``#`` and six lower-case hex digits (the API normalises input)."""

BRAND_ASSET_CONTENT_TYPES = ("image/png", "image/svg+xml")
"""What stored assets are: re-encoded PNG, or allow-listed and re-serialised SVG."""

MAX_ASSET_BYTES = 1024 * 1024
"""Database ceiling; the API's limit is ``SOUNDINGS_BRANDING_MAX_UPLOAD_BYTES``."""


class BrandAsset(UUIDPrimaryKeyMixin, Base):
    """An uploaded logo or favicon for the global profile (``project_id`` null) or one
    project. Immutable; served with its stored ``content_type`` only."""

    __tablename__ = "brand_assets"
    __table_args__ = (
        CheckConstraint("content_type IN ('image/png', 'image/svg+xml')", name="content_type"),
        CheckConstraint(f"byte_size BETWEEN 1 AND {MAX_ASSET_BYTES}", name="byte_size_range"),
        CheckConstraint("octet_length(data) = byte_size", name="byte_size_matches"),
        CheckConstraint(
            "(width IS NULL OR width BETWEEN 1 AND 4096)"
            " AND (height IS NULL OR height BETWEEN 1 AND 4096)",
            name="dimensions_range",
        ),
        # Upload quota per scope and the cleanup of unreferenced assets.
        Index("ix_brand_assets_project_id_created_at", "project_id", "created_at"),
    )

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE")
    )
    kind: Mapped[BrandAssetKind] = mapped_column(str_enum(BrandAssetKind, "kind"))
    content_type: Mapped[str] = mapped_column(String(20))
    data: Mapped[bytes] = mapped_column(LargeBinary)
    byte_size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    # Pixels for PNG; for SVG from its width/height or viewBox when given, else null.
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )


class BrandingProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The global branding (``project_id`` null) or one project's override. Null fields
    inherit (project -> global -> built-in default)."""

    __tablename__ = "branding_profiles"
    __table_args__ = (
        UniqueConstraint("project_id", postgresql_nulls_not_distinct=True),
        CheckConstraint(f"primary_color ~ '{HEX_COLOR_PATTERN}'", name="primary_color_hex"),
        CheckConstraint(f"accent_color ~ '{HEX_COLOR_PATTERN}'", name="accent_color_hex"),
        CheckConstraint("char_length(app_name) BETWEEN 1 AND 40", name="app_name_length"),
    )

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE")
    )
    app_name: Mapped[str | None] = mapped_column(String(40))
    primary_color: Mapped[str | None] = mapped_column(String(7))
    accent_color: Mapped[str | None] = mapped_column(String(7))
    font: Mapped[BrandFont | None] = mapped_column(str_enum(BrandFont, "font"))
    # Plain text (no Markdown or HTML), at most 5 lines; shown at the foot of emails.
    email_footer: Mapped[str | None] = mapped_column(String(500))
    logo_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("brand_assets.id", ondelete="SET NULL")
    )
    favicon_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("brand_assets.id", ondelete="SET NULL")
    )
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
