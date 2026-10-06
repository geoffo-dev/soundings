"""Base classes and constrained types for the API contract.

* :class:`RequestModel`: request bodies. Unknown fields are rejected (422) and
  strings are stripped, so ``"  "`` fails a ``min_length=1`` check. No string
  anywhere in a body may contain a NUL character (422): PostgreSQL text cannot
  store one. Text query parameters use :data:`NoNul` for the same reason.
  Nor may it contain a Unicode tag character (U+E0000-U+E007F): they are invisible
  and are used to hide instructions for AI models in text an agent later reads
  (:func:`reject_hidden`). One-line names that reach email subjects and headers (idea
  titles, display names) also reject line breaks, other control characters, bidi
  controls and tag characters (:data:`SingleLine`).
* :class:`ResponseModel`: response bodies. Every field is *required* in the
  OpenAPI schema (a default only helps the server build it), so generated
  TypeScript types have no optional response fields; nullable fields are
  ``T | null``. ``from_attributes`` lets the backend validate ORM objects directly.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator
from typing import Annotated, Any, Final, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)

__all__ = [
    "BIDI_CONTROLS",
    "IDEA_KEY_PATTERN",
    "PROJECT_KEY_PATTERN",
    "SLUG_PATTERN",
    "NoNul",
    "RequestModel",
    "ResponseModel",
    "Score",
    "ScoreKey",
    "SingleLine",
    "TagName",
    "has_tag_character",
    "reject_control",
    "reject_hidden",
    "reject_nul",
]

SLUG_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"
PROJECT_KEY_PATTERN = r"^[A-Z][A-Z0-9]{1,5}$"
IDEA_KEY_PATTERN = r"^[A-Z][A-Z0-9]{1,5}-[1-9][0-9]*$"


def _strings(value: object) -> Iterator[str]:
    """Every string in ``value``, also inside lists, tuples, sets and dict keys or values."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, list | tuple | set | frozenset):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _strings(key)
            yield from _strings(item)


def reject_nul[T](value: T) -> T:
    """``value`` unchanged, or ``ValueError`` if a string in it (also inside lists,
    tuples, sets and dict keys or values) contains NUL (``\\x00``)."""
    if any("\x00" in text for text in _strings(value)):
        raise ValueError("must not contain NUL characters")
    return value


_TAG_CHARACTERS: Final = re.compile("[\U000e0000-\U000e007f]")
"""Unicode tag characters (U+E0000-U+E007F): invisible, they mirror ASCII and can carry
hidden instructions to AI models ("ASCII smuggling"). The only other use, subdivision
flag emoji such as Scotland's, is refused with them (simple beats configurable)."""


def has_tag_character(value: str) -> bool:
    """True if ``value`` has a Unicode tag character (:data:`_TAG_CHARACTERS`)."""
    return _TAG_CHARACTERS.search(value) is not None


def reject_hidden[T](value: T) -> T:
    """:func:`reject_nul`, and ``ValueError`` if a string in ``value`` has a Unicode tag
    character (U+E0000-U+E007F). Every request body string goes through it
    (:class:`RequestModel`), and so do the MCP tools' arguments."""
    reject_nul(value)
    if any(has_tag_character(text) for text in _strings(value)):
        raise ValueError("must not contain invisible Unicode tag characters")
    return value


NoNul = AfterValidator(reject_nul)
"""``Annotated[str | None, Query(...), NoNul]``: 422 instead of a database error."""


BIDI_CONTROLS: Final = frozenset(
    "\u061c"  # ARABIC LETTER MARK
    + "".join(map(chr, range(0x202A, 0x202F)))  # LRE, RLE, PDF, LRO, RLO
    + "".join(map(chr, range(0x2066, 0x206A)))  # LRI, RLI, FSI, PDI
)
"""Bidi controls that reorder the text after them (a display name could make an email
line read backwards); the marks U+200E / U+200F stay allowed."""

_BREAKING_CATEGORIES: Final = frozenset({"Cc", "Zl", "Zp"})


def has_control(value: str) -> bool:
    """True if ``value`` has a control character (Unicode ``Cc``: CR, LF, tab, NUL, …),
    a line or paragraph separator (``Zl`` / ``Zp``: U+2028, U+2029), a bidi control
    (:data:`BIDI_CONTROLS`) or a Unicode tag character (:func:`has_tag_character`)."""
    return has_tag_character(value) or any(
        unicodedata.category(char) in _BREAKING_CATEGORIES or char in BIDI_CONTROLS
        for char in value
    )


def reject_control[T](value: T) -> T:
    """``value`` unchanged, or ``ValueError`` if it is a string with a line break or
    another control character."""
    if isinstance(value, str) and has_control(value):
        raise ValueError("must be one line without control or invisible characters")
    return value


SingleLine = AfterValidator(reject_control)
"""``Annotated[str, Field(...), SingleLine]``: a one-line name (an idea title, a display
name) that ends up in email subjects, so CR/LF and other control characters, U+2028 /
U+2029, bidi controls and tag characters are a 422 (:func:`has_control`)."""


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @field_validator("*")
    @classmethod
    def _no_nul(cls, value: Any) -> Any:
        # Nested request models validate their own fields.
        return reject_hidden(value)


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
