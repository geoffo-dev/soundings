"""Schemas shared by every API: problem details and cursor pages."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Problem(BaseModel):
    """RFC 9457 problem details, returned as ``application/problem+json``.

    Clients should branch on ``code`` (stable, snake_case), not on ``title`` or
    ``detail`` (human-readable, may change). As RFC 9457 allows, ``detail``,
    ``instance`` and ``request_id`` may be absent: the one exception to "every
    documented response field is always present".
    """

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "type": "urn:soundings:problem:not_found",
                    "title": "Not Found",
                    "status": 404,
                    "detail": "Idea not found.",
                    "instance": "/api/v1/ideas/0b7c7d1e-7a55-4a4f-9b8b-0d7d3a9d1c11",
                    "code": "not_found",
                    "request_id": "7f9c2b4e1d6a4c0f8e3b5a2d9c1e0f7a",
                }
            ]
        }
    )

    type: str = Field(description="URI identifying the problem type.")
    title: str = Field(description="Short, human-readable summary of the problem type.")
    status: int = Field(description="HTTP status code.")
    detail: str | None = Field(default=None, description="Explanation of this occurrence.")
    instance: str | None = Field(default=None, description="Request path that failed.")
    code: str = Field(description="Stable machine-readable error code (snake_case).")
    request_id: str | None = Field(
        default=None, description="Correlates with server logs (X-Request-ID)."
    )


class FieldError(BaseModel):
    """One request-validation error."""

    loc: list[str | int] = Field(description="Location, e.g. ['body', 'title'].")
    msg: str
    type: str


class ValidationProblem(Problem):
    """422 problem with per-field errors (``code`` is ``validation_error``)."""

    errors: list[FieldError] = Field(default_factory=list)


class Page[T](BaseModel):
    """A page of results in cursor pagination.

    Pass ``next_cursor`` back as ``?cursor=`` to fetch the next page; it is ``null``
    on the last page. Cursors are opaque: never build or parse them client-side.
    """

    # Both fields are always present in responses (next_cursor may be null).
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: list[T]
    next_cursor: str | None = None
