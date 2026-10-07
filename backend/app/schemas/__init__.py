"""Pydantic request/response schemas: the API contract (owned by the lead).

One module per area: ``auth``, ``users``, ``projects``, ``rubric``, ``ideas``,
``evaluations``, ``comments``, ``activity``, ``work``, ``search``; Phase 2 adds
``groups``, ``admin_users``, ``audit`` and ``sso``; Phase 3 adds ``notifications``
and ``email``; Phase 4 adds ``proposals``, ``public`` and ``branding``; Phase 5 adds
``api_keys``, ``mcp`` (the MCP tool catalogue: not part of OpenAPI) and the suggestion
models in ``proposals``; Phase 6 adds ``ai``; Phase 8 adds ``research`` and the
per-project template models in ``proposals``. Shared pieces in ``base`` and ``common``.
Summaries with business rules: docs/api/contract-phase1.md to contract-phase8.md.
"""

from app.schemas.common import FieldError, Page, Problem, ValidationProblem

__all__ = ["FieldError", "Page", "Problem", "ValidationProblem"]
