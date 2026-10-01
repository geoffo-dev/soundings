"""Sign-in: the signed-in user, which sign-in methods to offer, the development login
stub and the break-glass admin. SSO itself is browser redirects (``GET /auth/login``,
``GET /auth/callback``), so it has no request or response bodies.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import ConfigDict, Field

from app.models.enums import AuthMethod
from app.schemas.base import RequestModel, ResponseModel
from app.schemas.users import UserRef

__all__ = [
    "AuthConfig",
    "BreakGlassLogin",
    "CurrentUser",
    "DevLoginRequest",
    "LoginErrorCode",
    "LoginPrompt",
]


class CurrentUser(UserRef):
    """The signed-in user (``GET /auth/me``, sign-in responses), also used for the dev
    login picker."""

    email: str
    is_platform_admin: bool
    auth_method: AuthMethod | None = Field(
        default=None,
        description=(
            "How this session was started: sso, break_glass (show the break-glass "
            "banner) or dev_login. Null only in the dev login picker (no session)."
        ),
    )


class DevLoginRequest(RequestModel):
    user_id: UUID


class AuthConfig(ResponseModel):
    """Which sign-in methods the sign-in page offers (public, no secrets)."""

    sso: bool = Field(
        description='SSO is configured: show the "Sign in with SSO" button (GET /auth/login).'
    )
    dev_login: bool = Field(description="The development login picker is enabled.")
    break_glass: bool = Field(
        description=(
            "The break-glass admin form is available: enabled, credentials set, and SSO "
            "not configured."
        )
    )


class BreakGlassLogin(RequestModel):
    """Break-glass admin credentials (from the K8s Secret). Not trimmed: passwords are
    compared exactly."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    username: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=1024)


class LoginPrompt(StrEnum):
    """``GET /auth/login?prompt=``: passed on to the IdP's authorization request
    (OIDC Core 3.1.2.1) together with ``max_age=0``, for "Use a different account"
    after ``no_account`` or ``identity_conflict``."""

    LOGIN = "login"
    """Ask for credentials again, even with a running IdP session."""
    SELECT_ACCOUNT = "select_account"
    """Show the IdP's account picker (Entra ID, Google). Keycloak 26 ignores it; the
    ``max_age=0`` sent with it makes Keycloak ask to sign in again, with "Restart
    login" to switch account."""


class LoginErrorCode(StrEnum):
    """``/login?error=<code>`` after a failed SSO sign-in (contract-phase2 section 4.2).

    The sign-in page shows a message per code; details are in the audit log only.
    """

    SSO_UNAVAILABLE = "sso_unavailable"
    """SSO is not configured, or the IdP could not be reached to start sign-in."""
    TOO_MANY_ATTEMPTS = "too_many_attempts"
    """Too many sign-in starts from this network (per client IP): wait a minute."""
    LOGIN_EXPIRED = "login_expired"
    """Missing, mismatched, used or expired state (took over 10 minutes, another tab,
    back button): start again."""
    LOGIN_CANCELLED = "login_cancelled"
    """The IdP answered ``error=access_denied`` (the user cancelled or was refused)."""
    SSO_FAILED = "sso_failed"
    """Any other IdP error, a failed token exchange, an invalid ID token, or a groups
    claim the IdP left out because there were too many groups (Entra ID overage)."""
    NO_ACCOUNT = "no_account"
    """No user matched and auto-create is off (or impossible): ask an admin."""
    ACCOUNT_DISABLED = "account_disabled"
    """The matched user is deactivated, or is a service or break-glass account."""
    IDENTITY_CONFLICT = "identity_conflict"
    """The matched user is already linked to another account at this IdP, the
    external-ID claim doesn't match theirs (or is missing), or the email is taken: an
    admin must resolve it."""
