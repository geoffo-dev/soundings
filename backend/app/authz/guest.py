"""The guest researcher's route table (role matrix table L; contract-phase8b section 4.8).

A guest researcher (column R: the idea's live researcher without a role in its private
project) passes ``idea.view`` on that one idea, so every route that loads an idea and
reads it with only the view rule would let them in. This table decides, operation by
operation, what R may reach; :func:`app.authz.policy.authorize` applies it to every
idea-scoped decision for column R while a request is being served
(``Principal.operation``):

* ``view``: part of R's view (the overview, the feed without its evaluation events,
  comments, the research panel, Similar ideas, research notes, watching).
* ``rule``: the route's own rules decide with R's cells (403 for most; the researcher
  overlay grants commenting, answering and "Hand back").
* ``list``: not an idea page: a list or the inbox that reaches a guest's idea only
  through :func:`app.authz.queries.researched_ideas`; per-idea checks there use the
  rules (My work's "Research to do", search, the inbox, MCP ``search_ideas``).
* ``hidden``: 404 for R (the evaluation, the proposal and its exports, the AI panel and
  its stream, the submission panel, project-only tools).

**Deny by default:** an operation without a row is ``hidden`` for R.
``tests/authz/test_researcher_access.py`` fails for an idea route (a path with ``{idea}``) or
an MCP tool without a row. Outside a request (``operation`` is ``None``: jobs, the
fan-out, the CLI) there is no route, and the rules alone decide (a guest passes
``idea.view`` for their notifications, never ``evaluation.view_own``).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

__all__ = ["RESEARCH_GUEST_ACCESS", "GuestAccess", "guest_access", "mcp_operation"]


class GuestAccess(StrEnum):
    VIEW = "view"
    RULE = "rule"
    LIST = "list"
    HIDDEN = "hidden"


def mcp_operation(tool: str) -> str:
    """The ``Principal.operation`` of an MCP tool call."""
    return f"mcp.{tool}"


_V, _R, _L, _H = GuestAccess.VIEW, GuestAccess.RULE, GuestAccess.LIST, GuestAccess.HIDDEN

# fmt: off
RESEARCH_GUEST_ACCESS: Final[dict[str, GuestAccess]] = {
    # The guest's view of the idea (table L: view)
    "get_idea": _V, "list_idea_activity": _V, "watch_idea": _V, "unwatch_idea": _V,
    "get_idea_research": _V, "list_similar_ideas": _V, "get_research_note": _V,
    # The rules decide with R's cells and the researcher overlay (table L: rule)
    "create_comment": _R, "update_comment": _R, "delete_comment": _R,
    "answer_research_item": _R, "clear_research_item": _R, "remove_researcher": _R,
    "update_idea": _R, "delete_idea": _R, "change_idea_status": _R, "set_idea_owner": _R,
    "volunteer_as_owner": _R, "vote_idea": _R, "unvote_idea": _R,
    "set_research_assignment": _R, "delete_research_note": _R,
    # Lists and the inbox (a guest's idea only through researched_ideas)
    "get_my_work": _L, "get_my_work_counts": _L, "list_my_research_to_do": _L,
    "global_search": _L, "list_notifications": _L, "get_notification_summary": _L,
    "mark_notification_read": _L, "mark_all_notifications_read": _L,
    # The evaluation area (404)
    "add_evaluators": _H, "remove_evaluator": _H, "set_evaluation_due_date": _H,
    "close_evaluation": _H, "reopen_evaluation": _H, "list_evaluations": _H,
    "get_my_evaluation": _H, "save_my_evaluation": _H, "set_evaluation_inclusion": _H,
    # The proposal, its exports, threads and suggestions (404)
    "get_proposal": _H, "create_proposal": _H, "update_proposal_section": _H,
    "export_proposal_markdown": _H, "export_proposal_pdf": _H,
    "list_proposal_threads": _H, "create_proposal_thread": _H,
    "reply_to_proposal_thread": _H, "resolve_proposal_thread": _H,
    "reopen_proposal_thread": _H, "delete_proposal_comment": _H,
    "list_proposal_suggestions": _H, "create_proposal_suggestion": _H,
    "accept_proposal_suggestion": _H, "discard_proposal_suggestion": _H,
    # The submission panel (404)
    "get_idea_submission": _H, "approve_submission": _H, "reject_submission": _H,
    "erase_submitter": _H,
    # The AI panel and its stream (404)
    "list_idea_ai_runs": _H, "request_ai_evaluation": _H, "request_ai_research": _H,
    "request_ai_section_draft": _H, "get_ai_run": _H, "cancel_ai_run": _H,
    "stream_ai_run_events": _H,
    # MCP tools (table L)
    "mcp.get_idea": _V, "mcp.search_ideas": _L, "mcp.add_comment": _R,
    "mcp.list_projects": _L, "mcp.add_research_note": _R,
    "mcp.get_rubric": _H, "mcp.get_proposal": _H, "mcp.create_idea": _H,
    "mcp.propose_proposal_section": _H, "mcp.submit_evaluation": _H,
}
# fmt: on
"""Every operation and MCP tool a guest researcher may reach; anything else is hidden."""


def guest_access(operation: str | None) -> GuestAccess | None:
    """R's access for the operation being served; ``None`` outside a request (the rules
    decide); ``hidden`` for an operation without a row (deny by default)."""
    if operation is None:
        return None
    return RESEARCH_GUEST_ACCESS.get(operation, GuestAccess.HIDDEN)
