"""The sign-in cookies (ADR 0005, contract-phase2 section 1).

* ``soundings_session``: the session token. ``HttpOnly``, ``SameSite=Lax``, ``Path=/``.
* ``soundings_csrf``: the session's CSRF token, readable by the SPA, which echoes it
  in ``X-CSRF-Token`` on unsafe methods (double submit, checked against the session
  row). Same attributes except ``HttpOnly``.
* ``soundings_oidc``: during an SSO sign-in only, the ``state`` that binds the
  login attempt to this browser. ``HttpOnly``, ``SameSite=Lax`` (sent on the IdP's
  top-level redirect back), ``Max-Age=600``.

**When cookies are Secure** (production, any HTTPS request: :func:`cookie_secure`)
they are named ``__Host-soundings_session``, ``__Host-soundings_csrf`` and
``__Host-soundings_oidc``: browsers accept a ``__Host-`` cookie only with ``Secure``,
``Path=/`` and no ``Domain``, so a sibling subdomain can't plant one (cookie tossing:
session fixation, login CSRF). The server reads only the variant matching
:func:`cookie_secure` for the request, never the other one.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Final

from fastapi import Request, Response

from app.config import Settings

__all__ = [
    "CSRF_COOKIE",
    "CSRF_HEADER",
    "OIDC_COOKIE",
    "OIDC_COOKIE_MAX_AGE",
    "SECURE_PREFIX",
    "SESSION_COOKIE",
    "clear_oidc_cookie",
    "clear_session_cookies",
    "cookie_name",
    "cookie_secure",
    "read_cookie",
    "set_oidc_cookie",
    "set_session_cookies",
]

SESSION_COOKIE: Final = "soundings_session"
"""HttpOnly, SameSite=Lax cookie holding the session token (plain-http name)."""

CSRF_COOKIE: Final = "soundings_csrf"
"""Readable (non-HttpOnly) cookie with the session's CSRF token (plain-http name)."""

OIDC_COOKIE: Final = "soundings_oidc"
"""HttpOnly cookie holding an SSO sign-in's ``state`` (plain-http name)."""

SECURE_PREFIX: Final = "__Host-"
"""Prefix of every cookie name when cookies are Secure."""

CSRF_HEADER: Final = "X-CSRF-Token"
"""Header that must echo the CSRF cookie on POST/PUT/PATCH/DELETE."""

OIDC_COOKIE_MAX_AGE: Final = timedelta(minutes=10)
"""= the login attempt's lifetime."""


def cookie_secure(request: Request, settings: Settings) -> bool:
    """``SOUNDINGS_COOKIE_SECURE`` if set; else always in production, and outside
    production for HTTPS requests (the scheme honours trusted proxies' headers)."""
    if settings.cookie_secure is not None:
        return settings.cookie_secure
    return settings.is_production or request.url.scheme == "https"


def cookie_name(name: str, *, secure: bool) -> str:
    """``__Host-<name>`` for Secure cookies, else ``<name>``."""
    return SECURE_PREFIX + name if secure else name


def read_cookie(request: Request, settings: Settings, name: str) -> str | None:
    """The cookie's value under the one name this request may use (see module doc)."""
    value = request.cookies.get(cookie_name(name, secure=cookie_secure(request, settings)))
    return value or None


def _set(
    response: Response,
    request: Request,
    settings: Settings,
    name: str,
    value: str,
    *,
    max_age: timedelta,
    httponly: bool,
) -> None:
    secure = cookie_secure(request, settings)
    response.set_cookie(
        cookie_name(name, secure=secure),
        value,
        max_age=int(max_age.total_seconds()),
        path="/",
        secure=secure,
        httponly=httponly,
        samesite="lax",
    )


def _clear(
    response: Response, request: Request, settings: Settings, name: str, *, httponly: bool
) -> None:
    secure = cookie_secure(request, settings)
    response.delete_cookie(
        cookie_name(name, secure=secure),
        path="/",
        secure=secure,
        httponly=httponly,
        samesite="lax",
    )


def set_session_cookies(
    response: Response,
    request: Request,
    settings: Settings,
    *,
    token: str,
    csrf_token: str,
    max_age: timedelta | None = None,
) -> None:
    """Set both session cookies; ``max_age`` defaults to ``session_max_age``."""
    lifetime = max_age or settings.session_max_age
    _set(response, request, settings, SESSION_COOKIE, token, max_age=lifetime, httponly=True)
    _set(response, request, settings, CSRF_COOKIE, csrf_token, max_age=lifetime, httponly=False)


def clear_session_cookies(response: Response, request: Request, settings: Settings) -> None:
    _clear(response, request, settings, SESSION_COOKIE, httponly=True)
    _clear(response, request, settings, CSRF_COOKIE, httponly=False)


def set_oidc_cookie(response: Response, request: Request, settings: Settings, state: str) -> None:
    _set(
        response, request, settings, OIDC_COOKIE, state, max_age=OIDC_COOKIE_MAX_AGE, httponly=True
    )


def clear_oidc_cookie(response: Response, request: Request, settings: Settings) -> None:
    _clear(response, request, settings, OIDC_COOKIE, httponly=True)
