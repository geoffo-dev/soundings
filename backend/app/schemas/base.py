"""Base classes and constrained types for the API contract.

* :class:`RequestModel`: request bodies. Unknown fields are rejected (422) and
  strings are stripped, so ``"  "`` fails a ``min_length=1`` check. No string
  anywhere in a body may contain a NUL character (422): PostgreSQL text cannot
  store one. Text query parameters use :data:`NoNul` for the same reason.
* :class:`ResponseModel`: response bodies. Every field is *required* in the
  OpenAPI schema (a default only helps the server build it), so generated
  TypeScript types have no optional response fields; nullable fields are
  ``T | null``. ``from_attributes`` lets the backend validate ORM objects directly.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)

__all__ = [
    "IDEA_KEY_PATTERN",
    "PROJECT_KEY_PATTERN",
    "SLUG_PATTERN",
    "NoNul",
    "RequestModel",
    "ResponseModel",
    "Score",
    "ScoreKey",
    "TagName",
    "reject_nul",
]

SLUG_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"
PROJECT_KEY_PATTERN = r"^[A-Z][A-Z0-9]{1,5}$"
IDEA_KEY_PATTERN = r"^[A-Z][A-Z0-9]{1,5}-[1-9][0-9]*$"


def reject_nul[T](value: T) -> T:
    """``value`` unchanged, or ``ValueError`` if a string in it (also inside lists,
    tuples, sets and dict keys or values) contains NUL (``\\x00``)."""
    if isinstance(value, str):
        if "\x00" in value:
            raise ValueError("must not contain NUL characters")
    elif isinstance(value, list | tuple | set | frozenset):
        for item in value:
            reject_nul(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            reject_nul(key)
            reject_nul(item)
    return value


NoNul = AfterValidator(reject_nul)
"""``Annotated[str | None, Query(...), NoNul]``: 422 instead of a database error."""


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @field_validator("*")
    @classmethod
    def _no_nul(cls, value: Any) -> Any:
        # Nested request models validate their own fields.
        return reject_nul(value)


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
    NoNul,
]
"""A tag name: 1-32 characters, no commas or line breaks. Case-insensitive per project."""
