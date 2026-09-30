"""OpenAPI documentation of the problem+json errors a route can return.

Usage: ``@router.post(..., responses=problems(403, 404, 409))``. Every operation
also documents ``default: Problem`` (see ``app/openapi.py``); this lists the
statuses a client should expect, with the codes in docs/api/contract-phase1.md.
"""

from __future__ import annotations

from typing import Any

from app.errors import PROBLEM_CONTENT_TYPE

__all__ = ["problems"]

_DESCRIPTIONS: dict[int, str] = {
    400: "Bad request (e.g. invalid_cursor)",
    401: "Not signed in (unauthorized)",
    403: "Not allowed (forbidden, csrf_failed, or a specific code)",
    404: "Not found, or not visible to you (not_found)",
    409: "Conflicts with the current state (see code)",
    422: "Validation failed (validation_error, or a specific code)",
}


def problems(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """``responses=`` entries for the given statuses, all ``application/problem+json``."""
    return {
        status: {
            "description": _DESCRIPTIONS[status],
            "content": {
                PROBLEM_CONTENT_TYPE: {
                    "schema": {
                        "$ref": "#/components/schemas/"
                        + ("ValidationProblem" if status == 422 else "Problem")
                    }
                }
            },
        }
        for status in statuses
    }
