"""The MCP server at ``/mcp`` (SPEC section 8; contract-phase5 sections 3.5, 3.6 and 4;
ADR 0013): stateless streamable HTTP with JSON responses, authenticated by API keys,
ten tools (SPEC section 8's nine and Phase 6's add_research_note) that call the same
services and policy as the REST API, every call audited.

* :mod:`.guard`: ``POST /mcp`` (Origin, the key, the key's rate, c15), then the SDK.
* :mod:`.server`: the SDK's low-level ``Server`` (the catalogue and one dispatcher) and
  its stateless transport, whose ``run()`` lives in the app's lifespan.
* :mod:`.dispatcher`: every ``tools/call``: validate, write cap, check the key again,
  run, map errors, audit; results without invisible text (:mod:`.text`).
* :mod:`.tools`: the ten tools over the REST services (c22 for agents: app.ai.scope).
* :mod:`.audit`: ``mcp.call`` entries and their 90-day cleanup.
* :mod:`.context`: the authenticated request the tools read.

:func:`install_mcp` mounts it on an app; tests use the SDK client over
``httpx2.ASGITransport`` inside the app's lifespan (in-memory clients skip auth).
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from starlette.routing import Route

from app.config import Settings
from app.mcp.guard import McpGuard
from app.mcp.server import McpTransport
from app.schemas.mcp import MCP_PATH

__all__ = ["MCP_PATH", "McpTransport", "install_mcp"]


def install_mcp(app: FastAPI, settings: Settings, transport: McpTransport) -> None:
    """Add ``/mcp`` (exact path, outside OpenAPI) in front of ``transport``, whose
    ``run()`` the app's lifespan enters. Every method reaches the guard, which answers
    all but ``POST`` with 405 problem+json (``Allow: POST``, ``no-store``)."""
    # The SDK logs every stateless request at INFO ("Terminating session") and may log
    # raw messages at DEBUG; tool arguments must never reach the logs (contract-phase5
    # section 1, "Privacy"), so it only gets to say WARNING and above.
    sdk_logger = logging.getLogger("mcp")
    sdk_logger.setLevel(max(sdk_logger.getEffectiveLevel(), logging.WARNING))
    guard = McpGuard(transport, base_urls=settings.base_urls)
    guard.route = Route(MCP_PATH, endpoint=guard, include_in_schema=False)
    app.router.routes.append(guard.route)
