"""OpenAPI documentation of the problem+json errors a route can return.

Usage: ``@router.post(..., responses=problems(403, 404, 409))``. Every operation
also documents ``default: Problem`` (see ``app/openapi.py``); this lists the
statuses a client should expect, with the codes in docs/api/contract-phase1.md.
"""

from __future__ import annotations

from typing import Any

from app.errors import PROBLEM_CONTENT_TYPE

__all__ = ["binary", "binary_body", "problems", "redirect"]

_DESCRIPTIONS: dict[int, str] = {
    400: "Bad request (e.g. invalid_cursor)",
    401: "Not signed in (unauthorized)",
    403: "Not allowed (forbidden, csrf_failed, or a specific code)",
    404: "Not found, or not visible to you (not_found)",
    409: "Conflicts with the current state (see code)",
    413: "Request body too large (content_too_large)",
    415: "Wrong Content-Type (unsupported_media_type)",
    422: "Validation failed (validation_error, or a specific code)",
    429: "Too many attempts (too_many_attempts): wait and retry",
    503: "Busy (see code): retry shortly",
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


def redirect(status: int, description: str) -> dict[int | str, dict[str, Any]]:
    """``responses=`` entry for a browser redirect (``Location`` header, no body)."""
    return {
        status: {
            "description": description,
            "headers": {
                "Location": {
                    "description": "Where the browser goes next.",
                    "schema": {"type": "string"},
                }
            },
        }
    }


def binary(
    status: int, description: str, *media_types: str, headers: dict[str, str] | None = None
) -> dict[int | str, dict[str, Any]]:
    """``responses=`` entry for a non-JSON body (a file download, an image), with
    optional documented headers (name -> description)."""
    entry: dict[str, Any] = {
        "description": description,
        "content": {
            media_type: {"schema": {"type": "string", "format": "binary"}}
            for media_type in media_types
        },
    }
    if headers:
        entry["headers"] = {
            name: {"description": text, "schema": {"type": "string"}}
            for name, text in headers.items()
        }
    return {status: entry}


def binary_body(*media_types: str, description: str) -> dict[str, Any]:
    """``openapi_extra=`` for a route that reads a raw (non-JSON) request body."""
    return {
        "requestBody": {
            "required": True,
            "description": description,
            "content": {
                media_type: {"schema": {"type": "string", "format": "binary"}}
                for media_type in media_types
            },
        }
    }
