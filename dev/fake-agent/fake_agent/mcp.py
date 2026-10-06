"""A small MCP client for Soundings' ``/mcp`` (streamable HTTP, stateless): initialize,
``notifications/initialized``, then ``tools/call``, as kagent's Go MCP client does. The
key goes in the ``Authorization`` header and nowhere else (never logged)."""

from __future__ import annotations

import itertools
import json
import logging
import os
import ssl
from dataclasses import dataclass
from typing import Any

import httpx

log = logging.getLogger("fake_agent.mcp")

PROTOCOL_VERSION = "2025-11-25"
CLIENT_INFO = {"name": "soundings-fake-agent", "version": "0.1.0"}


class McpTransportError(Exception):
    """The MCP server couldn't be reached or answered something that isn't MCP (a
    revoked key's 401, a 5xx, a dropped connection). Carries the HTTP status only."""

    def __init__(self, what: str, status: int | None = None) -> None:
        super().__init__(f"{what} (HTTP {status})" if status else what)
        self.status = status


@dataclass(frozen=True)
class ToolResult:
    tool: str
    is_error: bool
    content: dict[str, Any]
    """``structuredContent``: the tool's output, or ``{code, message}`` for a tool error."""

    @property
    def error_code(self) -> str | None:
        if not self.is_error:
            return None
        code = self.content.get("code")
        return code if isinstance(code, str) else "error"


def _json_from_sse(text: str) -> dict[str, Any]:
    data = [line[5:].strip() for line in text.splitlines() if line.startswith("data:")]
    for item in reversed(data):
        if item:
            parsed = json.loads(item)
            if isinstance(parsed, dict):
                return parsed
    raise McpTransportError("an empty event stream")


class McpClient:
    def __init__(self, url: str, key: str, *, timeout: float = 30.0) -> None:
        self._url = url
        self._ids = itertools.count(1)
        self._protocol = PROTOCOL_VERSION
        # No proxy or .netrc from the environment (like Soundings' own A2A client); an
        # https MCP URL is verified against SSL_CERT_FILE when set, else the system CAs.
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=10.0),
            follow_redirects=False,
            trust_env=False,
            verify=ssl.create_default_context(cafile=os.environ.get("SSL_CERT_FILE") or None),
            headers={
                "Authorization": f"Bearer {key}",
                "Accept": "application/json, text/event-stream",
                "User-Agent": "soundings-fake-agent/0.1",
            },
        )

    async def __aenter__(self) -> McpClient:
        await self.initialize()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def close(self) -> None:
        await self._http.aclose()

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        try:
            response = await self._http.post(
                self._url, json=payload, headers={"MCP-Protocol-Version": self._protocol}
            )
        except httpx.HTTPError as error:
            raise McpTransportError(type(error).__name__) from None
        if response.status_code == 202 and "id" not in payload:
            return None  # a notification
        if response.status_code != 200:
            raise McpTransportError("the MCP server refused the request", response.status_code)
        kind = response.headers.get("content-type", "")
        try:
            body = (
                _json_from_sse(response.text)
                if kind.startswith("text/event-stream")
                else response.json()
            )
        except ValueError:
            raise McpTransportError("an answer that isn't JSON", response.status_code) from None
        if not isinstance(body, dict):
            raise McpTransportError("an answer that isn't a JSON-RPC response")
        if "error" in body:
            code = body["error"].get("code") if isinstance(body["error"], dict) else None
            raise McpTransportError(f"JSON-RPC error {code}")
        return body

    async def initialize(self) -> None:
        body = await self._post(
            {
                "jsonrpc": "2.0",
                "id": next(self._ids),
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": CLIENT_INFO,
                },
            }
        )
        result = (body or {}).get("result") or {}
        self._protocol = str(result.get("protocolVersion") or PROTOCOL_VERSION)
        await self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})

    async def call(self, tool: str, arguments: dict[str, Any]) -> ToolResult:
        body = await self._post(
            {
                "jsonrpc": "2.0",
                "id": next(self._ids),
                "method": "tools/call",
                "params": {"name": tool, "arguments": arguments},
            }
        )
        result = (body or {}).get("result")
        if not isinstance(result, dict):
            raise McpTransportError("a tools/call answer without a result")
        content = result.get("structuredContent")
        if not isinstance(content, dict):
            content = {}
            for item in result.get("content") or []:
                if isinstance(item, dict) and item.get("type") == "text":
                    try:
                        parsed = json.loads(item.get("text") or "")
                    except ValueError:
                        continue
                    if isinstance(parsed, dict):
                        content = parsed
                        break
        tool_result = ToolResult(tool=tool, is_error=bool(result.get("isError")), content=content)
        log.info("tool %s: %s", tool, tool_result.error_code or "ok")
        return tool_result
