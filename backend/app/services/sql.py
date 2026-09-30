"""Small SQL helpers shared by the services."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, Uuid, any_, bindparam
from sqlalchemy.dialects.postgresql import ARRAY

__all__ = ["any_of"]


def any_of(column: Any, ids: Iterable[UUID]) -> ColumnElement[bool]:
    """``column = ANY(:ids)``: one ``uuid[]`` parameter instead of an ``IN`` list with a
    placeholder per id, which is cheaper to build, send and plan for pages of hundreds
    of ideas (and keeps one cached statement whatever the page size)."""
    return column == any_(bindparam(None, list(ids), type_=ARRAY(Uuid())))  # type: ignore[no-any-return]
