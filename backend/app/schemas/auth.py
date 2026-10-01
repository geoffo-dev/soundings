"""Sign-in: the signed-in user, which sign-in methods to offer, the development login
stub and the break-glass admin. SSO itself is browser redirects (``GET /auth/login``,
``GET /auth/callback``), so it has no request or response bodies.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import ConfigDict, Field

from app.schemas.base import RequestModel, ResponseModel
from app.schemas.users import UserRef

__all__ = [
    "AuthConfig",
    "BreakGlassLogin",
    "CurrentUser",
    "DevLoginRequest",
    "LoginErrorCode",
]


class CurrentUser(UserRef):
    """The signed-in user (``GET /auth/me``, sign-in responses), also used for the dev
    login picker.

    Pending (contract-phase2 section 7): ``auth_method: AuthMethod | None`` lands with
    the identity and frontend builds, which update the tests and mocks that build a
    ``CurrentUser`` in the same change.
    """

    email: str
    is_platform_admin: bool


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
