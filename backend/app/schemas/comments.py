"""Comment requests (comments are returned as ``CommentActivity`` feed items), and the
@mention syntax (contract-phase3 section 3.8)."""

from __future__ import annotations

import re
from typing import Final
from uuid import UUID

from pydantic import Field

from app.schemas.base import RequestModel

__all__ = [
    "MAX_MENTIONS",
    "MENTION_PATTERN",
    "CommentCreate",
    "CommentUpdate",
    "mention_token",
    "mentioned_user_ids",
]

MAX_COMMENT_LENGTH = 10_000

MENTION_PATTERN: Final = re.compile(
    r"@\[(?P<label>[^\[\]\r\n]{1,100})\]"
    r"\(user:(?P<user_id>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\)"
)
"""An @mention in a comment's Markdown: ``@[Ada Lovelace](user:<user id>)``, inserted by
the SPA's mention picker. The server rewrites each label to the user's current
display name, so a label can't impersonate someone else."""

MAX_MENTIONS: Final = 20
"""Distinct users one comment may mention (more: 422 ``too_many_mentions``)."""

_MENTION_DESCRIPTION = (
    " Mention someone with @[Display Name](user:<user id>): people with a role in the "
    "idea's project who can view it are notified (labels are rewritten to the user's "
    f"current name, and the result must still fit {MAX_COMMENT_LENGTH:,} characters; at most "
    f"{MAX_MENTIONS} people per comment)."
)


def mention_token(user_id: UUID, display_name: str) -> str:
    """The token for ``user_id``, labelled with ``display_name`` (brackets and line
    breaks removed, spaces collapsed, at most 100 characters)."""
    label = " ".join(re.sub(r"[\[\]\r\n]+", " ", display_name).split())[:100].strip()
    label = label or "user"
    return f"@[{label}](user:{user_id})"


def mentioned_user_ids(body_md: str) -> list[UUID]:
    """The distinct users ``body_md`` mentions, in order of first appearance."""
    found: dict[UUID, None] = {}
    for match in MENTION_PATTERN.finditer(body_md):
        found.setdefault(UUID(match.group("user_id")), None)
    return list(found)


class CommentCreate(RequestModel):
    body_md: str = Field(
        min_length=1,
        max_length=MAX_COMMENT_LENGTH,
        description="Markdown." + _MENTION_DESCRIPTION,
    )


class CommentUpdate(RequestModel):
    body_md: str = Field(
        min_length=1,
        max_length=MAX_COMMENT_LENGTH,
        description="Markdown. Newly mentioned people are notified." + _MENTION_DESCRIPTION,
    )
