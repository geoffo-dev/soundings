"""Request dependencies shared by the API routers: the signed-in user.

:func:`get_current_user` authenticates the request through the principal sources in
:mod:`app.auth.sources` (the session cookie in Phase 1; API keys in Phase 5), stores
the :class:`~app.domain.principal.Principal` on ``request.state`` for
:func:`app.api.v1.principal.get_principal`, and returns its user. Routes take
``PrincipalDep``, never this directly.
"""

from __future__ import annotations

import dataclasses
from typing import Annotated

from fastapi import Depends, Request, Security
from fastapi.security import APIKeyCookie, HTTPAuthorizationCredentials, HTTPBearer

from app.auth.cookies import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE
from app.auth.sources import UnauthorizedProblem, authenticate
from app.authz.keys import check_route_for_key
from app.db import SessionDep
from app.models.user import User

__all__ = [
    "CSRF_COOKIE",
    "CSRF_HEADER",
    "SESSION_COOKIE",
    "CurrentUserDep",
    "api_key_bearer",
    "get_current_user",
    "not_activity",
    "session_cookie",
]

_KEEP_ALIVE = "keep_session_alive"


def not_activity(request: Request) -> None:
    """Route-level dependency (``dependencies=[Depends(not_activity)]``): this request
    doesn't keep the session alive (the bell's poll, contract-phase3 section 3.2).
    Route-level dependencies run before the route's parameters, so the principal is
    resolved after this."""
    setattr(request.state, _KEEP_ALIVE, False)


session_cookie = APIKeyCookie(
    name=SESSION_COOKIE,
    scheme_name="session",
    description=(
        "Server-side session cookie set by every sign-in (SSO via GET /api/v1/auth/login, "
        "the break-glass admin, the development login). Named __Host-soundings_session "
        "(and __Host-soundings_csrf) whenever cookies are Secure, i.e. over HTTPS and in "
        f"production. Unsafe methods must also send the {CSRF_HEADER} header equal to the "
        f"CSRF cookie ({CSRF_COOKIE} or __Host-{CSRF_COOKIE})."
    ),
    auto_error=False,
)


api_key_bearer = HTTPBearer(
    scheme_name="api_key",
    bearerFormat="sdg_…",
    description=(
        "A personal API key (Settings -> API keys), sent as Authorization: Bearer "
        "sdg_<lookup id>_<secret>. It acts as its owner, live, narrowed by its scopes "
        "(read, write, evaluate, mcp) and optional project restriction; it needs no CSRF "
        "header and is decided before any session cookie. Session-only routes answer 403 "
        "insufficient_scope; a missing, invalid, expired or revoked key 401."
    ),
    auto_error=False,
)


async def get_current_user(
    request: Request,
    session: SessionDep,
    token: Annotated[str | None, Security(session_cookie)],
    key: Annotated[HTTPAuthorizationCredentials | None, Security(api_key_bearer)],
) -> User:
    """The signed-in, active user.

    * ``Authorization: Bearer <key>``: the API-key source decides (401 for a missing,
      invalid, expired or revoked key, 429 past its limits); then a key on a route it
      may not reach -> 403 ``insufficient_scope`` (session-only routes, ``read``
      routes without the scope);
    * no credential, an unknown/expired session or a deactivated user -> 401
      ``unauthorized``;
    * a cookie-authenticated ``POST``/``PUT``/``PATCH``/``DELETE`` without the
      session's ``X-CSRF-Token`` -> 403 ``csrf_failed``;
    * refreshes the session's ``last_seen_at`` (at most once a minute), unless the
      route declares :func:`not_activity`.

    ``token`` and ``key`` declare the OpenAPI security schemes; the sources read the
    cookie and the header themselves.
    """
    touch = getattr(request.state, _KEEP_ALIVE, True) is not False
    principal = await authenticate(request, session, touch=touch)
    if principal is None:
        raise UnauthorizedProblem
    route = request.scope.get("route")
    operation = getattr(route, "operation_id", None)
    check_route_for_key(principal, operation)
    # Phase 8b: the operation decides what a guest researcher may reach (app.authz.guest).
    principal = dataclasses.replace(principal, operation=operation)
    request.state.principal = principal
    return principal.user


CurrentUserDep = Annotated[User, Depends(get_current_user)]
"""The signed-in user; 401 problem if there is none."""
