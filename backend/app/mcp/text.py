"""Tool results carry no invisible text (security review M4).

People write ideas, comments, evaluations and proposals, some of them anonymously
through the public form, and an agent reads them through MCP. Characters that show
nothing in the app and in moderation can still be read by a model: Unicode **tag
characters** (U+E0000-U+E007F spell out ASCII invisibly: "ignore previous
instructions" hidden after a harmless summary), variation selectors past the emoji ones
(bytes can be encoded in them), zero-width and other format characters, bidi controls
that make a line read differently from its logical order, and control characters.

:func:`visible_text` removes them; :func:`visible_data` applies it to every string of a
result, so every people-written field (and anything added later) is covered at the one
place results are built (:func:`app.mcp.dispatcher.success_result`). Kept: tab, line
feed and carriage return; ZWNJ and ZWJ (U+200C, U+200D), which scripts such as Persian
and Hindi and emoji sequences need; VS15 and VS16 (U+FE0E, U+FE0F, text or emoji
presentation). Emoji flags of subdivisions (England, Scotland, Wales: a black flag plus
tag characters) lose their tags and show as a black flag: an accepted cost.

The set is every ``Cc``, ``Cf`` and ``Cs`` character of Unicode 15 but those kept, the
variation selectors U+FE00-U+FE0D and U+E0100-U+E01EF, the unassigned rest of the tag
block, the combining grapheme joiner and the Hangul fillers (blank letters);
``tests/mcp/test_hidden_text.py`` checks it against :mod:`unicodedata`.

**Agents' text, too** (Phase 6 review M2): what an AI agent writes (a research note, a
suggested section, its evaluation's comments) is shown to people as untrusted Markdown,
where a right-to-left override or a zero-width space could make a link's text or its
host read as something else. :func:`agent_text_arguments` removes the same characters
from those fields of an agent's write before they are validated again and stored.
Source titles are one-line names, which refuse them (``SingleLine``), and source URLs
refuse them too; tag characters are refused for everyone by the request models.
"""

from __future__ import annotations

import re
from typing import Any, Final

__all__ = ["AGENT_TEXT_FIELDS", "HIDDEN", "agent_text_arguments", "visible_data", "visible_text"]

HIDDEN: Final = re.compile(
    "["
    "\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f"  # controls (Cc) but tab, LF and CR
    "\u00ad"  # soft hyphen
    "\u034f"  # combining grapheme joiner
    "\u0600-\u0605\u061c\u06dd\u070f\u0890\u0891\u08e2"  # Arabic and Syriac format marks
    "\u115f\u1160\u3164\uffa0"  # Hangul fillers: letters that show as nothing
    "\u180e"  # Mongolian vowel separator
    "\u200b\u200e\u200f"  # zero-width space, LRM, RLM
    "\u202a-\u202e"  # bidi embeddings and overrides
    "\u2060-\u2064\u2066-\u206f"  # word joiner, invisible operators, bidi isolates, ...
    "\ufe00-\ufe0d"  # variation selectors 1-14 (VS15/VS16 stay: emoji presentation)
    "\ufeff"  # zero-width no-break space (byte order mark)
    "\ufff9-\ufffb"  # interlinear annotation
    "\U000110bd\U000110cd"  # Kaithi number signs
    "\U00013430-\U0001343f"  # Egyptian hieroglyph format controls
    "\U0001bca0-\U0001bca3"  # shorthand format controls
    "\U0001d173-\U0001d17a"  # musical symbol format controls
    "\U000e0000-\U000e007f"  # the whole tag block
    "\U000e0100-\U000e01ef"  # variation selectors 17-256
    "\ud800-\udfff"  # lone surrogates
    "]+"
)
"""Every character :func:`visible_text` removes."""


def visible_text(text: str) -> str:
    """``text`` without the characters in :data:`HIDDEN`."""
    return HIDDEN.sub("", text)


AGENT_TEXT_FIELDS: Final = ("body_md", "comment")
"""The free-text arguments of the write tools an agent may call (and ``scores[].comment``)."""


def agent_text_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    """An agent's write arguments with :data:`HIDDEN` removed from its Markdown and
    comments (:data:`AGENT_TEXT_FIELDS`, and each score's ``comment``); everything else as
    sent (identifiers and URLs are validated as they are)."""
    cleaned = dict(arguments)
    for name in AGENT_TEXT_FIELDS:
        if isinstance(cleaned.get(name), str):
            cleaned[name] = visible_text(cleaned[name])
    scores = cleaned.get("scores")
    if isinstance(scores, list):
        cleaned["scores"] = [
            {**score, "comment": visible_text(score["comment"])}
            if isinstance(score, dict) and isinstance(score.get("comment"), str)
            else score
            for score in scores
        ]
    return cleaned


def visible_data(value: Any) -> Any:
    """``value`` (JSON data: dicts, lists, strings, numbers, booleans, null) with every
    string, keys included, passed through :func:`visible_text`."""
    if isinstance(value, str):
        return visible_text(value)
    if isinstance(value, dict):
        return {visible_text(str(key)): visible_data(item) for key, item in value.items()}
    if isinstance(value, list):
        return [visible_data(item) for item in value]
    return value
