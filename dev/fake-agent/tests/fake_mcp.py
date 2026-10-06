"""A stand-in for Soundings' ``/mcp`` in these unit tests: just enough of the nine tools
(plus ``add_research_note``) and of c22 to see what the agent sends. The real server is
exercised by the e2e stack (``E2E_AI=1``), ``make ai-smoke`` and ``k3s-smoke AI=1``."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

IDEA = "CUST-12"
PROJECT = {"id": "p1", "slug": "customer-innovation", "key": "CUST", "name": "Customer Innovation"}
CRITERIA = [
    {"id": "11111111-0000-0000-0000-000000000001", "name": "Impact", "position": 0},
    {"id": "11111111-0000-0000-0000-000000000002", "name": "Effort", "position": 1},
    {"id": "11111111-0000-0000-0000-000000000003", "name": "Fit", "position": 2},
]
SECTIONS = [
    {"key": "summary", "title": "Summary", "body_md": "", "version": 1},
    {"key": "risks", "title": "Risks", "body_md": "Known risks.", "version": 3},
]
AGENT_WRITES = {"submit_evaluation", "add_research_note", "propose_proposal_section"}


@dataclass
class FakeMcp:
    calls: list[dict[str, Any]] = field(default_factory=list)
    run_open: bool = True
    """While false, every tool answers ``ai_run_not_active`` (a run that ended)."""
    open_kind: str = "evaluate"
    open_section: str | None = None
    status: int = 200
    lock: threading.Lock = field(default_factory=threading.Lock)

    def tools(self) -> list[str]:
        with self.lock:
            return [call["tool"] for call in self.calls if call["tool"]]

    def arguments(self, tool: str) -> dict[str, Any]:
        with self.lock:
            return next(call["arguments"] for call in self.calls if call["tool"] == tool)

    def _tool(self, name: str, args: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
        def error(code: str) -> tuple[bool, dict[str, Any]]:
            return True, {"code": code, "message": f"refused: {code}"}

        if not self.run_open:
            return error("ai_run_not_active")
        if name in ("add_comment", "create_idea"):
            return error("forbidden")
        idea = args.get("idea")
        if idea is not None and idea != IDEA:
            return error("ai_run_not_active")
        if name in AGENT_WRITES:
            wanted = {
                "evaluate": "submit_evaluation",
                "research": "add_research_note",
                "draft_section": "propose_proposal_section",
            }[self.open_kind]
            if name != wanted:
                return error("ai_run_not_active")
            if name == "propose_proposal_section" and args.get("section_key") != self.open_section:
                return error("ai_run_not_active")
        idea_ref = {"key": IDEA, "title": "Planted text", "project": PROJECT}
        if name == "get_rubric":
            return False, {"project": PROJECT, "criteria": CRITERIA}
        if name == "get_idea":
            return False, {
                "idea": {
                    **idea_ref,
                    "score_hidden": True,
                    "score": None,
                    "aggregate": None,
                    "evaluation_count": 0,
                    "evaluations": [],
                    "high_disagreement": False,
                    "my_evaluation": {"state": "invited"},
                }
            }
        if name == "search_ideas":
            return False, {
                "items": [
                    {**idea_ref, "score_hidden": True, "score": None, "high_disagreement": False}
                ],
                "next_cursor": None,
            }
        if name == "list_projects":
            return False, {"projects": [PROJECT]}
        if name == "get_proposal":
            return False, {"idea": idea_ref, "proposal": {"id": "x", "sections": SECTIONS}}
        if name == "submit_evaluation":
            return False, {"idea": idea_ref, "evaluation": {"state": "submitted"}}
        if name == "add_research_note":
            return False, {"idea": idea_ref, "note_id": "n1", "replaced": False}
        if name == "propose_proposal_section":
            return False, {"idea": idea_ref, "suggestion": {"id": "s1"}}
        return error("unknown_tool")

    def app(self) -> Starlette:
        async def mcp(request: Request) -> Response:
            body = await request.json()
            method = body.get("method")
            with self.lock:
                status = self.status
            if status != 200:
                return JSONResponse({"code": "unauthorized"}, status_code=status)
            if method == "notifications/initialized":
                return Response(status_code=202)
            if method == "initialize":
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": body["id"],
                        "result": {"protocolVersion": "2025-11-25", "capabilities": {}},
                    }
                )
            params = body.get("params") or {}
            name, args = str(params.get("name") or ""), params.get("arguments") or {}
            with self.lock:
                self.calls.append(
                    {
                        "tool": name,
                        "arguments": args,
                        "authorization": request.headers.get("authorization"),
                        "protocol": request.headers.get("mcp-protocol-version"),
                    }
                )
                is_error, content = self._tool(name, args)
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": {
                        "content": [{"type": "text", "text": "…"}],
                        "structuredContent": content,
                        "isError": is_error,
                    },
                }
            )

        return Starlette(routes=[Route("/mcp", mcp, methods=["POST"])])
