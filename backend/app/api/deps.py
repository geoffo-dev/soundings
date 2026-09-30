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
    "session_cookie",
]

session_cookie = APIKeyCookie(
    name=SESSION_COOKIE,
    scheme_name="session",
    description=(
        "Server-side session cookie set by sign-in (Phase 1: POST /api/v1/auth/dev/login). "
        f"Unsafe methods must also send the {CSRF_HEADER} header equal to the "
        f"{CSRF_COOKIE} cookie."
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
    * refreshes ``last_seen_at`` (at most once a minute).

    ``token`` declares the OpenAPI security scheme; the session source reads the
    cookie itself, next to the other principal sources.
    """
    principal = await authenticate(request, session)
    if principal is None:
        raise UnauthorizedProblem
    request.state.principal = principal
    return principal.user


CurrentUserDep = Annotated[User, Depends(get_current_user)]
"""The signed-in user; 401 problem if there is none."""
