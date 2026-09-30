"""Pydantic request/response schemas: the API contract (owned by the lead).

One module per area: ``auth``, ``users``, ``projects``, ``rubric``, ``ideas``,
``evaluations``, ``comments``, ``activity``, ``work``, ``search``; shared pieces in
``base`` and ``common``. Summary with business rules: docs/api/contract-phase1.md.
"""

from app.schemas.common import FieldError, Page, Problem, ValidationProblem

__all__ = ["FieldError", "Page", "Problem", "ValidationProblem"]
