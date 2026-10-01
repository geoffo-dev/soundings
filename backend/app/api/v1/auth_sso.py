"""Sign-in methods (Phase 2): SSO through OIDC, the break-glass admin, and sign-out
with the IdP. Contract and business rules: docs/api/contract-phase2.md section 3.

SSO is a browser flow: the SPA *navigates* to ``GET /auth/login``; the IdP sends the
browser back to ``GET /auth/callback``, which signs in and redirects into the SPA.
Sign-out with the IdP is a plain HTML form ``POST`` to ``/auth/logout/redirect``.
The browser never sees IdP tokens or the PKCE verifier: the attempt (nonce, verifier,
redirect URI, next path) lives in ``oidc_login_attempts``, and the browser holds only
``state``, in the URL and the HttpOnly ``soundings_oidc`` cookie.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import math
import secrets
import unicodedata
from datetime import timedelta
from typing import Annotated, Final
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, func, select

from app.api.v1.responses import problems, redirect
from app.auth.break_glass import break_glass_account, credentials_match
from app.auth.cookies import (
    OIDC_COOKIE,
    clear_oidc_cookie,
    read_cookie,
    set_oidc_cookie,
)
from app.auth.group_mapping import groups_overage
from app.auth.group_sync import sync_groups
from app.auth.login_matching import (
    DENIAL_CODES,
    DenialReason,
    LoginDenied,
    match_login,
    record_denial,
)
from app.auth.oidc import OidcError, get_provider
from app.auth.sign_in import current_user, end_current_session, sign_in
from app.auth.throttle import BREAK_GLASS_THROTTLE, LOGIN_THROTTLE, client_key, get_throttle
from app.auth.tokens import hash_token, tokens_match
from app.config import Settings
from app.db import SessionDep, SessionMaker, session_scope
from app.errors import NotFoundProblem, ProblemError
from app.models.base import utcnow
from app.models.enums import AuthMethod
from app.models.user import OidcLoginAttempt
from app.schemas.auth import AuthConfig, BreakGlassLogin, CurrentUser, LoginErrorCode
from app.schemas.base import NoNul

router = APIRouter(prefix="/auth", tags=["auth"])

logger = logging.getLogger("soundings.auth")

LOGIN_PATH: Final = "/api/v1/auth/login"
ATTEMPT_LIFETIME: Final = timedelta(minutes=10)
MAX_LIVE_ATTEMPTS: Final = 10_000
MAX_NEXT_LENGTH: Final = 2048
SIGNED_OUT_PATH: Final = "/login?signed_out=1"

_CALLBACK_ERRORS = (
    "On failure it redirects to /login?error=<code> (sso_unavailable, login_expired, "
    "login_cancelled, sso_failed, no_account, account_disabled, identity_conflict); "
    "the reason is in the audit log. Overlong or unexpected parameter values fail "
    "the flow (a redirect); only a NUL character is a 422."
)


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def _sessionmaker(request: Request) -> SessionMaker:
    sessionmaker: SessionMaker = request.app.state.sessionmaker
    return sessionmaker


def safe_next_path(value: str | None) -> str:
    """``value`` if it is a same-origin SPA path, else ``/`` (open-redirect protection):
    starts with ``/`` (not ``//`` or ``/\\``), no backslash, no whitespace or control
    characters, at most 2048 characters, not under ``/api/``."""
    if not value or len(value) > MAX_NEXT_LENGTH:
        return "/"
    if not value.startswith("/") or value.startswith(("//", "/\\")) or "\\" in value:
        return "/"
    if any(ch.isspace() or unicodedata.category(ch).startswith("C") for ch in value):
        return "/"
    if value == "/api" or value.startswith("/api/"):
        return "/"
    return value


def _login_error(code: LoginErrorCode, next_path: str = "/") -> RedirectResponse:
    query = {"error": code.value}
    if next_path != "/":
        query["next"] = next_path
    return RedirectResponse("/login?" + urlencode(query), status_code=status.HTTP_302_FOUND)


def _with_query(endpoint: str, params: dict[str, str]) -> str:
    return endpoint + ("&" if urlsplit(endpoint).query else "?") + urlencode(params)


@router.get(
    "/config",
    operation_id="get_auth_config",
    summary="Sign-in methods",
    description=(
        "Public. Which sign-in methods the sign-in page shows: the SSO button, the "
        "development login, the break-glass admin form. No secrets."
    ),
)
async def get_auth_config(request: Request) -> AuthConfig:
    settings = _settings(request)
    return AuthConfig(
        sso=settings.sso_configured,
        dev_login=settings.dev_login_enabled,
        break_glass=settings.break_glass_available,
    )


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
    request: Request,
    session: SessionDep,
    next_path: Annotated[
        str | None,
        Query(
            alias="next",
            description="Where to go after signing in: a path such as /ideas/CUST-12.",
        ),
        NoNul,
    ] = None,
) -> RedirectResponse:
    settings = _settings(request)
    if not settings.sso_configured:
        return _login_error(LoginErrorCode.SSO_UNAVAILABLE)
    target = safe_next_path(next_path)

    # The whole flow (cookie included) runs on a configured origin: each public host
    # signs in on itself; any other host goes to the first base URL first.
    host = (request.headers.get("host") or "").lower()
    if host not in settings.allowed_hosts:
        query = "?" + urlencode({"next": target}) if target != "/" else ""
        return RedirectResponse(
            settings.base_urls[0] + LOGIN_PATH + query, status_code=status.HTTP_302_FOUND
        )
    base_url = settings.base_url_for_host(host)

    throttle = get_throttle(request.app, LOGIN_THROTTLE)
    client = client_key(request)
    if throttle.retry_after(client) is not None:
        return _login_error(LoginErrorCode.TOO_MANY_ATTEMPTS)
    throttle.hit(client)

    # The provider's metadata first (cached), so no transaction is open during a fetch.
    metadata = await get_provider(request.app).metadata()
    if metadata is None:
        return _login_error(LoginErrorCode.SSO_UNAVAILABLE)

    now = utcnow()
    live = await session.scalar(
        select(func.count()).select_from(OidcLoginAttempt).where(OidcLoginAttempt.expires_at > now)
    )
    if (live or 0) >= MAX_LIVE_ATTEMPTS:
        logger.warning("too many sso sign-ins in progress", extra={"live_attempts": live})
        return _login_error(LoginErrorCode.SSO_UNAVAILABLE)

    state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
    redirect_uri = settings.oidc_redirect_uri(base_url)
    await session.execute(delete(OidcLoginAttempt).where(OidcLoginAttempt.expires_at <= now))
    session.add(
        OidcLoginAttempt(
            state_hash=hash_token(state),
            nonce=nonce,
            code_verifier=verifier,
            redirect_uri=redirect_uri,
            next_path=target,
            created_at=now,
            expires_at=now + ATTEMPT_LIFETIME,
        )
    )
    location = _with_query(
        metadata.authorization_endpoint,
        {
            "response_type": "code",
            "client_id": settings.oidc_client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(settings.oidc_scopes),
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge.rstrip(b"=").decode("ascii"),
            "code_challenge_method": "S256",
        },
    )
    response = RedirectResponse(location, status_code=status.HTTP_302_FOUND)
    set_oidc_cookie(response, request, settings, state)
    return response


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
    request: Request,
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
    del error_description  # IdP text: never shown, stored or logged
    settings = _settings(request)
    sessionmaker = _sessionmaker(request)

    def finish(response: RedirectResponse) -> RedirectResponse:
        clear_oidc_cookie(response, request, settings)  # every outcome
        return response

    if not settings.sso_configured or settings.oidc_issuer is None:
        return finish(_login_error(LoginErrorCode.SSO_UNAVAILABLE))
    issuer = settings.oidc_issuer

    # State: in the URL and in this browser's cookie, and a stored attempt. The attempt
    # is deleted now (single use), committed even if a later step fails.
    cookie_state = read_cookie(request, settings, OIDC_COOKIE)
    attempt = None
    if state and cookie_state and tokens_match(state, cookie_state):
        async with session_scope(sessionmaker) as db:
            attempt = await db.scalar(
                select(OidcLoginAttempt)
                .where(OidcLoginAttempt.state_hash == hash_token(state))
                .with_for_update()
            )
            if attempt is not None:
                await db.delete(attempt)
    if attempt is None:
        return finish(_login_error(LoginErrorCode.LOGIN_EXPIRED))
    next_path = attempt.next_path

    async def deny(
        reason: DenialReason,
        *,
        code: LoginErrorCode | None = None,
        subject: str | None = None,
    ) -> RedirectResponse:
        async with session_scope(sessionmaker) as db:
            await record_denial(db, reason, method=AuthMethod.SSO, issuer=issuer, subject=subject)
        return finish(_login_error(code or DENIAL_CODES[reason], next_path))

    if attempt.expires_at <= utcnow():
        return await deny("login_expired")
    if iss is not None and iss != issuer:  # RFC 9207: mix-up defence
        return await deny("sso_failed")
    if error is not None:
        return await deny("login_cancelled" if error == "access_denied" else "sso_failed")
    if not code:
        return await deny("sso_failed")

    provider = get_provider(request.app)
    metadata = await provider.metadata()
    if metadata is None:
        return await deny("sso_failed", code=LoginErrorCode.SSO_UNAVAILABLE)
    try:
        tokens = await provider.exchange_code(
            metadata,
            code=code,
            redirect_uri=attempt.redirect_uri,
            code_verifier=attempt.code_verifier,
        )
        id_token = tokens.get("id_token")
        if not isinstance(id_token, str):
            raise OidcError("no id token in the token response")
        claims = await provider.validate_id_token(metadata, id_token, nonce=attempt.nonce)
    except OidcError as exc:
        logger.warning("sso sign-in failed", extra={"reason": exc.reason})
        return await deny("sso_failed")
    subject: str = claims["sub"]

    if groups_overage(claims, settings.oidc_groups_claim):
        return await deny("groups_overage", subject=subject)

    response = RedirectResponse(next_path, status_code=status.HTTP_302_FOUND)
    async with session_scope(sessionmaker) as db:
        matched = await match_login(db, settings, issuer=issuer, subject=subject, claims=claims)
        if isinstance(matched, LoginDenied):
            await record_denial(
                db,
                matched.reason,
                method=AuthMethod.SSO,
                user_id=matched.user_id,
                issuer=issuer,
                subject=subject,
            )
            denied = matched.code
        else:
            denied = None
            await sync_groups(db, matched.user, claims, settings)
            matched.identity.last_login_at = utcnow()
            await sign_in(
                db,
                request,
                response,
                matched.user,
                method=AuthMethod.SSO,
                id_token=id_token,
                details={"identity_id": matched.identity.id, "matched_by": matched.matched_by},
            )
    if denied is not None:
        return finish(_login_error(denied, next_path))
    return finish(response)


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
async def break_glass_login(
    body: BreakGlassLogin, request: Request, response: Response
) -> CurrentUser:
    settings = _settings(request)
    if not settings.break_glass_available:
        raise NotFoundProblem
    sessionmaker = _sessionmaker(request)
    throttle = get_throttle(request.app, BREAK_GLASS_THROTTLE)
    client = client_key(request)

    retry_after = throttle.retry_after(client)
    if retry_after is not None:
        if throttle.first_refusal(client):  # one audit entry per lockout, not per request
            async with session_scope(sessionmaker) as db:
                await record_denial(db, "too_many_attempts", method=AuthMethod.BREAK_GLASS)
        raise ProblemError(
            429,
            "too_many_attempts",
            detail="Too many failed sign-ins from your network. Wait and try again.",
            headers={"Retry-After": str(max(1, math.ceil(retry_after)))},
        )
    if not credentials_match(settings, body.username, body.password):
        throttle.hit(client)
        async with session_scope(sessionmaker) as db:
            await record_denial(db, "invalid_credentials", method=AuthMethod.BREAK_GLASS)
        raise ProblemError(401, "invalid_credentials", detail="The username or password is wrong.")

    async with session_scope(sessionmaker) as db:
        account = await break_glass_account(db)
        if not account.is_active:
            await record_denial(
                db, "account_disabled", method=AuthMethod.BREAK_GLASS, user_id=account.id
            )
            disabled = True
        else:
            disabled = False
            await sign_in(db, request, response, account, method=AuthMethod.BREAK_GLASS)
    if disabled:
        raise ProblemError(
            403, "account_disabled", detail="The break-glass account is deactivated."
        )
    return current_user(account, AuthMethod.BREAK_GLASS)


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
async def logout_redirect(request: Request, session: SessionDep) -> RedirectResponse:
    settings = _settings(request)
    if _cross_origin(request, settings):
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    # The provider's metadata first (cached), so no transaction is open during a fetch.
    metadata = await get_provider(request.app).metadata() if settings.sso_configured else None
    response = RedirectResponse(SIGNED_OUT_PATH, status_code=status.HTTP_303_SEE_OTHER)
    ended = await end_current_session(session, request, response)
    if ended is None or ended.auth_method != AuthMethod.SSO:
        return response
    if metadata is None or metadata.end_session_endpoint is None:
        return response
    base_url = settings.base_url_for_host(request.headers.get("host"))
    params = {
        "client_id": settings.oidc_client_id,
        "post_logout_redirect_uri": settings.oidc_post_logout_redirect_uri(base_url),
    }
    if ended.id_token:
        params["id_token_hint"] = ended.id_token
    response.headers["location"] = _with_query(metadata.end_session_endpoint, params)
    return response


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}".lower()


def _cross_origin(request: Request, settings: Settings) -> bool:
    """A sign-out post from another origin: ``Sec-Fetch-Site`` other than
    ``same-origin``, or an ``Origin`` that is none of the base URLs' origins.
    (SameSite=Lax doesn't stop a form post from a sibling subdomain: same site.)"""
    fetch_site = request.headers.get("sec-fetch-site")
    if fetch_site is not None and fetch_site != "same-origin":
        return True
    origin = request.headers.get("origin")
    return origin is not None and origin.lower() not in {_origin(url) for url in settings.base_urls}
