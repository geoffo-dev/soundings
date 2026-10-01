"""Pydantic request/response schemas: the API contract (owned by the lead).

One module per area: ``auth``, ``users``, ``projects``, ``rubric``, ``ideas``,
``evaluations``, ``comments``, ``activity``, ``work``, ``search``; Phase 2 adds
``groups``, ``admin_users``, ``audit`` and ``sso``. Shared pieces in ``base`` and
``common``. Summaries with business rules: docs/api/contract-phase1.md and
docs/api/contract-phase2.md.
"""

from app.schemas.common import FieldError, Page, Problem, ValidationProblem

__all__ = ["FieldError", "Page", "Problem", "ValidationProblem"]
