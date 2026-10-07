"""OpenAPI documentation shared by the requests the Phase 8 research gate guards
(contract-phase8 section 3.5): ``change_idea_status``, ``add_evaluators``,
``create_proposal`` and ``request_ai_evaluation``. Their 409 is a
``ResearchIncompleteProblem``: with code ``research_incomplete`` it lists the open
required items and whether you may move anyway; their other 409 codes don't carry them."""

from __future__ import annotations

from typing import Any, Final

from app.errors import PROBLEM_CONTENT_TYPE

__all__ = ["GATE_DESCRIPTION", "research_gate_conflict"]

GATE_DESCRIPTION: Final = (
    " Phase 8: 409 research_incomplete (with open_items and can_override) while required "
    "research checklist items are open and the request would take the idea past Research; "
    "override_research: true (idea.research_override: project and platform admins, "
    "session only, else 403) moves anyway, audited as idea.research_override."
)


def research_gate_conflict(other_codes: str) -> dict[int | str, dict[str, Any]]:
    """``responses=`` entry for a guarded route's 409 (``other_codes``: its other 409
    codes, for the description)."""
    return {
        409: {
            "description": (
                "Conflicts with the current state: research_incomplete (with open_items and "
                f"can_override), {other_codes}"
            ),
            "content": {
                PROBLEM_CONTENT_TYPE: {
                    "schema": {"$ref": "#/components/schemas/ResearchIncompleteProblem"}
                }
            },
        }
    }
