"""Comment excerpts (inbox, emails, digests): what they show, and that no comment can
make one slow (review H1: quadratic patterns stalled the event loop for seconds)."""

from __future__ import annotations

import time
from uuid import UUID

import pytest

from app.notifications.excerpt import EXCERPT_LENGTH, SOURCE_LENGTH, comment_excerpt

ADA = UUID("00000000-0000-4000-8000-000000000001")

# 10,000 characters each (the comment limit): patterns that made the old regexes
# backtrack quadratically, and their relatives.
CRAFTED = {
    "star-space": "*x " * 3334,
    "underscore-space": "_x " * 3334,
    "backtick-space": "`x " * 3334,
    "tilde-space": "~~x " * 2500,
    "mixed": "*x _x `x ~~x " * 800,
    "open-brackets": "[" * 10_000,
    "open-images": "![" * 5_000,
    "open-links": "[a](" * 2_500,
    "open-tags": "<a" * 5_000,
    "open-autolinks": "<http:" * 1_667,
    "blank-lines": "\n" * 9_999 + "x",
    "rule-lines": "-\n" * 4_999 + "x",
    "open-mentions": "@[" * 5_000,
    "stars": "*" * 10_000,
    "intraword-stars": "a*" * 5_000,
    "strong-runs": "**a " * 2_500,
    "underscores": "_" * 10_000,
    "close-tags": "</a " * 2_500,
    "fences": "```" * 3_333,
    "headings": "#\n" * 5_000,
    "one-long-label": "[" + "a" * 9_999,
    "labels": "[a]" * 3_333,
}


@pytest.mark.parametrize("body", list(CRAFTED.values()), ids=list(CRAFTED))
def test_no_comment_makes_an_excerpt_slow(body: str) -> None:
    body = body[:10_000]
    comment_excerpt(body)  # warm the regex cache
    started = time.perf_counter()
    for _ in range(5):
        excerpt = comment_excerpt(body)
    elapsed = (time.perf_counter() - started) / 5

    # About 1 ms here; the old patterns took 0.2-1.1 s on several of these.
    assert elapsed < 0.05, f"{elapsed * 1000:.1f} ms"
    assert len(excerpt) <= EXCERPT_LENGTH


def test_a_page_of_crafted_comments_is_fast() -> None:
    """An inbox page of 200 crafted comments (the reviewer's 20 took 23 s)."""
    body = ("*x " * 3334)[:10_000]
    started = time.perf_counter()
    for _ in range(200):
        comment_excerpt(body)
    assert time.perf_counter() - started < 2.0


@pytest.mark.parametrize(
    ("body", "excerpt"),
    [
        (
            f"**Great** idea, see [the doc](https://x.test) @[Ada](user:{ADA})",
            "Great idea, see the doc @Ada",
        ),
        (
            "snake_case stays, 2 * 3 stays, a*b*c stays",
            "snake_case stays, 2 * 3 stays, a*b*c stays",
        ),
        ("**_both_** `code` ~~gone~~ but ~5 min stays", "both code gone but ~5 min stays"),
        (
            "# Title\n> quote\n- item\n- [x] done\n1. one\n\n---\n<b>bold</b> ![alt](i.png) "
            "<https://x.test/a>",
            "Title quote item done one bold alt https://x.test/a",
        ),
        ("```\ncode block\n```\nafter", "code block after"),
        ("  lots   of\n\n\nspace  ", "lots of space"),
    ],
)
def test_markdown_becomes_plain_text(body: str, excerpt: str) -> None:
    assert comment_excerpt(body) == excerpt


def test_long_comments_are_shortened_at_a_word() -> None:
    excerpt = comment_excerpt("word " * 100)

    assert len(excerpt) <= EXCERPT_LENGTH
    assert excerpt.endswith("word…")


def test_only_the_start_of_a_long_comment_is_read_and_tokens_are_not_cut() -> None:
    # A mention token straddling the source limit is dropped whole, not shown half.
    filler = "x" * (SOURCE_LENGTH - 20) + " "
    body = filler + f"@[Ada](user:{ADA}) and more"

    excerpt = comment_excerpt(body, limit=10_000)

    assert "user:" not in excerpt
    assert "@[" not in excerpt
