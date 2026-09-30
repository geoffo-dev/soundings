"""Idea references: every ``/ideas/{idea}`` route takes the UUID or the key.

A key is ``<project key>-<number>`` (``CUST-12``) and is matched in any case
(``cust-12``). The route's path pattern already rejects anything else (422).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final
from uuid import UUID

__all__ = ["IdeaKey", "format_key", "parse_idea_key", "parse_idea_ref"]

_KEY: Final = re.compile(r"^([A-Za-z][A-Za-z0-9]{1,5})-([1-9][0-9]{0,8})$")


@dataclass(frozen=True, slots=True)
class IdeaKey:
    project_key: str
    """Upper-case, as stored in ``projects.key``."""
    number: int


def format_key(project_key: str, number: int) -> str:
    return f"{project_key}-{number}"


def parse_idea_key(text: str) -> IdeaKey | None:
    """``"cust-12"`` -> ``IdeaKey("CUST", 12)``; ``None`` if it is not a key."""
    match = _KEY.match(text.strip())
    if match is None:
        return None
    return IdeaKey(match.group(1).upper(), int(match.group(2)))


def parse_idea_ref(ref: str) -> UUID | IdeaKey:
    """The idea's id, or its key. Raises ``ValueError`` for anything else."""
    key = parse_idea_key(ref)
    if key is not None:
        return key
    return UUID(ref)
