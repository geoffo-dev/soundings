"""Plain-text excerpts of comments for the inbox, emails and digests.

Comments are Markdown; excerpts are plain text everyone who can view the idea may
read (the same text the feed shows): Markdown syntax removed, @mention tokens shown as
``@Name``, whitespace collapsed, at most :data:`EXCERPT_LENGTH` characters. Never
rendered as HTML or Markdown anywhere (emails escape it).
"""

from __future__ import annotations

import re
from typing import Final

from app.schemas.comments import MENTION_PATTERN

__all__ = ["EXCERPT_LENGTH", "comment_excerpt", "mentions_as_names", "shorten"]

EXCERPT_LENGTH: Final = 200

_FENCE = re.compile(r"^\s*(```|~~~).*$", re.MULTILINE)
_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_AUTOLINK = re.compile(r"<((?:https?|mailto):[^>\s]+)>")
_LINE_PREFIX = re.compile(
    r"^\s{0,3}(?:#{1,6}\s+|>\s?|[-*+]\s+(?:\[[ xX]\]\s+)?|\d{1,9}[.)]\s+)", re.MULTILINE
)
_RULE = re.compile(r"^\s{0,3}(?:[-*_]\s*){3,}$", re.MULTILINE)
_EMPHASIS = re.compile(r"(\*\*|__|\*|_|~~|`)(?=\S)(.+?)(?<=\S)\1")
_HTML_TAG = re.compile(r"</?[A-Za-z][^>]*>")
_SPACE = re.compile(r"\s+")


def mentions_as_names(text: str) -> str:
    """``@[Ada Lovelace](user:<id>)`` -> ``@Ada Lovelace``."""
    return MENTION_PATTERN.sub(lambda match: "@" + match.group("label"), text)


def shorten(text: str, limit: int) -> str:
    """At most ``limit`` characters, cut at a word boundary where possible, with "…"."""
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    space = cut.rfind(" ")
    if space >= limit // 2:
        cut = cut[:space]
    return cut.rstrip(" ,.;:-") + "…"


def comment_excerpt(body_md: str, limit: int = EXCERPT_LENGTH) -> str:
    """Plain text of a comment, mentions as ``@Name``, at most ``limit`` characters."""
    text = mentions_as_names(body_md)
    text = _FENCE.sub(" ", text)
    text = _IMAGE.sub(lambda match: match.group(1), text)
    text = _LINK.sub(lambda match: match.group(1), text)
    text = _AUTOLINK.sub(lambda match: match.group(1), text)
    text = _RULE.sub(" ", text)
    text = _LINE_PREFIX.sub("", text)
    for _ in range(3):  # nested emphasis: **_x_**
        text = _EMPHASIS.sub(lambda match: match.group(2), text)
    text = _HTML_TAG.sub("", text)
    text = _SPACE.sub(" ", text).strip()
    return shorten(text, limit)
