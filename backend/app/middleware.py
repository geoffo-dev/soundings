"""Pure-ASGI middleware: request context (id, access log, metrics, 500s) and security headers."""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Sequence
from time import perf_counter
from typing import Any

from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.errors import internal_error_response
from app.observability import observe_request, request_id_var

logger = logging.getLogger("soundings.request")

REQUEST_ID_HEADER = "X-Request-ID"
_VALID_REQUEST_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}")
_QUIET_ROUTES = frozenset({"/healthz", "/readyz", "/metrics"})


def route_template(scope: Scope) -> str:
    """The matched route's path template (e.g. ``/api/v1/ideas/{idea_id}``).

    Used for metric labels and access logs so raw paths (ids, tokens) never leak
    and label cardinality stays bounded. FastAPI (0.142) keeps the *full* template of
    a route from an included router in its effective route context, while
    ``scope["route"]`` only has the path relative to that router;
    tests/test_observability.py pins this behaviour across upgrades.
    """
    fastapi_scope = scope.get("fastapi")
    if isinstance(fastapi_scope, dict):
        context = fastapi_scope.get("effective_route_context")
        template = getattr(context, "path_format", None)
        if isinstance(template, str) and template:
            return template
    template = getattr(scope.get("route"), "path_format", None)
    if isinstance(template, str) and template:
        return template
    return "unmatched"


def _incoming_request_id(scope: Scope) -> str | None:
    for name, value in scope.get("headers", ()):
        if name == b"x-request-id":
            candidate = value.decode("latin-1")
            return candidate if _VALID_REQUEST_ID.fullmatch(candidate) else None
    return None


class RequestContextMiddleware:
    """Request bookkeeping, just inside SecurityHeadersMiddleware.

    * assigns a request id (reuses a well-formed incoming ``X-Request-ID``),
      exposes it to logs and echoes it on the response;
    * turns unhandled exceptions into a generic 500 problem (details go to the log);
    * records Prometheus metrics and one PII-free access-log line per request.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _incoming_request_id(scope) or uuid.uuid4().hex
        token = request_id_var.set(request_id)
        started = perf_counter()
        status = 500
        response_started = False

        async def send_with_request_id(message: Message) -> None:
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception:
            logger.exception("unhandled error", extra={"route": route_template(scope)})
            if response_started:
                raise
            response = internal_error_response(Request(scope))
            await response(scope, receive, send_with_request_id)
        finally:
            duration = perf_counter() - started
            route = route_template(scope)
            observe_request(scope["method"], route, status, duration)
            fields: dict[str, Any] = {
                "method": scope["method"],
                "route": route,
                "status": status,
                "duration_ms": round(duration * 1000, 2),
            }
            level = logging.DEBUG if route in _QUIET_ROUTES else logging.INFO
            logger.log(level, "request", extra=fields)
            request_id_var.reset(token)


def content_security_policy(script_hashes: Sequence[str] = ()) -> str:
    """The CSP for everything we serve (SPA, Swagger UI, API responses).

    * ``script-src 'self'`` plus the sha256 hashes of index.html's inline scripts
      (the theme bootstrap), computed at startup, so no ``'unsafe-inline'`` scripts.
    * ``style-src 'unsafe-inline'``: Radix/react-remove-scroll inject ``<style>``
      elements at runtime; inline styles are far lower risk than inline scripts.
    * ``form-action`` is deliberately unset: Chromium applies it to the redirect
      after a form POST, which would block an OIDC sign-in/out redirect to the IdP.
    """
    script_src = " ".join(["'self'", *(f"'{digest}'" for digest in script_hashes)])
    return "; ".join(
        [
            "default-src 'self'",
            f"script-src {script_src}",
            "style-src 'self' 'unsafe-inline'",
            "img-src 'self' data: blob:",
            "font-src 'self'",
            "connect-src 'self'",
            "object-src 'none'",
            "base-uri 'self'",
            "frame-ancestors 'none'",
        ]
    )


class SecurityHeadersMiddleware:
    """Adds CSP and other security headers to every HTTP response.

    Headers already set by an endpoint win. API responses default to
    ``Cache-Control: no-store`` because they may contain private data.
    """

    def __init__(self, app: ASGIApp, *, content_security_policy: str) -> None:
        self.app = app
        self.headers: dict[str, str] = {
            "Content-Security-Policy": content_security_policy,
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "strict-origin-when-cross-origin",
            "X-Frame-Options": "DENY",
            "Cross-Origin-Opener-Policy": "same-origin",
            "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
        }

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        is_https = scope.get("scheme") == "https"
        is_api = scope["path"].startswith("/api/")

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in self.headers.items():
                    headers.setdefault(name, value)
                if is_https:
                    headers.setdefault("Strict-Transport-Security", "max-age=31536000")
                if is_api:
                    headers.setdefault("Cache-Control", "no-store")
            await send(message)

        await self.app(scope, receive, send_with_headers)
