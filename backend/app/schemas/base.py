"""Base classes and constrained types for the API contract.

* :class:`RequestModel`: request bodies. Unknown fields are rejected (422) and
  strings are stripped, so ``"  "`` fails a ``min_length=1`` check.
* :class:`ResponseModel`: response bodies. Every field is *required* in the
  OpenAPI schema (a default only helps the server build it), so generated
  TypeScript types have no optional response fields; nullable fields are
  ``T | null``. ``from_attributes`` lets the backend validate ORM objects directly.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

__all__ = [
    "IDEA_KEY_PATTERN",
    "PROJECT_KEY_PATTERN",
    "SLUG_PATTERN",
    "RequestModel",
    "ResponseModel",
    "Score",
    "ScoreKey",
    "TagName",
]

SLUG_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"
PROJECT_KEY_PATTERN = r"^[A-Z][A-Z0-9]{1,5}$"
IDEA_KEY_PATTERN = r"^[A-Z][A-Z0-9]{1,5}-[1-9][0-9]*$"


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ResponseModel(BaseModel):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )


Score = Annotated[int, Field(ge=1, le=5, description="Rubric score, 1 (low) to 5 (high).")]
"""A 1-5 rubric score."""

ScoreKey = Literal["1", "2", "3", "4", "5"]
"""Key of a per-score guidance hint (JSON object keys are strings)."""

TagName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=32, pattern=r"^[^,\r\n\t]+$"),
]
"""A tag name: 1-32 characters, no commas or line breaks. Case-insensitive per project."""
