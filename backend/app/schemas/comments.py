"""Comment requests (comments are returned as ``CommentActivity`` feed items)."""

from __future__ import annotations

from pydantic import Field

from app.schemas.base import RequestModel

__all__ = ["CommentCreate", "CommentUpdate"]

MAX_COMMENT_LENGTH = 10_000


class CommentCreate(RequestModel):
    body_md: str = Field(min_length=1, max_length=MAX_COMMENT_LENGTH, description="Markdown.")


class CommentUpdate(RequestModel):
    body_md: str = Field(min_length=1, max_length=MAX_COMMENT_LENGTH, description="Markdown.")
