"""Request dependencies shared by the API routers: the signed-in user.

:func:`get_current_user` authenticates the request through the principal sources in
:mod:`app.auth.sources` (the session cookie in Phase 1; API keys in Phase 5), stores
the :class:`~app.domain.principal.Principal` on ``request.state`` for
:func:`app.api.v1.principal.get_principal`, and returns its user. Routes take
``PrincipalDep``, never this directly.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request, Security
from fastapi.security import APIKeyCookie

from app.auth.cookies import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE
from app.auth.sources import UnauthorizedProblem, authenticate
from app.db import SessionDep
from app.models.user import User

__all__ = [
    "CSRF_COOKIE",
    "CSRF_HEADER",
    "SESSION_COOKIE",
    "CurrentUserDep",
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


async def get_current_user(
    request: Request,
    session: SessionDep,
    token: Annotated[str | None, Security(session_cookie)],
) -> User:
    """The signed-in, active user.

    * no credential, an unknown/expired session or a deactivated user -> 401
      ``unauthorized``;
    * a cookie-authenticated ``POST``/``PUT``/``PATCH``/``DELETE`` without the
      session's ``X-CSRF-Token`` -> 403 ``csrf_failed``;
    * refreshes ``last_seen_at`` (at most once a minute), unless the route declares
      :func:`not_activity`.

    ``token`` declares the OpenAPI security scheme; the session source reads the
    cookie itself, next to the other principal sources.
    """
    touch = getattr(request.state, _KEEP_ALIVE, True) is not False
    principal = await authenticate(request, session, touch=touch)
    if principal is None:
        raise UnauthorizedProblem
    request.state.principal = principal
    return principal.user


CurrentUserDep = Annotated[User, Depends(get_current_user)]
"""The signed-in user; 401 problem if there is none."""
