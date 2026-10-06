"""``POST /mcp``: the checks in front of the SDK (contract-phase5 section 3.5), in order:

1. **Method:** only ``POST``; anything else is 405 with ``Allow: POST`` (no ``GET`` SSE
   stream, no ``DELETE`` of sessions, never CORS). The app's body limit (413) applies
   before that.
2. **Origin:** an ``Origin`` header, when present, must be the origin of one of
   ``SOUNDINGS_BASE_URLS``, else 403 ``invalid_origin``: browsers can't be used to
   reach ``/mcp`` through DNS rebinding. MCP clients outside browsers send none.
   There is no ``Host`` check here (agents call the cluster Service by name).
3. **Key:** ``Authorization: Bearer <key>`` through the same API-key checks and
   throttles as REST (:mod:`app.auth.key_auth`): 401 with ``WWW-Authenticate`` for a
   missing or unusable key (a session cookie is never accepted here, so there is no
   CSRF exposure), 429 for a failing key from an address past the failure limit. The
   check runs in a short transaction of its own; no connection is held while the SDK
   reads the body.
4. **Rate:** the key's request budget, shared with REST (429 ``too_many_attempts``).
   Every request of a valid key counts, refused ones included, so a key without the
   ``mcp`` scope can't make unlimited requests here either.
5. **c15** (``mcp.connect``): a key without the ``mcp`` scope is 403
   ``insufficient_scope``, whatever its JSON-RPC method.
6. **Content-Type** must be ``application/json`` (415 ``unsupported_media_type``; the
   SDK alone would answer a plain-text 400).

Refusals at steps 4 and 5 are audited (``mcp.call`` without a tool) **at most once per
key and minute** each (:data:`DOOR_AUDIT_PERIOD`): enough for admins to see a refused
or runaway key, without a flood of requests filling the audit log.

Then the request is bound (:mod:`app.mcp.context`) and handed to the SDK, which checks
``Accept`` (406) and the JSON-RPC message (400; batches are refused). Every response
gets ``Cache-Control: no-store``. Each request is authenticated on its own (stateless),
and each tool call checks the key again in its own transaction
(:mod:`app.mcp.dispatcher`), so a revoked key fails on the very next call, even one
whose request was let in before the revoke.
"""

from __future__ import annotations

from typing import Any, Final
from urllib.parse import urlsplit

from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.routing import BaseRoute
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.auth.key_auth import (
    ApiKeyUnauthorizedProblem,
    TooManyKeyAttemptsProblem,
    authenticate_api_key,
    bearer_token,
    limit_key_request,
)
from app.auth.throttle import client_key, get_throttle
from app.authz import Rule, authorize
from app.domain.principal import Principal
from app.errors import ProblemError, problem_from_problem_error
from app.mcp.audit import record_door_refusal
from app.mcp.context import McpRequest, bound

__all__ = ["DOOR_AUDIT_PERIOD", "McpGuard", "allowed_origins", "normalise_origin"]

_DEFAULT_PORTS: Final = {"http": 80, "https": 443}
_INSUFFICIENT_SCOPE: Final = 'Bearer error="insufficient_scope", scope="mcp"'

DOOR_AUDIT_PERIOD: Final = 60.0
"""Seconds: at most one ``mcp.call`` entry per key and refusal code in this period for
requests refused before the SDK (c15's 403, the request budget's 429)."""
_DOOR_AUDIT: Final = ("mcp_door_audit", 1, DOOR_AUDIT_PERIOD)


def normalise_origin(value: str) -> str | None:
    """``scheme://host[:port]`` in lower case without a default port; ``None`` for
    anything that isn't an http(s) origin (``null``, paths, garbage)."""
    try:
        parts = urlsplit(value.strip())
        port = parts.port
    except ValueError:
        return None
    scheme, host = parts.scheme.lower(), (parts.hostname or "").lower()
    if scheme not in _DEFAULT_PORTS or not host or parts.path not in {"", "/"}:
        return None
    if ":" in host:
        host = f"[{host}]"
    if port is None or port == _DEFAULT_PORTS[scheme]:
        return f"{scheme}://{host}"
    return f"{scheme}://{host}:{port}"


def allowed_origins(base_urls: list[str]) -> frozenset[str]:
    """The origins of the configured base URLs (a base URL may have a path; its origin
    doesn't)."""
    found = set()
    for url in base_urls:
        parts = urlsplit(url)
        origin = normalise_origin(f"{parts.scheme}://{parts.netloc}")
        if origin is not None:
            found.add(origin)
    return frozenset(found)


class McpGuard:
    """The ASGI endpoint of ``/mcp`` (:func:`app.mcp.install_mcp`): the checks above,
    then ``inner`` (:class:`app.mcp.server.McpTransport`) with the request bound."""

    def __init__(self, inner: ASGIApp, *, base_urls: list[str]) -> None:
        self.inner = inner
        self.origins = allowed_origins(base_urls)
        self.route: BaseRoute | None = None
        """The route serving this guard: put in the scope, so access logs and metrics
        label requests ``/mcp`` (FastAPI does that only for its own routes)."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if self.route is not None:
            scope.setdefault("route", self.route)

        async def send_no_store(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message).setdefault("Cache-Control", "no-store")
            await send(message)

        request = Request(scope, receive)
        try:
            principal_request = await self._admit(request)
        except ProblemError as problem:
            await problem_from_problem_error(request, problem)(scope, receive, send_no_store)
            return
        with bound(principal_request):
            await self.inner(scope, receive, send_no_store)

    async def _admit(self, request: Request) -> McpRequest:
        app: Any = request.app
        if request.method != "POST":
            raise ProblemError(
                405, "method_not_allowed", detail="Use POST.", headers={"Allow": "POST"}
            )
        origin = request.headers.get("origin")
        if origin is not None and normalise_origin(origin) not in self.origins:
            raise ProblemError(
                403, "invalid_origin", detail="Requests from this origin aren't accepted."
            )
        token = bearer_token(request.headers.get("authorization"))
        if token is None:
            raise ApiKeyUnauthorizedProblem
        principal = await authenticate_api_key(app, token, client=client_key(request))
        try:
            limit_key_request(app, principal, write=False)
        except TooManyKeyAttemptsProblem:
            await _audit_door_refusal(app, principal, rule=None, code="too_many_attempts")
            raise
        connect = authorize(principal, Rule.MCP_CONNECT)
        if not connect.allowed:
            await _audit_door_refusal(
                app, principal, rule=Rule.MCP_CONNECT.value, code="insufficient_scope"
            )
            problem = connect.problem()
            problem.headers["WWW-Authenticate"] = _INSUFFICIENT_SCOPE
            raise problem
        media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if media_type != "application/json":
            raise ProblemError(
                415, "unsupported_media_type", detail="Send JSON-RPC as application/json."
            )
        return McpRequest(app=app, principal=principal)


async def _audit_door_refusal(
    app: Any, principal: Principal, *, rule: str | None, code: str
) -> None:
    """One entry per key and ``code`` per :data:`DOOR_AUDIT_PERIOD`; the rest only in
    the access log."""
    if get_throttle(app, _DOOR_AUDIT).first_notice(
        f"{principal.api_key_id}:{code}", DOOR_AUDIT_PERIOD
    ):
        await record_door_refusal(app, principal, rule=rule, code=code)
