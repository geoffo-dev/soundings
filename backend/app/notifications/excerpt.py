"""Plain-text excerpts of comments for the inbox, emails and digests.

Comments are Markdown; excerpts are plain text everyone who can view the idea may
read (the same text the feed shows): Markdown syntax removed, @mention tokens shown as
``@Name``, whitespace collapsed, at most :data:`EXCERPT_LENGTH` characters. Never
rendered as HTML or Markdown anywhere (emails escape it).

Excerpts are built on request (an inbox page builds up to 200), so they must stay
cheap whatever a comment contains: only the first :data:`SOURCE_LENGTH` characters
are read, and every pattern below runs in linear time (bounded repeats over character
classes that stop at the next opening delimiter, no lazy ``.+?`` pairing), so a
crafted comment can't make one take more than about a millisecond.
"""

from __future__ import annotations

import re
from typing import Final

from app.schemas.comments import MENTION_PATTERN

__all__ = ["EXCERPT_LENGTH", "SOURCE_LENGTH", "comment_excerpt", "mentions_as_names", "shorten"]

EXCERPT_LENGTH: Final = 200
SOURCE_LENGTH: Final = 2_000
"""Characters of a comment an excerpt reads (ten excerpts' worth: enough for Markdown
syntax, link targets and mention tokens that are removed)."""

_FENCE = re.compile(r"^[ \t]*(?:```|~~~)[^\n]*$", re.MULTILINE)
_IMAGE = re.compile(r"!\[([^\[\]\n]{0,200})\]\([^\s()]{0,500}\)")
_LINK = re.compile(r"\[([^\[\]\n]{1,200})\]\([^\s()]{0,500}\)")
_AUTOLINK = re.compile(r"<((?:https?|mailto):[^<>\s]{1,500})>")
_LINE_PREFIX = re.compile(
    r"^[ \t]{0,3}(?:#{1,6}[ \t]+|>[ \t]?|[-*+][ \t]+(?:\[[ xX]\][ \t]+)?|\d{1,9}[.)][ \t]+)",
    re.MULTILINE,
)
_RULE = re.compile(r"^[ \t]{0,3}(?:[-*_][ \t]*){3,}$", re.MULTILINE)
_DELIMITER = r"(?:\*+|_+|~~+|`+)"
# Emphasis, strikethrough and code delimiters where they open (not after a word
# character, before a non-space) or close (after a non-space, not before a word
# character) a span: "**bold**", "_it_", "`code`" lose them; "snake_case", "2 * 3" and
# "a*b" keep theirs. Unpaired ones are removed too (cheaper than pairing them).
_EMPHASIS = re.compile(rf"(?<!\w){_DELIMITER}(?=\S)|(?<=\S){_DELIMITER}(?!\w)")
_HTML_TAG = re.compile(r"</?[A-Za-z][^<>\n]{0,200}>")
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


def _source(body_md: str) -> str:
    """The first :data:`SOURCE_LENGTH` characters, cut after whitespace where possible
    (so a link or mention token isn't cut in half)."""
    if len(body_md) <= SOURCE_LENGTH:
        return body_md
    cut = body_md[:SOURCE_LENGTH]
    space = max(cut.rfind(" "), cut.rfind("\n"))
    return cut[:space] if space >= SOURCE_LENGTH // 2 else cut


def comment_excerpt(body_md: str, limit: int = EXCERPT_LENGTH) -> str:
    """Plain text of a comment, mentions as ``@Name``, at most ``limit`` characters."""
    text = mentions_as_names(_source(body_md))
    text = _FENCE.sub(" ", text)
    text = _IMAGE.sub(lambda match: match.group(1), text)
    text = _LINK.sub(lambda match: match.group(1), text)
    text = _AUTOLINK.sub(lambda match: match.group(1), text)
    text = _RULE.sub(" ", text)
    text = _LINE_PREFIX.sub("", text)
    text = _EMPHASIS.sub("", text)
    text = _HTML_TAG.sub("", text)
    text = _SPACE.sub(" ", text).strip()
    return shorten(text, limit)
