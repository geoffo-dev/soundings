"""Request dependencies shared by the API routers: the signed-in user.

Contract glue written with the Phase 1 API contract; the backend agent implements
:func:`get_current_user` (the signature and the OpenAPI security scheme stay).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request, Security
from fastapi.security import APIKeyCookie

from app.db import SessionDep
from app.errors import NotImplementedProblem
from app.models.user import User

__all__ = [
    "CSRF_COOKIE",
    "CSRF_HEADER",
    "SESSION_COOKIE",
    "CurrentUserDep",
    "get_current_user",
    "session_cookie",
]

SESSION_COOKIE = "soundings_session"
"""HttpOnly, Secure (over HTTPS), SameSite=Lax cookie holding the session token."""

CSRF_COOKIE = "soundings_csrf"
"""Readable (non-HttpOnly) cookie with the session's CSRF token (double submit)."""

CSRF_HEADER = "X-CSRF-Token"
"""Header that must echo ``CSRF_COOKIE`` on POST/PUT/PATCH/DELETE."""

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

    To implement (Phase 1 backend):

    * look up ``user_sessions`` by SHA-256 of ``token``; missing, unknown or expired
      -> 401 ``unauthorized``; deactivated user -> 401 ``unauthorized``;
    * on POST/PUT/PATCH/DELETE require ``X-CSRF-Token`` == the session's
      ``csrf_token`` (constant-time compare) -> 403 ``csrf_failed``;
    * refresh ``last_seen_at`` (at most once a minute) and return the user.
    """
    raise NotImplementedProblem("Sessions are not implemented yet.")


CurrentUserDep = Annotated[User, Depends(get_current_user)]
"""The signed-in user; 401 problem if there is none."""
