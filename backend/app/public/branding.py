"""A project's effective branding for its public pages (contract-phase4 section 3.10).

Field by field: the project's override, else the global profile, else the built-in
default (:data:`app.schemas.branding.DEFAULT_BRANDING`). Images resolve to their public
URL (``/api/v1/branding/assets/{id}``). Two indexed reads (the unique
``branding_profiles.project_id``), no writes.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.branding import BrandingProfile
from app.schemas.branding import DEFAULT_BRANDING, EffectiveBranding

__all__ = ["asset_url", "effective_branding"]


def asset_url(asset_id: UUID | None) -> str | None:
    return None if asset_id is None else f"/api/v1/branding/assets/{asset_id}"


async def effective_branding(db: AsyncSession, project_id: UUID | None) -> EffectiveBranding:
    """The branding of ``project_id`` (``None``: the global branding)."""
    clause: ColumnElement[bool] = BrandingProfile.project_id.is_(None)
    if project_id is not None:
        clause = or_(clause, BrandingProfile.project_id == project_id)
    found = {
        profile.project_id: profile
        for profile in await db.scalars(select(BrandingProfile).where(clause))
    }
    order = [project_id, None] if project_id is not None else [None]
    layers = [found[key] for key in order if key in found]

    def pick(field: str) -> object:
        for profile in layers:
            value = getattr(profile, field)
            if value is not None:
                return value
        return None

    logo = pick("logo_asset_id")
    favicon = pick("favicon_asset_id")
    return EffectiveBranding(
        app_name=str(pick("app_name") or DEFAULT_BRANDING.app_name),
        primary_color=str(pick("primary_color") or DEFAULT_BRANDING.primary_color),
        accent_color=str(pick("accent_color") or DEFAULT_BRANDING.accent_color),
        font=pick("font") or DEFAULT_BRANDING.font,  # type: ignore[arg-type]
        logo_url=asset_url(logo if isinstance(logo, UUID) else None),
        favicon_url=asset_url(favicon if isinstance(favicon, UUID) else None),
    )
