"""API keys over HTTP: the bearer header, the throttles and the answers (contract-phase5
section 3.2). Used by :class:`app.auth.sources.ApiKeySource` (REST) and
:class:`app.mcp.guard.McpGuard` (``/mcp``), so both paths refuse and limit keys
identically.

* :func:`bearer_token`: the token of ``Authorization: Bearer <token>`` (scheme in any
  case), or ``None`` without such a header (other schemes, e.g. ``Basic`` from an
  ingress, are ignored).
* :func:`authenticate_api_key`: :func:`app.api_keys.verify.verify_api_key` (the check
  and the throttled ``last_used_at`` update in one short transaction of their own, so a
  request never holds two connections), then on a refusal 401
  (:class:`ApiKeyUnauthorizedProblem`, one body for every reason) counted per client
  address, or 429 once the address is past
  :data:`~app.schemas.api_keys.API_KEY_FAILURES_PER_MINUTE` failures in a minute (only
  failing keys: a valid key from that address still works). Given the request's
  session, the principal is then rebuilt in it (:func:`reload_api_key`), so the routes
  get an owner loaded in their own unit of work.
* :func:`refuse_reloaded_key`: the refusal for a key that passed the check but no longer
  holds when it is read again (an MCP tool's transaction).
* :func:`limit_key_request`: at most :data:`API_KEY_REQUESTS_PER_MINUTE` requests per
  key (REST and ``/mcp`` together) and, for writes, :data:`API_KEY_WRITES_PER_MINUTE`
  (429 ``too_many_attempts`` with ``Retry-After``).
* :func:`take_key_write`: one write from the key's write budget for an MCP tool call
  that isn't read-only; returns the seconds to wait when the budget is spent (the
  dispatcher answers the tool error ``too_many_attempts``).

All limits are in-process sliding windows (:mod:`app.auth.throttle`), per API process.
Refusals are logged (``api key refused``, ``reason``, the key id when known), never the
token; the first throttled refusal of an address in a minute at WARNING, the rest not
at all. Nothing here is audited (an unauthenticated flood must not fill the audit log).
"""

from __future__ import annotations

import logging
import math
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.api_keys.verify import KeyCheck, reload_api_key, verify_api_key
from app.auth.throttle import get_throttle
from app.domain.principal import Principal
from app.errors import ProblemError
from app.schemas.api_keys import (
    API_KEY_FAILURES_PER_MINUTE,
    API_KEY_REQUESTS_PER_MINUTE,
    API_KEY_WRITES_PER_MINUTE,
)

__all__ = [
    "KEY_FAILURE_THROTTLE",
    "KEY_REQUEST_THROTTLE",
    "KEY_WRITE_THROTTLE",
    "WWW_AUTHENTICATE",
    "ApiKeyUnauthorizedProblem",
    "TooManyKeyAttemptsProblem",
    "authenticate_api_key",
    "bearer_token",
    "limit_key_request",
    "refuse_reloaded_key",
    "take_key_write",
]

logger = logging.getLogger(__name__)

KEY_FAILURE_THROTTLE: Final = ("api_key_failure", API_KEY_FAILURES_PER_MINUTE, 60.0)
"""Failed key authentications per client address (IPv6: per /64) per minute."""
KEY_REQUEST_THROTTLE: Final = ("api_key_request", API_KEY_REQUESTS_PER_MINUTE, 60.0)
"""Requests per key per minute (REST and ``/mcp``)."""
KEY_WRITE_THROTTLE: Final = ("api_key_write", API_KEY_WRITES_PER_MINUTE, 60.0)
"""Writes per key per minute (REST unsafe methods and MCP write tools)."""

WWW_AUTHENTICATE: Final = 'Bearer realm="soundings"'

_UNAUTHORIZED_DETAIL: Final = (
    "The API key is missing, invalid, expired or revoked, or its owner needs to sign in "
    "to Soundings again."
)


class ApiKeyUnauthorizedProblem(ProblemError):
    """Every refused key: the same body and ``WWW-Authenticate``, whatever the reason."""

    def __init__(self) -> None:
        super().__init__(
            401,
            "unauthorized",
            detail=_UNAUTHORIZED_DETAIL,
            headers={"WWW-Authenticate": WWW_AUTHENTICATE},
        )


class TooManyKeyAttemptsProblem(ProblemError):
    """429 ``too_many_attempts`` with ``Retry-After`` (whole seconds, at least 1)."""

    def __init__(self, retry_after: float, detail: str) -> None:
        super().__init__(
            429,
            "too_many_attempts",
            detail=detail,
            headers={"Retry-After": str(max(1, math.ceil(retry_after)))},
        )


def bearer_token(authorization: str | None) -> str | None:
    """The token of a ``Bearer`` authorization (scheme in any case; may be empty, which
    is a failure, never a fall-through to the session), or ``None`` without one."""
    if not authorization:
        return None
    scheme, _, token = authorization.strip().partition(" ")
    if scheme.lower() != "bearer":
        return None
    return token.strip()


def _refuse(app: Any, check: KeyCheck, client: str) -> ProblemError:
    throttle = get_throttle(app, KEY_FAILURE_THROTTLE)
    retry_after = throttle.retry_after(client)
    fields: dict[str, object] = {"reason": check.refusal}
    if check.key_id is not None:
        fields["api_key_id"] = str(check.key_id)
    if retry_after is not None:
        if throttle.first_refusal(client):
            logger.warning("api key refused", extra={**fields, "throttled": True})
        return TooManyKeyAttemptsProblem(
            retry_after, "Too many failed API key attempts. Try again in a minute."
        )
    throttle.hit(client)
    logger.info("api key refused", extra=fields)
    return ApiKeyUnauthorizedProblem()


async def authenticate_api_key(
    app: Any, token: str, *, client: str, db: AsyncSession | None = None
) -> Principal:
    """The key's principal, or raise 401 (:class:`ApiKeyUnauthorizedProblem`) / 429 (a
    failing key from an address over the failure limit). ``client`` is
    :func:`app.auth.throttle.client_key` of the request. ``app`` gives the settings,
    the session maker and the throttles.

    Without ``db`` the principal's owner comes from the check's own (closed) session:
    enough to decide ``mcp.connect`` and the rates; whatever reads or writes data must
    rebuild it in its own transaction (:func:`reload_api_key`, as the MCP dispatcher
    does). With ``db`` (the request's session, which must hold no connection yet) it is
    rebuilt there at once."""
    settings = app.state.settings
    check = await verify_api_key(app.state.sessionmaker, token, settings=settings)
    if check.principal is None or check.key_id is None:
        raise _refuse(app, check, client)
    if db is None:
        return check.principal
    live = await reload_api_key(db, check.key_id, settings=settings)
    if live.principal is None:
        raise refuse_reloaded_key(live)
    return live.principal


def refuse_reloaded_key(check: KeyCheck) -> ProblemError:
    """The 401 for a key refused when read again after the request was let in (logged
    like every refusal; not counted per address: the secret was right)."""
    fields: dict[str, object] = {"reason": check.refusal, "stage": "reload"}
    if check.key_id is not None:
        fields["api_key_id"] = str(check.key_id)
    logger.info("api key refused", extra=fields)
    return ApiKeyUnauthorizedProblem()


def _key_id(principal: Principal) -> str:
    if principal.api_key_id is None:
        raise ValueError("not an API-key principal")
    return str(principal.api_key_id)


def limit_key_request(app: Any, principal: Principal, *, write: bool) -> None:
    """Count one request of the key (and one write when ``write``); 429 when the key is
    over :data:`API_KEY_REQUESTS_PER_MINUTE` or, for a write,
    :data:`API_KEY_WRITES_PER_MINUTE`. A refused request isn't counted."""
    key_id = _key_id(principal)
    requests = get_throttle(app, KEY_REQUEST_THROTTLE)
    retry_after = requests.retry_after(key_id)
    if retry_after is not None:
        if requests.first_refusal(key_id):
            logger.warning("api key rate limited", extra={"api_key_id": key_id})
        raise TooManyKeyAttemptsProblem(
            retry_after, "This API key made too many requests. Try again in a minute."
        )
    if write:
        writes = get_throttle(app, KEY_WRITE_THROTTLE)
        write_retry = writes.retry_after(key_id)
        if write_retry is not None:
            if writes.first_refusal(key_id):
                logger.warning("api key write limited", extra={"api_key_id": key_id})
            raise TooManyKeyAttemptsProblem(
                write_retry, "This API key made too many changes. Try again in a minute."
            )
        writes.hit(key_id)
    requests.hit(key_id)


def take_key_write(app: Any, principal: Principal) -> float | None:
    """Spend one write of the key's budget (an MCP tool that isn't read-only): ``None``
    when allowed (counted), else the seconds until one is free (not counted)."""
    key_id = _key_id(principal)
    writes = get_throttle(app, KEY_WRITE_THROTTLE)
    retry_after = writes.retry_after(key_id)
    if retry_after is not None:
        if writes.first_refusal(key_id):
            logger.warning("api key write limited", extra={"api_key_id": key_id})
        return retry_after
    writes.hit(key_id)
    return None
