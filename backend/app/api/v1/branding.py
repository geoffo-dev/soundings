"""Branding: the effective branding (public), the global profile (Admin settings ->
Branding), project overrides, and uploaded logos and favicons.

Images are uploaded as the raw request body (``Content-Type`` an image type; no
multipart), checked and normalised (raster -> PNG; SVG allow-listed and re-serialised),
stored in the database, and served by ``get_brand_asset`` with a fixed content type,
``nosniff`` and a sandboxing CSP. Business rules: docs/api/contract-phase4.md sections
3.10-3.12, ADR 0012.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Query, status
from fastapi.responses import Response

from app.api.v1.principal import PrincipalDep
from app.api.v1.projects import ProjectSlug
from app.api.v1.responses import binary, binary_body, problems
from app.errors import NotImplementedProblem
from app.models.enums import BrandAssetKind
from app.schemas.branding import BrandAsset, BrandingSettings, BrandingUpdate, EffectiveBranding

router = APIRouter(tags=["branding"])

UPLOAD_TYPES = ("image/png", "image/svg+xml")
"""What an upload may be (detected from the bytes, not the header): PNG or SVG, for
logos and favicons alike (browsers take PNG favicons; no ICO or WebP decoders exposed)."""

AssetKind = Annotated[BrandAssetKind, Query(description="What the image is for.")]

_UPLOAD = binary_body(
    *UPLOAD_TYPES,
    description=(
        "The image file itself as the body (no multipart, no JSON): PNG or SVG. At most "
        "SOUNDINGS_BRANDING_MAX_UPLOAD_BYTES (512 KiB by default); PNGs at most 2048 x "
        "2048 pixels (favicons 512 x 512); SVGs at most 2,000 elements, nested at most "
        "32 deep."
    ),
)
_UPLOAD_ERRORS = (
    "201 with the stored image. 413 content_too_large; 422 invalid_image (not PNG or "
    "SVG, damaged, too many pixels, or an SVG with anything outside the allow-list: "
    "a DOCTYPE, scripts, event handlers, styles, external references, foreign objects, "
    "too many elements...); 429 too_many_attempts (20 uploads per profile per day)."
)


@router.get(
    "/branding",
    operation_id="get_branding",
    summary="The app's branding",
    description=(
        "Public: the global effective branding (app name, colours, font, logo and favicon "
        "URLs) for the SPA shell, the sign-in page and every signed-in page. Project "
        "overrides are applied only where a project faces outward (public form and "
        "tracking pages, submitter emails, exported proposals)."
    ),
)
async def get_branding() -> EffectiveBranding:
    raise NotImplementedProblem


@router.get(
    "/branding/assets/{asset_id}",
    operation_id="get_brand_asset",
    response_class=Response,
    summary="A logo or favicon",
    description=(
        "Public. The stored bytes with their stored type (image/png or image/svg+xml), "
        "X-Content-Type-Options: nosniff, Content-Security-Policy: default-src 'none'; "
        "style-src 'unsafe-inline'; sandbox, and Cache-Control: public, max-age=31536000, "
        'immutable (ids never change content). ETag "<sha256>"; If-None-Match -> 304.'
    ),
    responses={
        **binary(
            200,
            "The image.",
            "image/png",
            "image/svg+xml",
            headers={"ETag": "The image's SHA-256, quoted.", "Cache-Control": "Cached for a year."},
        ),
        304: {"description": "Not modified (If-None-Match matched)."},
        **problems(404),
    },
)
async def get_brand_asset(
    asset_id: Annotated[UUID, Path(description="The image's id.")],
) -> Response:
    raise NotImplementedProblem


@router.get(
    "/admin/branding",
    operation_id="get_global_branding",
    summary="Admin settings: branding",
    description="platform.edit_branding (session only): the global profile as stored.",
    responses=problems(401, 403),
)
async def get_global_branding(principal: PrincipalDep) -> BrandingSettings:
    raise NotImplementedProblem


@router.put(
    "/admin/branding",
    operation_id="update_global_branding",
    summary="Change the global branding",
    description=(
        "platform.edit_branding (session only). The complete profile: omitted or null "
        "fields use the built-in defaults. Image ids must be global uploads of the right "
        "kind (422 invalid_asset). Audited (branding.update, field names only)."
    ),
    responses=problems(401, 403, 422),
)
async def update_global_branding(principal: PrincipalDep, body: BrandingUpdate) -> BrandingSettings:
    raise NotImplementedProblem


@router.post(
    "/admin/branding/assets",
    operation_id="upload_global_brand_asset",
    status_code=status.HTTP_201_CREATED,
    summary="Upload a global logo or favicon",
    description=(
        "platform.edit_branding (session only). " + _UPLOAD_ERRORS + " Use it with "
        "update_global_branding; images no profile uses are deleted after 24 hours."
    ),
    responses=problems(401, 403, 413, 422, 429),
    openapi_extra=_UPLOAD,
)
async def upload_global_brand_asset(principal: PrincipalDep, kind: AssetKind) -> BrandAsset:
    raise NotImplementedProblem


@router.get(
    "/projects/{slug}/branding",
    operation_id="get_project_branding",
    summary="Project settings: branding",
    description=(
        "project.edit_settings (session only): the project's override as stored; inherited "
        "values come from the global profile."
    ),
    responses=problems(401, 403, 404),
)
async def get_project_branding(principal: PrincipalDep, slug: ProjectSlug) -> BrandingSettings:
    raise NotImplementedProblem


@router.put(
    "/projects/{slug}/branding",
    operation_id="update_project_branding",
    summary="Change the project's branding",
    description=(
        "project.edit_settings (session only). The complete override: omitted or null "
        "fields inherit the global branding (an empty body removes the override). Image "
        "ids must be this project's uploads of the right kind (422 invalid_asset). 409 "
        "project_archived. Audited as project.update."
    ),
    responses=problems(401, 403, 404, 409, 422),
)
async def update_project_branding(
    principal: PrincipalDep, slug: ProjectSlug, body: BrandingUpdate
) -> BrandingSettings:
    raise NotImplementedProblem


@router.post(
    "/projects/{slug}/branding/assets",
    operation_id="upload_project_brand_asset",
    status_code=status.HTTP_201_CREATED,
    summary="Upload a project logo or favicon",
    description=(
        "project.edit_settings (session only). " + _UPLOAD_ERRORS + " Use it with "
        "update_project_branding; 409 project_archived."
    ),
    responses=problems(401, 403, 404, 409, 413, 422, 429),
    openapi_extra=_UPLOAD,
)
async def upload_project_brand_asset(
    principal: PrincipalDep, slug: ProjectSlug, kind: AssetKind
) -> BrandAsset:
    raise NotImplementedProblem
