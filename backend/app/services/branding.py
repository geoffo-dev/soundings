"""Branding: effective branding (project override -> global -> built-in default), its
cache, the global and project profiles, and the derived values for emails
(contract-phase4 section 3.10, ADR 0012).

**Resolution, field by field:** the project's override, else the global profile (the
row with ``project_id`` null), else :data:`~app.schemas.branding.DEFAULT_BRANDING`.
:func:`resolve` returns every field (the footer and the image ids too);
:func:`effective_branding` the public shape (``EffectiveBranding``). Use these
everywhere branding is shown: ``GET /branding`` (global), the public pages, emails
(:func:`email_branding`: global for staff, the project's for public submitters) and
exported PDFs (:func:`logo_image` for the logo's bytes).

**Cache.** Resolved branding is cached per process for :data:`CACHE_TTL` seconds, per
database engine and project. A save in this process invalidates its entries at once
and again after its commit (a reader in between can't keep the old values); other
replicas see a change within the TTL. Branding is read on every public page, SPA
start and email, and changes a few times a year.

**Safety.** Colours are ``#rrggbb`` and the font a :class:`BrandFont` key, validated
by the request schema and checked again by the database, so nothing but those reaches
CSS; the email font stacks are fixed strings (:data:`EMAIL_FONT_STACKS`); the app name
and footer are text, escaped wherever they are shown. Text and link colours derived
from a brand colour keep WCAG AA contrast (:func:`text_on`, :func:`readable_on`).
"""

from __future__ import annotations

import time
import weakref
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal
from uuid import UUID, uuid4

from sqlalchemy import ColumnElement, Engine, delete, event, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.authz import Resource, Rule, require
from app.domain.principal import Principal
from app.email.model import Branding as EmailBranding
from app.errors import ProblemError
from app.models.base import utcnow
from app.models.branding import BrandAsset as BrandAssetRow
from app.models.branding import BrandingProfile
from app.models.enums import BrandAssetKind, BrandFont, EmailType
from app.models.idea import Idea
from app.models.project import Project
from app.models.user import User
from app.schemas.branding import (
    DEFAULT_BRANDING,
    BrandAsset,
    BrandingSettings,
    BrandingUpdate,
    EffectiveBranding,
    InheritedBranding,
)
from app.schemas.users import UserRef
from app.services import audit
from app.services.brand_assets import asset_out, asset_url

__all__ = [
    "CACHE_TTL",
    "EMAIL_FONT_STACKS",
    "PROFILE_FIELDS",
    "ResolvedBranding",
    "contrast",
    "effective_branding",
    "email_branding",
    "email_branding_for",
    "global_settings",
    "invalidate",
    "logo_image",
    "project_settings",
    "readable_on",
    "resolve",
    "text_on",
    "update_global",
    "update_project",
]

CACHE_TTL: Final = 5.0
"""Seconds a resolved branding is reused in one process: the most another replica
can lag behind a save."""

WHITE: Final = "#ffffff"
INK: Final = "#1a1a1f"
"""The email layout's text colour."""
BLACK: Final = "#000000"
AA_CONTRAST: Final = 4.5

_SYSTEM_SANS: Final = (
    "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif"
)
EMAIL_FONT_STACKS: Final[Mapping[BrandFont, str]] = {
    BrandFont.INTER: f"Inter,{_SYSTEM_SANS}",
    BrandFont.IBM_PLEX_SANS: f"'IBM Plex Sans',{_SYSTEM_SANS}",
    BrandFont.SOURCE_SERIF_4: "'Source Serif 4','Source Serif Pro',Georgia,'Times New Roman',serif",
    BrandFont.ATKINSON_HYPERLEGIBLE: f"'Atkinson Hyperlegible',{_SYSTEM_SANS}",
}
"""Emails name the chosen family first and end in fonts every client has (nothing is
downloaded). Fixed strings: no branding input is ever part of them."""

PROFILE_FIELDS: Final = (
    "app_name",
    "primary_color",
    "accent_color",
    "font",
    "email_footer",
    "logo",
    "favicon",
)
"""Field names as audited (``details.fields``)."""

_SUBMITTER_EMAILS: Final = frozenset(
    {EmailType.SUBMISSION_RECEIVED, EmailType.SUBMISSION_STATUS_CHANGED}
)


# --- Colours ----------------------------------------------------------------------------
def _channel(value: int) -> float:
    srgb = value / 255
    return srgb / 12.92 if srgb <= 0.04045 else ((srgb + 0.055) / 1.055) ** 2.4


def _rgb(colour: str) -> tuple[int, int, int]:
    return int(colour[1:3], 16), int(colour[3:5], 16), int(colour[5:7], 16)


def _luminance(colour: str) -> float:
    red, green, blue = (_channel(value) for value in _rgb(colour))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast(first: str, second: str) -> float:
    """WCAG 2 contrast ratio of two ``#rrggbb`` colours (1 to 21)."""
    lighter, darker = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def text_on(background: str) -> str:
    """Text colour for a ``background`` in a brand colour (a button, a band): white,
    else the ink colour, else whichever of white and black reads best (one of them
    always reaches 4.5:1)."""
    for candidate in (WHITE, INK):
        if contrast(candidate, background) >= AA_CONTRAST:
            return candidate
    return max((WHITE, BLACK), key=lambda candidate: contrast(candidate, background))


def readable_on(colour: str, background: str = WHITE) -> str:
    """``colour``, darkened just enough to reach 4.5:1 on ``background`` (links in a
    brand colour on a white card)."""
    red, green, blue = _rgb(colour)
    for step in range(21):
        factor = 1 - step / 20
        candidate = "#" + "".join(f"{round(value * factor):02x}" for value in (red, green, blue))
        if contrast(candidate, background) >= AA_CONTRAST:
            return candidate
    return BLACK


# --- Resolution -------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ResolvedBranding:
    """Every field of a profile, resolved (override -> global -> default)."""

    app_name: str
    primary_color: str
    accent_color: str
    font: BrandFont
    email_footer: str | None
    logo_asset_id: UUID | None
    favicon_asset_id: UUID | None

    def effective(self) -> EffectiveBranding:
        return EffectiveBranding(
            app_name=self.app_name,
            primary_color=self.primary_color,
            accent_color=self.accent_color,
            font=self.font,
            logo_url=None if self.logo_asset_id is None else asset_url(self.logo_asset_id),
            favicon_url=None if self.favicon_asset_id is None else asset_url(self.favicon_asset_id),
        )

    def email(self) -> EmailBranding:
        """The email layout's branding: the app name as the wordmark, the primary colour
        with a contrast-checked text colour, links readable on the white card, the
        font stack and the footer (no images: emails load nothing)."""
        return EmailBranding(
            product_name=self.app_name,
            accent=self.primary_color,
            accent_text=text_on(self.primary_color),
            link=readable_on(self.primary_color),
            font_stack=EMAIL_FONT_STACKS[self.font],
            footer_text=self.email_footer,
        )


DEFAULTS: Final = ResolvedBranding(
    app_name=DEFAULT_BRANDING.app_name,
    primary_color=DEFAULT_BRANDING.primary_color,
    accent_color=DEFAULT_BRANDING.accent_color,
    font=DEFAULT_BRANDING.font,
    email_footer=None,
    logo_asset_id=None,
    favicon_asset_id=None,
)


def _layer(profiles: Iterable[BrandingProfile], base: ResolvedBranding) -> ResolvedBranding:
    """``base`` with each field the first of ``profiles`` sets."""
    ordered = list(profiles)

    def pick(field: str, fallback: Any) -> Any:
        for profile in ordered:
            value = getattr(profile, field)
            if value is not None:
                return value
        return fallback

    return ResolvedBranding(
        app_name=pick("app_name", base.app_name),
        primary_color=pick("primary_color", base.primary_color),
        accent_color=pick("accent_color", base.accent_color),
        font=BrandFont(pick("font", base.font)),
        email_footer=pick("email_footer", base.email_footer),
        logo_asset_id=pick("logo_asset_id", base.logo_asset_id),
        favicon_asset_id=pick("favicon_asset_id", base.favicon_asset_id),
    )


class _Cache:
    """Per process: ``{engine: {project_id | None: (expires, resolved)}}``. Keyed by
    the engine (weakly), so two apps on two databases in one process never share."""

    def __init__(self) -> None:
        self._entries: weakref.WeakKeyDictionary[
            Engine, dict[UUID | None, tuple[float, ResolvedBranding]]
        ] = weakref.WeakKeyDictionary()

    @staticmethod
    def _engine(db: AsyncSession) -> Engine | None:
        bind = db.get_bind()
        engine = getattr(bind, "engine", bind)
        return engine if isinstance(engine, Engine) else None

    def get(self, db: AsyncSession, project_id: UUID | None) -> ResolvedBranding | None:
        engine = self._engine(db)
        entry = None if engine is None else self._entries.get(engine, {}).get(project_id)
        if entry is None or entry[0] < time.monotonic():
            return None
        return entry[1]

    def put(self, db: AsyncSession, project_id: UUID | None, value: ResolvedBranding) -> None:
        engine = self._engine(db)
        if engine is not None:
            self._entries.setdefault(engine, {})[project_id] = (time.monotonic() + CACHE_TTL, value)

    def drop(self, db: AsyncSession, project_id: UUID | Literal["all"] | None) -> None:
        engine = self._engine(db)
        entries = None if engine is None else self._entries.get(engine)
        if entries is None:
            return
        if project_id == "all":
            entries.clear()
        else:
            entries.pop(project_id, None)


_CACHE: Final = _Cache()


def invalidate(db: AsyncSession, project_id: UUID | Literal["all"] | None) -> None:
    """Forget cached branding now and once more when ``db``'s transaction ends (so a
    read in between, committed or not, isn't kept): ``"all"`` after a global save
    (every project inherits from it), else one project's."""
    _CACHE.drop(db, project_id)

    def forget(_session: Session, *_args: object) -> None:
        _CACHE.drop(db, project_id)

    for identifier in ("after_commit", "after_rollback"):
        event.listen(db.sync_session, identifier, forget, once=True)


async def _profiles(
    db: AsyncSession, project_id: UUID | None
) -> dict[UUID | None, BrandingProfile]:
    clause: ColumnElement[bool] = BrandingProfile.project_id.is_(None)
    if project_id is not None:
        clause = or_(clause, BrandingProfile.project_id == project_id)
    return {
        profile.project_id: profile
        for profile in await db.scalars(select(BrandingProfile).where(clause))
    }


async def resolve(
    db: AsyncSession, project_id: UUID | None = None, *, cached: bool = True
) -> ResolvedBranding:
    """The effective branding of ``project_id`` (``None``: the global branding); two
    indexed rows at most. ``cached=False`` reads the database (in a transaction that
    changed branding: never caches what isn't committed)."""
    if cached and (hit := _CACHE.get(db, project_id)) is not None:
        return hit
    profiles = await _profiles(db, project_id)
    layers = [profiles[key] for key in (project_id, None) if key in profiles]
    resolved = _layer(layers, DEFAULTS)
    if cached:
        _CACHE.put(db, project_id, resolved)
    return resolved


async def effective_branding(db: AsyncSession, project_id: UUID | None = None) -> EffectiveBranding:
    """What to show for ``project_id`` (``None``: the global branding, as the signed-in
    app uses it): the public pages, ``GET /branding``."""
    return (await resolve(db, project_id)).effective()


async def email_branding(db: AsyncSession, project_id: UUID | None = None) -> EmailBranding:
    return (await resolve(db, project_id)).email()


async def email_branding_for(
    db: AsyncSession, email_type: EmailType, idea_id: UUID | None
) -> EmailBranding:
    """Staff emails (notifications, digests, tests) use the global branding; emails to
    a public submitter use their idea's project's branding."""
    project_id = None
    if email_type in _SUBMITTER_EMAILS and idea_id is not None:
        project_id = await db.scalar(select(Idea.project_id).where(Idea.id == idea_id))
    return await email_branding(db, project_id)


async def logo_image(db: AsyncSession, project_id: UUID | None) -> tuple[str, bytes] | None:
    """The effective logo's content type and bytes (to embed in a PDF), if any."""
    resolved = await resolve(db, project_id)
    if resolved.logo_asset_id is None:
        return None
    row = (
        await db.execute(
            select(BrandAssetRow.content_type, BrandAssetRow.data).where(
                BrandAssetRow.id == resolved.logo_asset_id
            )
        )
    ).first()
    return None if row is None else (row.content_type, bytes(row.data))


# --- Settings ---------------------------------------------------------------------------
async def _assets(db: AsyncSession, ids: Iterable[UUID | None]) -> dict[UUID, BrandAsset]:
    wanted = {asset_id for asset_id in ids if asset_id is not None}
    if not wanted:
        return {}
    rows = await db.scalars(select(BrandAssetRow).where(BrandAssetRow.id.in_(wanted)))
    return {row.id: asset_out(row) for row in rows}


async def _user_ref(db: AsyncSession, user_id: UUID | None) -> UserRef | None:
    if user_id is None:
        return None
    user = await db.get(User, user_id)
    return None if user is None else UserRef(id=user.id, display_name=user.display_name)


def _inherited(base: ResolvedBranding, assets: Mapping[UUID, BrandAsset]) -> InheritedBranding:
    return InheritedBranding(
        app_name=base.app_name,
        primary_color=base.primary_color,
        accent_color=base.accent_color,
        font=base.font,
        email_footer=base.email_footer,
        logo=assets.get(base.logo_asset_id) if base.logo_asset_id else None,
        favicon=assets.get(base.favicon_asset_id) if base.favicon_asset_id else None,
    )


async def _settings(
    db: AsyncSession, scope: Literal["global", "project"], project_id: UUID | None
) -> BrandingSettings:
    profiles = await _profiles(db, project_id)
    own = profiles.get(project_id)
    global_layers = [profiles[None]] if None in profiles else []
    base = DEFAULTS if scope == "global" else _layer(global_layers, DEFAULTS)
    effective = _layer([own] if own is not None else [], base)
    assets = await _assets(
        db,
        [
            own.logo_asset_id if own else None,
            own.favicon_asset_id if own else None,
            base.logo_asset_id,
            base.favicon_asset_id,
        ],
    )
    return BrandingSettings(
        scope=scope,
        app_name=own.app_name if own else None,
        primary_color=own.primary_color if own else None,
        accent_color=own.accent_color if own else None,
        font=own.font if own else None,
        email_footer=own.email_footer if own else None,
        logo=assets.get(own.logo_asset_id) if own and own.logo_asset_id else None,
        favicon=assets.get(own.favicon_asset_id) if own and own.favicon_asset_id else None,
        inherited=_inherited(base, assets),
        effective=effective.effective(),
        updated_at=own.updated_at if own else None,
        updated_by=await _user_ref(db, own.updated_by_id if own else None),
    )


async def global_settings(db: AsyncSession, principal: Principal) -> BrandingSettings:
    """``GET /admin/branding`` (``platform.edit_branding``)."""
    require(principal, Rule.PLATFORM_EDIT_BRANDING)
    return await _settings(db, "global", None)


async def project_settings(db: AsyncSession, project: Project) -> BrandingSettings:
    """``GET /projects/{slug}/branding``; the caller checked ``project.edit_settings``."""
    return await _settings(db, "project", project.id)


def _invalid_asset(detail: str) -> ProblemError:
    return ProblemError(422, "invalid_asset", detail=detail)


async def _check_assets(db: AsyncSession, body: BrandingUpdate, project_id: UUID | None) -> None:
    """Each image must be an upload of that kind for this profile. The rows stay
    locked (``FOR KEY SHARE``) until commit, so the cleanup can't delete them under
    the save (it skips locked rows)."""
    for asset_id, kind in (
        (body.logo_asset_id, BrandAssetKind.LOGO),
        (body.favicon_asset_id, BrandAssetKind.FAVICON),
    ):
        if asset_id is None:
            continue
        row = (
            await db.execute(
                select(BrandAssetRow.kind, BrandAssetRow.project_id)
                .where(BrandAssetRow.id == asset_id)
                .with_for_update(read=True, key_share=True)
            )
        ).first()
        if row is None or row.project_id != project_id:
            where = "for the global branding" if project_id is None else "for this project"
            raise _invalid_asset(f"Upload the {kind.value} {where} first, then save.")
        if row.kind != kind:
            raise _invalid_asset(f"That image was uploaded as a {row.kind}, not a {kind.value}.")


_VALUE_FIELDS: Final = ("app_name", "primary_color", "accent_color", "font", "email_footer")


def _values(body: BrandingUpdate) -> dict[str, Any]:
    values: dict[str, Any] = {field: getattr(body, field) for field in _VALUE_FIELDS}
    values["logo_asset_id"] = body.logo_asset_id
    values["favicon_asset_id"] = body.favicon_asset_id
    return values


def _changed(before: BrandingProfile | None, values: Mapping[str, Any]) -> list[str]:
    changed = []
    for field in _VALUE_FIELDS:
        if (getattr(before, field) if before else None) != values[field]:
            changed.append(field)
    for name in ("logo", "favicon"):
        if (getattr(before, f"{name}_asset_id") if before else None) != values[f"{name}_asset_id"]:
            changed.append(name)
    return changed


async def _save(
    db: AsyncSession, principal: Principal, project_id: UUID | None, body: BrandingUpdate
) -> list[str]:
    """Replace the profile with ``body`` (all null: no row at all); the changed field
    names. Concurrent first saves of one profile meet on the unique ``project_id``."""
    await _check_assets(db, body, project_id)
    scope = (
        BrandingProfile.project_id.is_(None)
        if project_id is None
        else BrandingProfile.project_id == project_id
    )
    values = _values(body)
    now = utcnow()
    try:
        async with db.begin_nested():
            await db.execute(
                insert(BrandingProfile)
                .values(id=uuid4(), project_id=project_id, created_at=now, updated_at=now)
                .on_conflict_do_nothing(index_elements=[BrandingProfile.project_id])
            )
            profile = await db.scalar(
                select(BrandingProfile)
                .where(scope)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            assert profile is not None  # noqa: S101 - inserted or already there
            changed = _changed(profile, values)
            if all(value is None for value in values.values()):
                await db.execute(delete(BrandingProfile).where(BrandingProfile.id == profile.id))
            elif changed:
                for field, value in values.items():
                    setattr(profile, field, value)
                profile.updated_by_id = principal.user_id
                profile.updated_at = now
            await db.flush()
    except IntegrityError as exc:
        # An image deleted by the cleanup between the check and the save (its lock
        # makes this all but impossible): the same answer as an unknown image.
        raise _invalid_asset("That image is no longer available: upload it again.") from exc
    invalidate(db, "all" if project_id is None else project_id)
    return changed


async def update_global(
    db: AsyncSession, principal: Principal, body: BrandingUpdate
) -> BrandingSettings:
    """``PUT /admin/branding``: the complete global profile; audited ``branding.update``
    with the changed field names."""
    require(principal, Rule.PLATFORM_EDIT_BRANDING)
    changed = await _save(db, principal, None, body)
    if changed:
        await audit.record(
            db,
            "branding.update",
            actor=principal,
            details={"rule": Rule.PLATFORM_EDIT_BRANDING, "fields": changed},
        )
    return await _settings(db, "global", None)


def require_writable(project: Project) -> None:
    """Project branding and uploads are read-only in an archived project."""
    if project.archived_at is not None:
        raise ProblemError(
            409,
            "project_archived",
            detail="The project is archived: unarchive it to change its settings.",
        )


async def update_project(
    db: AsyncSession,
    principal: Principal,
    project: Project,
    resource: Resource,
    body: BrandingUpdate,
) -> BrandingSettings:
    """``PUT /projects/{slug}/branding``: the complete override (``{}`` removes it);
    audited ``project.update`` with ``fields: ["branding"]``. The caller loaded the
    project with ``project.edit_settings``."""
    del resource  # checked by the caller (load_project with project.edit_settings)
    require_writable(project)
    changed = await _save(db, principal, project.id, body)
    if changed:
        await audit.record(
            db,
            "project.update",
            actor=principal,
            target_type="project",
            target_id=project.id,
            project_id=project.id,
            details={"rule": Rule.PROJECT_EDIT_SETTINGS, "fields": ["branding"]},
        )
    return await _settings(db, "project", project.id)
