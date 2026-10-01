"""Sign-in methods (Phase 2): SSO through OIDC, the break-glass admin, and sign-out
with the IdP. Contract and business rules: docs/api/contract-phase2.md section 3.

SSO is a browser flow: the SPA *navigates* to ``GET /auth/login``; the IdP sends the
browser back to ``GET /auth/callback``, which signs in and redirects into the SPA.
Sign-out with the IdP is a plain HTML form ``POST`` to ``/auth/logout/redirect``.
The browser never sees IdP tokens or the PKCE verifier.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status
from fastapi.responses import RedirectResponse

from app.api.v1.responses import problems, redirect
from app.errors import NotImplementedProblem
from app.schemas.auth import AuthConfig, BreakGlassLogin, CurrentUser
from app.schemas.base import NoNul

router = APIRouter(prefix="/auth", tags=["auth"])

_CALLBACK_ERRORS = (
    "On failure it redirects to /login?error=<code> (sso_unavailable, login_expired, "
    "login_cancelled, sso_failed, no_account, account_disabled, identity_conflict); "
    "the reason is in the audit log. Overlong or unexpected parameter values fail "
    "the flow (a redirect); only a NUL character is a 422."
)


@router.get(
    "/config",
    operation_id="get_auth_config",
    summary="Sign-in methods",
    description=(
        "Public. Which sign-in methods the sign-in page shows: the SSO button (and its "
        "label), the development login, the break-glass admin form. No secrets."
    ),
)
async def get_auth_config() -> AuthConfig:
    raise NotImplementedProblem


@router.get(
    "/login",
    operation_id="sso_login",
    status_code=status.HTTP_302_FOUND,
    response_class=RedirectResponse,
    summary="Start SSO sign-in",
    description=(
        "Public; navigate the browser here (not fetch). Starts the authorization code "
        "flow with PKCE: stores the attempt server-side, sets the short-lived HttpOnly "
        "soundings_oidc cookie and redirects (302) to the IdP. The redirect URI is "
        "<base URL of this host>/api/v1/auth/callback; a host that is not one of "
        "SOUNDINGS_BASE_URLS is first redirected to the same path on the first base "
        "URL. next must be a same-origin SPA path of at most 2048 characters (else /). "
        "SSO not configured or the IdP unreachable: 302 to "
        "/login?error=sso_unavailable; too many starts from this client IP: 302 to "
        "/login?error=too_many_attempts."
    ),
    responses=redirect(302, "To the IdP's authorization endpoint (or /login?error=...)."),
)
async def sso_login(
    next_path: Annotated[
        str | None,
        Query(
            alias="next",
            description="Where to go after signing in: a path such as /ideas/CUST-12.",
        ),
        NoNul,
    ] = None,
) -> RedirectResponse:
    raise NotImplementedProblem


@router.get(
    "/callback",
    operation_id="sso_callback",
    status_code=status.HTTP_302_FOUND,
    response_class=RedirectResponse,
    summary="Finish SSO sign-in",
    description=(
        "Public; the IdP redirects the browser here. Checks state against the "
        "soundings_oidc cookie, exchanges the code (with the PKCE verifier), validates "
        "the ID token, matches the user, syncs groups, starts a session (rotating any "
        "existing one) and redirects (302) to the saved next path. " + _CALLBACK_ERRORS
    ),
    responses=redirect(302, "To the saved next path, or /login?error=<code>."),
)
async def sso_callback(
    code: Annotated[str | None, Query(), NoNul] = None,
    state: Annotated[str | None, Query(), NoNul] = None,
    error: Annotated[str | None, Query(), NoNul] = None,
    error_description: Annotated[
        str | None, Query(description="Never shown or logged."), NoNul
    ] = None,
    iss: Annotated[
        str | None,
        Query(description="RFC 9207 issuer; must match when present."),
        NoNul,
    ] = None,
) -> RedirectResponse:
    raise NotImplementedProblem


@router.post(
    "/break-glass",
    operation_id="break_glass_login",
    summary="Sign in as the break-glass admin",
    description=(
        "Public. The local platform admin whose credentials come from a K8s Secret, for "
        "first sign-in before SSO is configured. 404 unless available (enabled, "
        "credentials set, SSO not configured). Sets the session cookies like any "
        "sign-in. 401 invalid_credentials (wrong username or password, same answer); "
        "403 account_disabled; 429 too_many_attempts (with Retry-After). Every attempt "
        "is audited."
    ),
    responses=problems(401, 403, 404, 422, 429),
)
async def break_glass_login(body: BreakGlassLogin) -> CurrentUser:
    raise NotImplementedProblem


@router.post(
    "/logout/redirect",
    operation_id="logout_redirect",
    status_code=status.HTTP_303_SEE_OTHER,
    response_class=RedirectResponse,
    summary="Sign out, also at the IdP",
    description=(
        "Public; submit as an HTML form POST (top-level navigation, no body). Ends the "
        "session like logout, then redirects (303) to the IdP's end-session endpoint "
        "(SSO sessions, when the IdP has one) with id_token_hint (when stored), "
        "client_id and post_logout_redirect_uri=<base URL>/login?signed_out=1; "
        "otherwise straight to /login?signed_out=1. A cross-origin post ends nothing "
        "and redirects to /. Always redirects. POST /auth/logout (204) is unchanged."
    ),
    responses=redirect(303, "To the IdP's end-session endpoint or /login?signed_out=1."),
)
async def logout_redirect() -> RedirectResponse:
    raise NotImplementedProblem
