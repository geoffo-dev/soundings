"""Small SQL helpers shared by the services."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, String, Uuid, any_, bindparam, func, select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ProblemError
from app.schemas.common import FieldError

__all__ = ["any_of", "require_unique_lower"]


def any_of(column: Any, ids: Iterable[UUID]) -> ColumnElement[bool]:
    """``column = ANY(:ids)``: one ``uuid[]`` parameter instead of an ``IN`` list with a
    placeholder per id, which is cheaper to build, send and plan for pages of hundreds
    of ideas (and keeps one cached statement whatever the page size)."""
    return column == any_(bindparam(None, list(ids), type_=ARRAY(Uuid())))  # type: ignore[no-any-return]


async def require_unique_lower(
    db: AsyncSession, values: Sequence[str], *, field: str, message: str
) -> None:
    """422 ``validation_error`` (worded like the request schema's own uniqueness check)
    when two of ``values`` are equal under the database's ``lower()``, which the unique
    ``lower(title)`` indexes use. Python's ``casefold`` is not the same fold: "Idea" and
    "İdea" pass the schema but collide in the index (a 500 before; Phase 8 review L1).
    One statement, before the caller writes anything."""
    if len(values) < 2:
        return
    folded: list[str] = list(
        await db.scalars(
            select(func.lower(func.unnest(bindparam(None, list(values), type_=ARRAY(String())))))
        )
    )
    if len(set(folded)) != len(folded):
        raise ProblemError(
            422,
            "validation_error",
            title="Validation Failed",
            detail="The request is invalid; see errors for details.",
            errors=[
                FieldError(loc=["body", field], msg=f"Value error, {message}", type="value_error")
            ],
        )
