"""Principal sources: how a request proves who it is.

:func:`authenticate` asks each source in :data:`PRINCIPAL_SOURCES` in turn. A source
returns ``None`` when its credential is absent, a :class:`Principal` when it is valid,
and raises (401, or 403 ``csrf_failed``) when it is present but unusable, so a bad
credential never falls through to another source.

* :class:`ApiKeySource` (first): ``Authorization: Bearer <key>`` (contract-phase5
  section 3.2). A bearer token is always ours: a bad one is 401 (or 429), never a
  fall-through to the cookie, and a request with a key and a cookie is decided by the
  key. The principal is the key's owner, live, with the key's scopes and projects
  (``auth="api_key"``); no CSRF check (browsers can't attach the header cross-site
  without a preflight the API never grants). Each key is rate limited.
* :class:`SessionCookieSource`: the session cookie. Every sign-in method (SSO,
  break-glass, dev login) creates the same server-side session; the principal
  records which (``auth_method``), and a session whose method is no longer available
  is refused (:func:`app.services.sessions.resolve_session`). Writes need the CSRF
  token and are limited per person (:func:`limit_session_write`, 429 ``rate_limited``).
"""

from __future__ import annotations

import logging
import math
from typing import Any, Final, Protocol
from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.cookies import CSRF_HEADER, SESSION_COOKIE, read_cookie
from app.auth.key_auth import authenticate_api_key, bearer_token, limit_key_request
from app.auth.throttle import client_key, get_throttle
from app.auth.tokens import tokens_match
from app.config import Settings
from app.domain.principal import Principal
from app.errors import ProblemError
from app.models.base import utcnow
from app.models.enums import AuthMethod
from app.services import sessions

__all__ = [
    "PRINCIPAL_SOURCES",
    "UNSAFE_METHODS",
    "ApiKeySource",
    "CsrfFailedProblem",
    "PrincipalSource",
    "SessionCookieSource",
    "SessionWritesLimitedProblem",
    "UnauthorizedProblem",
    "authenticate",
    "limit_session_write",
]

logger = logging.getLogger(__name__)

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


class ApiKeySource:
    """``Authorization: Bearer <key>`` (scheme in any case). Other schemes and no header
    answer ``None`` (the session source runs). Unsafe methods count towards the key's
    write cap as well as its request rate."""

    async def authenticate(
        self, request: Request, db: AsyncSession, *, touch: bool = True
    ) -> Principal | None:
        token = bearer_token(request.headers.get("authorization"))
        if token is None:
            return None
        principal = await authenticate_api_key(
            request.app, token, client=client_key(request), db=db
        )
        limit_key_request(request.app, principal, write=request.method in UNSAFE_METHODS)
        return principal


class SessionWritesLimitedProblem(ProblemError):
    """429 ``rate_limited`` with ``Retry-After`` (whole seconds, at least 1)."""

    def __init__(self, retry_after: float) -> None:
        super().__init__(
            429,
            "rate_limited",
            detail="You're making changes very quickly. Wait a moment and try again.",
            headers={"Retry-After": str(max(1, math.ceil(retry_after)))},
        )


def limit_session_write(app: Any, settings: Settings, user_id: UUID) -> None:
    """Count one write of a signed-in person (security review P7 L4): at most
    ``SOUNDINGS_SESSION_WRITES_PER_MINUTE`` (120) a minute per API process, across their
    sessions, like the 30 a minute an API key gets. A refused write isn't counted; the
    first refusal of a minute is logged (user id only)."""
    throttle = get_throttle(app, ("session_write", settings.session_writes_per_minute, 60.0))
    key = str(user_id)
    retry_after = throttle.retry_after(key)
    if retry_after is not None:
        if throttle.first_refusal(key):
            logger.warning("session writes limited", extra={"user_id": key})
        raise SessionWritesLimitedProblem(retry_after)
    throttle.hit(key)


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
        now = utcnow()
        found = await sessions.resolve_session(db, token, settings=settings, now=now)
        if found is None:
            raise UnauthorizedProblem
        row, user = found
        if touch and sessions.needs_touch(row, now):
            # After the response, in a transaction of its own (performance review B8).
            request.state.session_touch = (row.id, user.id)
        if request.method in UNSAFE_METHODS:
            if not tokens_match(request.headers.get(CSRF_HEADER), row.csrf_token):
                raise CsrfFailedProblem
            limit_session_write(request.app, settings, user.id)
        return Principal(
            user=user, auth="session", session_id=row.id, auth_method=AuthMethod(row.auth_method)
        )


PRINCIPAL_SOURCES: Final[tuple[PrincipalSource, ...]] = (ApiKeySource(), SessionCookieSource())


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
