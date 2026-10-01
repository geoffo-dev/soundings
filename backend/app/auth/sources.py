"""Principal sources: how a request proves who it is.

:func:`authenticate` asks each source in :data:`PRINCIPAL_SOURCES` in turn. A source
returns ``None`` when its credential is absent, a :class:`Principal` when it is valid,
and raises (401, or 403 ``csrf_failed``) when it is present but unusable, so a bad
credential never falls through to another source.

* :class:`SessionCookieSource`: the session cookie. Every sign-in method (SSO,
  break-glass, dev login) creates the same server-side session; the principal
  records which (``auth_method``), and a session whose method is no longer available
  is refused (:func:`app.services.sessions.resolve_session`).
* Phase 5: an API-key source (``Authorization: Bearer``) goes *first*; it builds a
  principal with ``auth="api_key"``, the key's scopes and projects, and no CSRF check.
"""

from __future__ import annotations

from typing import Final, Protocol

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.cookies import CSRF_HEADER, SESSION_COOKIE, read_cookie
from app.auth.tokens import tokens_match
from app.config import Settings
from app.domain.principal import Principal
from app.errors import ProblemError
from app.models.enums import AuthMethod
from app.services import sessions

__all__ = [
    "PRINCIPAL_SOURCES",
    "UNSAFE_METHODS",
    "CsrfFailedProblem",
    "PrincipalSource",
    "SessionCookieSource",
    "UnauthorizedProblem",
    "authenticate",
]

UNSAFE_METHODS: Final = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class UnauthorizedProblem(ProblemError):
    def __init__(self) -> None:
        super().__init__(401, "unauthorized", detail="Sign in to continue.")


class CsrfFailedProblem(ProblemError):
    def __init__(self) -> None:
        super().__init__(
            403,
            "csrf_failed",
            detail="The request is missing the X-CSRF-Token header. Reload the page and retry.",
        )


class PrincipalSource(Protocol):
    async def authenticate(
        self, request: Request, db: AsyncSession, *, touch: bool = True
    ) -> Principal | None: ...


class SessionCookieSource:
    """The session cookie (``soundings_session``, or ``__Host-soundings_session`` when
    cookies are Secure: only the variant for this request is read), checked against
    ``user_sessions``.

    Unsafe methods must echo the session's CSRF token in ``X-CSRF-Token``
    (constant-time compare against the server-side value, not just the cookie).
    ``touch=False`` resolves the session without keeping it alive (the bell's poll).
    """

    async def authenticate(
        self, request: Request, db: AsyncSession, *, touch: bool = True
    ) -> Principal | None:
        settings: Settings = request.app.state.settings
        token = read_cookie(request, settings, SESSION_COOKIE)
        if not token:
            return None
        found = await sessions.resolve_session(db, token, settings=settings, touch=touch)
        if found is None:
            raise UnauthorizedProblem
        row, user = found
        if request.method in UNSAFE_METHODS and not tokens_match(
            request.headers.get(CSRF_HEADER), row.csrf_token
        ):
            raise CsrfFailedProblem
        return Principal(
            user=user, auth="session", session_id=row.id, auth_method=AuthMethod(row.auth_method)
        )


PRINCIPAL_SOURCES: Final[tuple[PrincipalSource, ...]] = (SessionCookieSource(),)


async def authenticate(
    request: Request, db: AsyncSession, *, touch: bool = True
) -> Principal | None:
    """The request's principal, or ``None`` when it carries no credential at all.
    ``touch=False``: don't keep the session alive (requests that aren't activity)."""
    for source in PRINCIPAL_SOURCES:
        principal = await source.authenticate(request, db, touch=touch)
        if principal is not None:
            return principal
    return None
