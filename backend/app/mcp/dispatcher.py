"""The one ``tools/call`` dispatcher (contract-phase5 section 4.2).

For every call: find the tool in the catalogue (else ``unknown_tool``), validate the
arguments with its ``*Input`` model (else ``validation_error``, naming the fields, never
their values), spend one of the key's writes for a tool that isn't read-only (else
``too_many_attempts``), run the tool in one unit of work (``session_scope`` with the
settings, so the before-commit fan-out sends email as in the app), turn a
:class:`~app.errors.ProblemError` into a tool error carrying the REST problem code and
anything else into ``internal_error`` (logged with the traceback), and audit the call
as ``mcp.call`` exactly once: in the tool's transaction when it commits, otherwise in a
short transaction of its own after the rollback (:mod:`app.mcp.audit`).

``decision`` in the entry is ``deny`` when the call was refused before or by
authorisation (an unknown tool, invalid arguments, the write cap, 401/403/404 from the
policy) and ``allow`` otherwise: successes, business failures (409 and 422 from the
service, ``invalid_cursor``) and crashes.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any, Final

import mcp_types as types
from pydantic import BaseModel, ValidationError

from app.auth.key_auth import take_key_write
from app.db import session_scope
from app.errors import ProblemError
from app.mcp.audit import AuditTarget, Decision, record_call, record_call_separately
from app.mcp.context import McpRequest
from app.mcp.tools import TOOLS, ToolContext
from app.schemas.mcp import McpTool, McpToolError, tool_by_name

__all__ = ["call_tool", "error_result", "success_result", "validation_message"]

logger = logging.getLogger(__name__)

_DENIED_STATUSES: Final = frozenset({401, 403, 404, 429})
_MAX_FIELDS: Final = 8


def success_result(output: BaseModel) -> types.CallToolResult:
    """The ``*Output`` model as ``structuredContent``, and the same JSON as text."""
    data = output.model_dump(mode="json")
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=text)], structured_content=data
    )


def error_result(code: str, message: str) -> types.CallToolResult:
    """A tool error: ``isError``, text ``"<code>: <message>"``, ``McpToolError``."""
    error = McpToolError(code=code, message=message)
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=f"{code}: {message}")],
        structured_content=error.model_dump(mode="json"),
        is_error=True,
    )


def validation_message(exc: ValidationError) -> str:
    """Which arguments are wrong and how, from field names and error types: never a
    value. Pydantic's own messages can quote the input, so only the messages of our
    validators (``value_error``: fixed sentences such as "give either project or idea")
    are kept."""
    problems: dict[str, str] = {}
    for error in exc.errors(include_url=False, include_input=False, include_context=False):
        location = ".".join(str(part) for part in error["loc"]) or "arguments"
        kind = error["type"]
        if kind == "value_error":
            kind = error["msg"].removeprefix("Value error, ")
        problems.setdefault(location, kind)
    listed = [f"{location} ({kind})" for location, kind in list(problems.items())[:_MAX_FIELDS]]
    more = len(problems) - len(listed)
    suffix = f" and {more} more" if more > 0 else ""
    return "Invalid arguments: " + ", ".join(listed) + suffix + "."


def _problem_message(problem: ProblemError) -> str:
    """The problem's ``detail``, plus the fields its ``errors`` name (``evaluation_incomplete``
    lists the criteria still missing a score: ``scores.<criterion id>``)."""
    message = problem.detail or problem.title
    if problem.errors:
        fields = [
            ".".join(str(part) for part in error.loc[1 if error.loc[:1] == ["body"] else 0 :])
            for error in problem.errors
        ]
        message = f"{message} Missing or invalid: {', '.join(fields)}."
    return message


def _decision(problem: ProblemError) -> Decision:
    return "deny" if problem.status in _DENIED_STATUSES else "allow"


async def call_tool(
    request: McpRequest, name: str, arguments: Mapping[str, Any] | None
) -> types.CallToolResult:
    """Run one ``tools/call`` for the bound request and audit it once."""
    app, principal = request.app, request.principal
    tool = tool_by_name(name)
    if tool is None:
        await record_call_separately(
            app, principal, tool="unknown", rule=None, decision="deny", code="unknown_tool"
        )
        return error_result("unknown_tool", "There is no tool with that name.")
    raw = dict(arguments or {})
    try:
        args = tool.input.model_validate(raw)
    except ValidationError as exc:
        await _refused(request, tool, "validation_error", raw)
        return error_result("validation_error", validation_message(exc))
    if not tool.read_only and take_key_write(app, principal) is not None:
        await _refused(request, tool, "too_many_attempts", raw)
        return error_result(
            "too_many_attempts", "This API key made too many changes. Try again in a minute."
        )
    return await _run(request, tool, args, raw)


async def _refused(request: McpRequest, tool: McpTool, code: str, raw: object) -> None:
    await record_call_separately(
        request.app,
        request.principal,
        tool=tool.name,
        rule=tool.rule,
        decision="deny",
        code=code,
        arguments=raw,
    )


async def _run(
    request: McpRequest, tool: McpTool, args: BaseModel, raw: dict[str, Any]
) -> types.CallToolResult:
    app, principal = request.app, request.principal
    target = AuditTarget()
    try:
        async with session_scope(app.state.sessionmaker, settings=app.state.settings) as db:
            context = ToolContext(
                db=db, principal=principal, settings=app.state.settings, target=target
            )
            output = await TOOLS[tool.name](context, args)
            await record_call(
                db,
                principal,
                tool=tool.name,
                rule=tool.rule,
                decision="allow",
                code=None,
                target=target,
            )
        return success_result(output)
    except ProblemError as problem:
        code, message = problem.code, _problem_message(problem)
        decision = _decision(problem)
    except Exception:
        logger.exception("mcp tool failed", extra={"tool": tool.name})
        code, message = "internal_error", "Something went wrong. Try again later."
        decision = "allow"
    await record_call_separately(
        app,
        principal,
        tool=tool.name,
        rule=tool.rule,
        decision=decision,
        code=code,
        target=target,
        arguments=raw,
    )
    return error_result(code, message)
