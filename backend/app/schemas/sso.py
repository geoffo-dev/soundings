"""Admin settings -> Single sign-on: the effective configuration, read-only.

SSO is configured through Helm values / ``SOUNDINGS_OIDC_*`` (one provider per
instance); this view shows what is in effect, with secrets masked, the URIs the IdP
client must allow, and whether the provider's discovery document can be used.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.base import ResponseModel

__all__ = ["BreakGlassStatus", "SsoConfig", "SsoDiscovery", "SsoRedirect"]


class SsoRedirect(ResponseModel):
    """What to register at the IdP for one of ``SOUNDINGS_BASE_URLS``."""

    base_url: str
    redirect_uri: str = Field(description="Valid redirect URI: <base_url>/api/v1/auth/callback.")
    post_logout_redirect_uri: str = Field(
        description="Valid post-logout redirect URI: <base_url>/login?signed_out=1."
    )


class BreakGlassStatus(ResponseModel):
    enabled: bool = Field(description="SOUNDINGS_BREAK_GLASS_ENABLED.")
    credentials_set: bool = Field(description="Username and password are both set.")
    available: bool = Field(
        description="Sign-in works now: enabled, credentials set and SSO not configured."
    )


class SsoDiscovery(ResponseModel):
    """The provider's ``/.well-known/openid-configuration``, as sign-in sees it (the same
    cached fetch; fetched now when nothing is cached). Diagnoses ``sso_unavailable``."""

    status: Literal["ok", "unreachable", "invalid", "issuer_mismatch"] = Field(
        description=(
            "ok; unreachable (network error, timeout or HTTP error); invalid (not JSON, "
            "or a required endpoint is missing); issuer_mismatch (its issuer is not "
            "exactly SOUNDINGS_OIDC_ISSUER)."
        )
    )
    end_session_supported: bool = Field(
        description="It has an end_session_endpoint: sign-out also signs out at the IdP."
    )
    checked_at: datetime = Field(description="When the document was fetched (or tried).")


class SsoConfig(ResponseModel):
    """The effective sign-in configuration. Secrets are never returned, only whether
    they are set."""

    enabled: bool = Field(description="SSO is configured (an issuer is set).")
    issuer: str | None
    client_id: str
    client_secret_set: bool
    scopes: list[str]
    groups_claim: str | None = Field(description="Null: group sync is off.")
    external_id_claim: str | None = Field(
        description=(
            "Null: no external-ID matching. Must be an attribute only IdP admins can set "
            "(Keycloak: user-profile edit permission admin only; Entra ID: oid or "
            "employeeid): whoever can choose its value can sign in as the pre-created "
            "user who has it."
        )
    )
    external_id_kind: str | None
    match_verified_email: bool
    auto_create_users: bool
    redirect_uris: list[SsoRedirect] = Field(description="One per base URL, in order.")
    discovery: SsoDiscovery | None = Field(description="Null when SSO is not configured.")
    break_glass: BreakGlassStatus
    dev_login: bool = Field(description="The development login is on (never in production).")
