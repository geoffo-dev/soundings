"""Admin settings -> Single sign-on, read-only (rule ``platform.configure_sso``).

SSO is configured through Helm values / ``SOUNDINGS_OIDC_*``; there is no editing
screen. Business rules: docs/api/contract-phase2.md section 3.10.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.v1.principal import PrincipalDep
from app.api.v1.responses import problems
from app.auth.oidc import get_provider
from app.authz import Rule, require
from app.config import Settings
from app.schemas.sso import BreakGlassStatus, SsoConfig, SsoDiscovery, SsoRedirect

router = APIRouter(prefix="/admin/sso", tags=["admin"])


def _is_set(secret: object) -> bool:
    value = getattr(secret, "get_secret_value", None)
    return bool(value()) if callable(value) else False


def sso_config(settings: Settings, discovery: SsoDiscovery | None) -> SsoConfig:
    """The effective settings, one to one. Secrets are never returned, only whether
    they are set; the break-glass username is not shown either."""
    return SsoConfig(
        enabled=settings.sso_configured,
        issuer=settings.oidc_issuer,
        client_id=settings.oidc_client_id,
        client_secret_set=_is_set(settings.oidc_client_secret),
        scopes=list(settings.oidc_scopes),
        groups_claim=settings.oidc_groups_claim or None,
        external_id_claim=settings.oidc_external_id_claim or None,
        external_id_kind=(
            settings.oidc_external_id_kind or None if settings.oidc_external_id_claim else None
        ),
        match_verified_email=settings.oidc_match_verified_email,
        auto_create_users=settings.oidc_auto_create_users,
        redirect_uris=[
            SsoRedirect(
                base_url=base_url,
                redirect_uri=settings.oidc_redirect_uri(base_url),
                post_logout_redirect_uri=settings.oidc_post_logout_redirect_uri(base_url),
            )
            for base_url in settings.base_urls
        ],
        discovery=discovery if settings.sso_configured else None,
        break_glass=BreakGlassStatus(
            enabled=settings.break_glass_enabled,
            credentials_set=_is_set(settings.break_glass_username)
            and _is_set(settings.break_glass_password),
            available=settings.break_glass_available,
        ),
        dev_login=settings.dev_login_enabled,
    )


@router.get(
    "",
    operation_id="get_sso_config",
    summary="Effective SSO configuration",
    description=(
        "Platform admins (platform.configure_sso). The settings in effect with secrets "
        "masked, the redirect URIs to register at the IdP for each base URL, whether "
        "the provider's discovery document can be used, and the break-glass status."
    ),
    responses=problems(401, 403),
)
async def get_sso_config(request: Request, principal: PrincipalDep) -> SsoConfig:
    require(principal, Rule.PLATFORM_CONFIGURE_SSO)
    settings: Settings = request.app.state.settings
    # The sign-in flow's cached discovery fetch (fetched now only when nothing is
    # cached); no IdP error text is returned.
    discovery = await get_provider(request.app).discovery_status()
    return sso_config(settings, discovery)
