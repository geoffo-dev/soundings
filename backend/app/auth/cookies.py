"""The session cookies (ADR 0005, contract section 1).

* ``soundings_session``: the session token. ``HttpOnly``, ``SameSite=Lax``, ``Path=/``,
  ``Secure`` (see :func:`cookie_secure`).
* ``soundings_csrf``: the session's CSRF token, readable by the SPA, which echoes it
  in ``X-CSRF-Token`` on unsafe methods (double submit, checked against the session
  row). Same attributes except ``HttpOnly``.
"""

from __future__ import annotations

from fastapi import Request, Response

from app.config import Settings

__all__ = [
    "CSRF_COOKIE",
    "CSRF_HEADER",
    "SESSION_COOKIE",
    "clear_session_cookies",
    "cookie_secure",
    "set_session_cookies",
]

SESSION_COOKIE = "soundings_session"
"""HttpOnly, Secure (over HTTPS), SameSite=Lax cookie holding the session token."""

CSRF_COOKIE = "soundings_csrf"
"""Readable (non-HttpOnly) cookie with the session's CSRF token (double submit)."""

CSRF_HEADER = "X-CSRF-Token"
"""Header that must echo ``CSRF_COOKIE`` on POST/PUT/PATCH/DELETE."""


def cookie_secure(request: Request, settings: Settings) -> bool:
    """``SOUNDINGS_COOKIE_SECURE`` if set; else always in production, and outside
    production for HTTPS requests (the scheme honours trusted proxies' headers)."""
    if settings.cookie_secure is not None:
        return settings.cookie_secure
    return settings.is_production or request.url.scheme == "https"


def set_session_cookies(
    response: Response, request: Request, settings: Settings, *, token: str, csrf_token: str
) -> None:
    secure = cookie_secure(request, settings)
    max_age = int(settings.session_max_age.total_seconds())
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=max_age,
        path="/",
        secure=secure,
        httponly=True,
        samesite="lax",
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        max_age=max_age,
        path="/",
        secure=secure,
        httponly=False,
        samesite="lax",
    )


def clear_session_cookies(response: Response, request: Request, settings: Settings) -> None:
    secure = cookie_secure(request, settings)
    response.delete_cookie(SESSION_COOKIE, path="/", secure=secure, httponly=True, samesite="lax")
    response.delete_cookie(CSRF_COOKIE, path="/", secure=secure, httponly=False, samesite="lax")
