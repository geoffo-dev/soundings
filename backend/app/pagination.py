"""Cursor (keyset) pagination helpers.

A list endpoint takes ``?cursor=&limit=`` via :data:`PageParamsDep`, fetches
``limit + 1`` rows ordered by a unique key, and returns a :class:`Page`::

    @router.get("/ideas")
    async def list_ideas(session: SessionDep, page: PageParamsDep) -> Page[IdeaOut]:
        after = decode_cursor(page.cursor) if page.cursor else None
        stmt = select(Idea).order_by(Idea.created_at.desc(), Idea.id.desc())
        if after:
            stmt = stmt.where(
                tuple_(Idea.created_at, Idea.id)
                < (datetime.fromisoformat(after["created_at"]), UUID(after["id"]))
            )
        rows = (await session.scalars(stmt.limit(page.limit + 1))).all()
        items, next_cursor = slice_page(
            rows, page.limit, lambda i: {"created_at": i.created_at, "id": i.id}
        )
        return Page(items=[IdeaOut.model_validate(i) for i in items], next_cursor=next_cursor)

Cursors are opaque to clients (base64url JSON) but not signed: never put anything
in a cursor that the caller may not see, and always re-apply authorisation filters.
"""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, Query

from app.errors import ProblemError
from app.schemas.common import Page

__all__ = [
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "InvalidCursorProblem",
    "Page",
    "PageParams",
    "PageParamsDep",
    "decode_cursor",
    "encode_cursor",
    "slice_page",
]

DEFAULT_LIMIT = 50
MAX_LIMIT = 200
_MAX_CURSOR_LENGTH = 1024


class InvalidCursorProblem(ProblemError):
    def __init__(self) -> None:
        super().__init__(400, "invalid_cursor", detail="The pagination cursor is invalid.")


def _json_default(value: object) -> str:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    raise TypeError(f"cannot encode {type(value).__name__} in a cursor")


def encode_cursor(values: Mapping[str, Any]) -> str:
    """Encode keyset values as an opaque URL-safe cursor.

    ``datetime``/``date`` become ISO strings and ``UUID`` becomes a string; decode
    them back explicitly when building the query.
    """
    raw = json.dumps(values, default=_json_default, separators=(",", ":"), sort_keys=True)
    return base64.urlsafe_b64encode(raw.encode()).rstrip(b"=").decode("ascii")


def decode_cursor(cursor: str) -> dict[str, Any]:
    """Decode a cursor from :func:`encode_cursor`; raises a 400 problem if malformed."""
    if not cursor or len(cursor) > _MAX_CURSOR_LENGTH:
        raise InvalidCursorProblem
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except (ValueError, binascii.Error, UnicodeError) as exc:
        raise InvalidCursorProblem from exc
    if not isinstance(data, dict):
        raise InvalidCursorProblem
    return data


def slice_page[T](
    rows: Sequence[T], limit: int, cursor_for: Callable[[T], Mapping[str, Any]]
) -> tuple[list[T], str | None]:
    """Split ``limit + 1`` fetched rows into the page items and the next cursor."""
    items = list(rows[:limit])
    next_cursor = encode_cursor(cursor_for(items[-1])) if len(rows) > limit and items else None
    return items, next_cursor


@dataclass(frozen=True, slots=True)
class PageParams:
    cursor: str | None
    limit: int


def page_params(
    cursor: Annotated[
        str | None,
        Query(max_length=_MAX_CURSOR_LENGTH, description="Opaque cursor from next_cursor."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT, description="Page size.")] = DEFAULT_LIMIT,
) -> PageParams:
    return PageParams(cursor=cursor, limit=limit)


PageParamsDep = Annotated[PageParams, Depends(page_params)]
