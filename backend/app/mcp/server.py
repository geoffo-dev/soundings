"""The MCP server: the SDK's low-level ``Server`` with the catalogue and the dispatcher,
served over stateless streamable HTTP with JSON responses (contract-phase5 sections 3.5
and 4.1).

* ``tools/list`` is :data:`app.schemas.mcp.MCP_TOOLS` as MCP ``Tool`` objects:
  ``inputSchema`` is the ``*Input`` model's JSON schema, ``outputSchema`` the
  ``*Output`` model's serialization schema, plus title, description and annotations, so
  the published schemas are the models by construction.
* ``tools/call`` goes to :func:`app.mcp.dispatcher.call_tool` with the request bound by
  the guard (:mod:`app.mcp.context`). A call the SDK refuses before it reaches the
  dispatcher (malformed ``params``) is audited by :class:`AuditRefusedCalls`, so every
  ``tools/call`` leaves exactly one ``mcp.call`` entry.
* :class:`McpTransport` is the SDK's ``StreamableHTTPSessionManager`` configured as
  ``Server.streamable_http_app(stateless_http=True, json_response=True,
  max_request_body_size=1 MiB)`` would, with the SDK's own Host/Origin check off (the
  guard checks ``Origin``; ``/mcp`` is exempt from the app's Host check). It is called
  directly, without the SDK's Starlette wrapper, so errors raised while reading the
  body reach the app's problem+json handlers. Its ``run()`` belongs in the app's
  lifespan (a mounted app's lifespan never runs; research R1 section 1).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from functools import cache
from typing import Any

import mcp_types as types
from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.types import Receive, Scope, Send

from app import __version__
from app.mcp.audit import record_call_separately
from app.mcp.context import current_request
from app.mcp.dispatcher import call_tool
from app.schemas.mcp import (
    MCP_INSTRUCTIONS,
    MCP_MAX_REQUEST_BYTES,
    MCP_SERVER_NAME,
    MCP_SERVER_TITLE,
    MCP_TOOLS,
    tool_by_name,
)

__all__ = ["AuditRefusedCalls", "McpTransport", "build_server", "tool_listing"]

logger = logging.getLogger(__name__)

_DISPATCHED: ContextVar[list[bool] | None] = ContextVar("soundings_mcp_dispatched", default=None)


@cache
def tool_listing() -> tuple[types.Tool, ...]:
    """The catalogue as MCP tools (built once: the models don't change at run time)."""
    return tuple(
        types.Tool(
            name=tool.name,
            title=tool.title,
            description=tool.description,
            input_schema=tool.input.model_json_schema(),
            output_schema=tool.output.model_json_schema(mode="serialization"),
            annotations=types.ToolAnnotations(
                title=tool.title,
                read_only_hint=tool.read_only,
                destructive_hint=tool.destructive,
                idempotent_hint=tool.idempotent,
                open_world_hint=False,
            ),
        )
        for tool in MCP_TOOLS
    )


async def _list_tools(
    ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
) -> types.ListToolsResult:
    return types.ListToolsResult(tools=list(tool_listing()))


async def _call_tool(
    ctx: ServerRequestContext[Any], params: types.CallToolRequestParams
) -> types.CallToolResult:
    seen = _DISPATCHED.get()
    if seen is not None:
        seen[0] = True
    return await call_tool(current_request(), params.name, params.arguments)


class AuditRefusedCalls:
    """Server middleware: a ``tools/call`` that the SDK refuses before the dispatcher
    runs (its ``params`` fail the protocol's own validation) still gets its ``mcp.call``
    entry (``validation_error``, ``deny``); the client gets the SDK's JSON-RPC error."""

    async def __call__(self, ctx: ServerRequestContext[Any], call_next: CallNext) -> HandlerResult:
        if ctx.method != "tools/call":
            return await call_next(ctx)
        seen = [False]
        token = _DISPATCHED.set(seen)
        try:
            return await call_next(ctx)
        except Exception:
            if not seen[0]:
                await _audit_refused(ctx.params)
            raise
        finally:
            _DISPATCHED.reset(token)


async def _audit_refused(params: Any) -> None:
    request = current_request()
    name = params.get("name") if isinstance(params, dict) else None
    tool = tool_by_name(name) if isinstance(name, str) else None
    arguments = params.get("arguments") if isinstance(params, dict) else None
    await record_call_separately(
        request.app,
        request.principal,
        tool=tool.name if tool else "unknown",
        rule=tool.rule if tool else None,
        decision="deny",
        code="validation_error",
        arguments=arguments,
    )


def build_server() -> Server[Any]:
    """``soundings``: tools only (no resources, prompts, sampling or subscriptions)."""
    server: Server[Any] = Server(
        MCP_SERVER_NAME,
        version=__version__,
        title=MCP_SERVER_TITLE,
        instructions=MCP_INSTRUCTIONS,
        on_list_tools=_list_tools,
        on_call_tool=_call_tool,
    )
    server.middleware.append(AuditRefusedCalls())
    return server


class McpTransport:
    """Stateless streamable HTTP with JSON responses for one app instance (``run()``
    works once per instance, so each ``create_app()`` builds its own)."""

    def __init__(self) -> None:
        self.server = build_server()
        self.manager = StreamableHTTPSessionManager(
            app=self.server,
            json_response=True,
            stateless=True,
            security_settings=TransportSecuritySettings(enable_dns_rebinding_protection=False),
            max_request_body_size=MCP_MAX_REQUEST_BYTES,
        )

    @asynccontextmanager
    async def run(self) -> AsyncIterator[None]:
        """Run the session manager for the app's lifetime. Its task group must be
        entered and left by one task, so a task of its own holds it: the lifespan's
        start and end may run in different tasks (pytest-asyncio's fixtures do)."""
        started, stopping = asyncio.Event(), asyncio.Event()

        async def hold() -> None:
            async with self.manager.run():
                started.set()
                await stopping.wait()

        holder = asyncio.create_task(hold(), name="mcp-session-manager")
        waiting = asyncio.create_task(started.wait())
        await asyncio.wait({holder, waiting}, return_when=asyncio.FIRST_COMPLETED)
        if not started.is_set():
            waiting.cancel()
            await holder  # raises what made the manager fail to start
        try:
            yield
        finally:
            stopping.set()
            await holder

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self.manager.handle_request(scope, receive, send)
