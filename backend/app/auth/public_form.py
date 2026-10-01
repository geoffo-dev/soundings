"""Anti-abuse for the public routes (``/api/v1/public/...``, contract-phase4 sections 1,
3.5 and 3.7): JSON-only writes, per-client-IP throttles and the honeypot.

* :class:`JsonOnlyRoute`: every ``POST``/``PUT``/``PATCH``/``DELETE`` must be
  ``Content-Type: application/json`` (parameters allowed), else **415
  ``unsupported_media_type``**, checked before the body is read or parsed. FastAPI would
  otherwise read a body sent without a ``Content-Type`` as JSON, so another site could
  post the form or confirm an address through its visitors' browsers with a
  ``no-cors`` request (spreading the per-IP limit over them); ``application/json``
  makes such a request need a CORS preflight, which the API never grants.
* :func:`check_throttle` / :func:`hit`: in-process sliding windows keyed by the client
  address that :class:`app.middleware.ProxyHeadersMiddleware` resolved (trusted
  proxies and hops only; IPv6 per /64; :func:`app.auth.throttle.client_key`), never a
  header the client chose. Refusals are 429 ``too_many_attempts`` with
  ``Retry-After`` and are logged without the address.
* :func:`honeypot_filled`: the form's hidden ``website`` field. Checked last (after
  every other check), so a bot that fills it gets exactly a real submission's answers.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable, Coroutine, Mapping
from email.message import Message
from typing import Any, Final

from fastapi.routing import APIRoute
from starlette.requests import Request
from starlette.responses import Response

from app.auth.throttle import Throttle, client_key, get_throttle
from app.errors import ProblemError

__all__ = [
    "JSON_ONLY_METHODS",
    "JsonOnlyRoute",
    "check_throttle",
    "honeypot_filled",
    "is_json",
    "refuse",
    "throttle_for",
]

logger = logging.getLogger(__name__)

JSON_ONLY_METHODS: Final = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_WARNING_PERIOD: Final = 60 * 60.0


def is_json(content_type: str | None) -> bool:
    """``application/json``, with any parameters (``; charset=utf-8``)."""
    if not content_type:
        return False
    message = Message()
    message["content-type"] = content_type
    return message.get_content_type() == "application/json"


class JsonOnlyRoute(APIRoute):
    """A route that answers 415 to a write without ``Content-Type: application/json``,
    before FastAPI reads or parses the body (so before any 422)."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def json_only(request: Request) -> Response:
            if request.method in JSON_ONLY_METHODS and not is_json(
                request.headers.get("content-type")
            ):
                raise ProblemError(
                    415,
                    "unsupported_media_type",
                    detail="Send the request as application/json.",
                )
            return await handler(request)

        return json_only


def throttle_for(request: Request, spec: tuple[str, int, float]) -> Throttle:
    return get_throttle(request.app, spec)


def refuse(retry_after: float, detail: str) -> ProblemError:
    """429 ``too_many_attempts`` with ``Retry-After`` (whole seconds, at least 1)."""
    return ProblemError(
        429,
        "too_many_attempts",
        detail=detail,
        headers={"Retry-After": str(max(1, math.ceil(retry_after)))},
    )


def check_throttle(
    request: Request,
    spec: tuple[str, int, float],
    *,
    detail: str,
    event: str,
    count: bool = True,
    log_fields: Mapping[str, object] | None = None,
) -> None:
    """Refuse (429) when the client is at the limit; otherwise count this request
    (``count``). Refusals are logged as ``event`` with ``reason=rate_limited`` and
    ``log_fields`` (ids only, never the address): the first per client and hour at
    WARNING (a shared NAT or a wrong ``trustedProxyHops`` shows up), the rest at INFO."""
    throttle = throttle_for(request, spec)
    key = client_key(request)
    retry_after = throttle.retry_after(key)
    if retry_after is not None:
        level = logging.WARNING if throttle.first_notice(key, _WARNING_PERIOD) else logging.INFO
        logger.log(level, event, extra={"reason": "rate_limited", **(log_fields or {})})
        raise refuse(retry_after, detail)
    if count:
        throttle.hit(key)


def honeypot_filled(website: str) -> bool:
    """The hidden field people never see or fill (any value, any length)."""
    return website != ""
