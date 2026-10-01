"""@mentions in comments (contract-phase3 section 3.8).

Tokens look like ``@[Display Name](user:<uuid>)`` (the SPA's picker inserts them). When
a comment is written: more than :data:`~app.schemas.comments.MAX_MENTIONS` distinct
people is 422 ``too_many_mentions``; each token naming an active person is rewritten
with their current display name (so a label can't impersonate anyone) and any other
token becomes its label as plain text; the 10,000-character limit applies after that.
"""

from __future__ import annotations

import re
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ProblemError
from app.models.user import User
from app.schemas.comments import (
    MAX_COMMENT_LENGTH,
    MAX_MENTIONS,
    MENTION_PATTERN,
    mention_token,
    mentioned_user_ids,
)
from app.schemas.common import FieldError
from app.services.sql import any_of

__all__ = ["TooManyMentionsProblem", "rewrite_mentions"]


class TooManyMentionsProblem(ProblemError):
    def __init__(self) -> None:
        super().__init__(
            422,
            "too_many_mentions",
            detail=f"Mention at most {MAX_MENTIONS} people in one comment.",
        )


async def rewrite_mentions(db: AsyncSession, body_md: str) -> tuple[str, list[UUID]]:
    """The body with every mention token rewritten, and the people it now mentions."""
    ids = mentioned_user_ids(body_md)
    if len(ids) > MAX_MENTIONS:
        raise TooManyMentionsProblem
    names: dict[UUID, str] = {}
    if ids:
        rows = await db.execute(
            select(User.id, User.display_name).where(
                any_of(User.id, ids), User.is_active, User.is_service_account.is_(False)
            )
        )
        names = dict(rows.all())

    def replace(match: re.Match[str]) -> str:
        user_id = UUID(match.group("user_id"))
        if user_id in names:
            return mention_token(user_id, names[user_id])
        return "@" + match.group("label")

    rewritten = MENTION_PATTERN.sub(replace, body_md)
    if len(rewritten) > MAX_COMMENT_LENGTH:
        raise ProblemError(
            422,
            "validation_error",
            detail="The comment is too long.",
            errors=[
                FieldError(
                    loc=["body", "body_md"],
                    msg=(
                        f"At most {MAX_COMMENT_LENGTH:,} characters (with mentions written "
                        "out in full)."
                    ),
                    type="string_too_long",
                )
            ],
        )
    return rewritten, [user_id for user_id in ids if user_id in names]
