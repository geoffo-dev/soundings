"""Proposal Markdown as the SPA renders it (contract-phase4 3.4, tests first): raw HTML
dropped, images as links, safe link targets, headings demoted through the parser,
bounded tables, a bounded number of boxes per document and break opportunities in
long runs (what keeps WeasyPrint's time and memory bounded). Pure functions: no
database."""

from __future__ import annotations

import re
from html.parser import HTMLParser

import pytest

from app.proposals.markdown import (
    BREAK,
    MAX_BOXES,
    MAX_TABLE_CELLS,
    MAX_TABLE_ROWS,
    PIECE_LENGTH,
    RUN_LENGTH,
    TOO_LONG,
    RenderBudget,
    close_open_blocks,
    demote_headings,
    render_html,
    safe_href,
)

HTML_BLOCKS = [
    "<script>alert(1)</script>",
    '<img src="http://169.254.169.254/latest/meta-data/">',
    '<iframe src="https://evil.example/"></iframe>',
    '<link rel="stylesheet" href="https://evil.example/x.css">',
    "<style>body { background: url(https://evil.example/x.png) }</style>",
    '<div style="background:url(http://evil.example/)">styled</div>',
    "<!-- a comment -->",
]
INLINE_HTML = [
    '<object data="file:///etc/passwd"></object>',
    '<svg><image href="http://169.254.169.254/"/></svg>',
    '<a href="javascript:alert(1)">click</a>',
    '<img src="http://169.254.169.254/" onerror="alert(1)">',
    "<style>body { background: url(https://evil.example/x.png) }</style>",
]
ALLOWED_TAGS = {
    "p", "a", "em", "strong", "s", "code", "pre", "ul", "ol", "li", "blockquote", "hr",
    "br", "h3", "h4", "h5", "h6", "table", "thead", "tbody", "tr", "th", "td", "span",
}  # fmt: skip
ALLOWED_ATTRIBUTES = {"href", "class", "aria-label", "start"}


class _Elements(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: set[str] = set()
        self.attributes: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.add(tag)
        self.attributes.update(name for name, _ in attrs)
        if tag == "a":
            href = dict(attrs).get("href") or ""
            assert href.startswith(("http://", "https://", "mailto:")), href


def elements(html: str) -> _Elements:
    parser = _Elements()
    parser.feed(html)
    parser.close()
    return parser


# --- Raw HTML ------------------------------------------------------------------------
def test_inline_html_is_dropped_but_its_text_stays() -> None:
    assert render_html("a <b>x</b> c") == "<p>a x c</p>\n"
    assert render_html('<a href="javascript:alert(1)">click</a>') == "<p>click</p>\n"


@pytest.mark.parametrize("html", HTML_BLOCKS)
def test_raw_html_blocks_render_as_nothing(html: str) -> None:
    rendered = render_html(f"Before\n\n{html}\n\nAfter")

    assert rendered == "<p>Before</p>\n<p>After</p>\n"


@pytest.mark.parametrize("html", HTML_BLOCKS + INLINE_HTML)
def test_no_markup_ever_loads_anything(html: str) -> None:
    for text in (html, f"Inline {html} too, and ![pic](http://169.254.169.254/x.png)"):
        found = elements(render_html(text))
        assert found.tags <= ALLOWED_TAGS, found.tags
        assert found.attributes <= ALLOWED_ATTRIBUTES, found.attributes


def test_a_paragraph_of_nothing_but_html_leaves_no_empty_paragraph() -> None:
    rendered = render_html('Before\n\n<object data="file:///etc/passwd"></object>\n\nAfter')
    assert "<p></p>" not in rendered
    assert rendered.split() == ["<p>Before</p>", "<p>After</p>"]


def test_entities_stay_text() -> None:
    assert render_html("&#x3C;script&#x3E; &amp; &lt;") == "<p>&lt;script&gt; &amp; &lt;</p>\n"


# --- Links and images ----------------------------------------------------------------
def printed(url: str) -> str:
    """The URL printed after a link (``|``: a break opportunity)."""
    return f'<span class="link-url"> ({url})</span>'


@pytest.mark.parametrize(
    ("markdown", "html"),
    [
        (
            "[ok](https://example.com/a?b=1&c=2)",
            '<a href="https://example.com/a?b=1&amp;c=2">ok</a>'
            + printed("https://example.com/|a?|b=1&amp;|c=2"),
        ),
        (
            "[web](http://example.com)",
            '<a href="http://example.com">web</a>' + printed("http://example.com"),
        ),
        (
            "[mail](mailto:jo@example.com)",
            '<a href="mailto:jo@example.com">mail</a>' + printed("jo@example.com"),
        ),
        # Paper can't be clicked, but a link whose text is its URL needs nothing more.
        ("<https://auto.example>", '<a href="https://auto.example">https://auto.example</a>'),
        ("[https://x.io](https://x.io)", '<a href="https://x.io">https://x.io</a>'),
        ("[jo@x.io](mailto:jo@x.io)", '<a href="mailto:jo@x.io">jo@x.io</a>'),
        ("[js](javascript:alert(1))", "js"),
        ("[js](JaVaScRiPt:alert(1))", "js"),
        ("[tab](java\tscript:alert(1))", "[tab](java\tscript:alert(1))"),
        ("[file](file:///etc/passwd)", "file"),
        ("[data](data:text/html,<b>x</b>)", "data"),
        ("[relative](/ideas/CUST-1)", "relative"),
        (
            "[meta](http://169.254.169.254/)",
            '<a href="http://169.254.169.254/">meta</a>' + printed("http://169.254.169.254/|"),
        ),
        ("<javascript:alert(1)>", "javascript:alert(1)"),
    ],
)
def test_links_keep_only_http_https_and_mailto_targets(markdown: str, html: str) -> None:
    assert render_html(markdown).replace(BREAK, "|") == f"<p>{html}</p>\n"


def test_a_long_printed_url_wraps_and_is_escaped() -> None:
    url = "https://example.com/" + "a" * 70 + "?q=<b>&x=1"
    rendered = render_html(f"[spec]({url})")
    shown = rendered.split('class="link-url">', 1)[1]
    assert "<b>" not in shown  # escaped (markdown-it also percent-encodes it)
    assert shown.count(BREAK) >= 70 // RUN_LENGTH + 1  # the path's "/" and long runs


@pytest.mark.parametrize(
    ("markdown", "html"),
    [
        (
            "![Chart](https://example.com/c.png)",
            '<a class="image-link" href="https://example.com/c.png">Chart</a>'
            + printed("https://example.com/|c.png"),
        ),
        (
            "![](http://example.com/c.png)",
            '<a class="image-link" href="http://example.com/c.png">Image</a>'
            + printed("http://example.com/|c.png"),
        ),
        ("![Local](file:///etc/passwd)", "Local"),
        ("![Inline](data:image/png;base64,AAAA)", "Inline"),
        ("![Rel](c.png)", "Rel"),
        ("![](javascript:x)", ""),
        (
            "[![In a link](https://x/i.png)](https://y/)",
            '<a href="https://y/">In a link</a>' + printed("https://y/|"),
        ),
    ],
)
def test_images_are_never_images(markdown: str, html: str) -> None:
    assert render_html(markdown).replace(BREAK, "|") == f"<p>{html}</p>\n"


def test_safe_href() -> None:
    assert safe_href("https://x") == "https://x"
    assert safe_href("MAILTO:a@b") == "MAILTO:a@b"
    for bad in ("javascript:x", "vbscript:x", "file:///x", "data:,x", "/rel", "x", "", "ftp://x"):
        assert safe_href(bad) is None


# --- Headings ------------------------------------------------------------------------
def test_headings_move_down_one_level_below_the_sections_capped_at_six() -> None:
    """UX review M4: ``###`` is an h4 (one level down), never body-sized; ``#`` and
    ``##`` both sit just below the section titles (h2)."""
    rendered = render_html("# One\n## Two\n### Three\n#### Four\n##### Five\n###### Six")
    assert rendered == (
        "<h3>One</h3>\n<h3>Two</h3>\n<h4>Three</h4>\n<h5>Four</h5>\n<h6>Five</h6>\n<h6>Six</h6>\n"
    )


def test_setext_headings_are_demoted_and_code_is_not() -> None:
    rendered = render_html("Setext\n===\n\nTwo\n---\n\n```\n# not a heading\n```")
    assert rendered == (
        "<h3>Setext</h3>\n<h3>Two</h3>\n<pre><code># not a heading\n</code></pre>\n"
    )


@pytest.mark.parametrize(
    ("source", "demoted"),
    [
        ("# One", "### One"),
        ("## Two ##", "### Two ##"),
        ("### Three", "#### Three"),
        ("#### Four", "##### Four"),
        ("##### Five", "###### Five"),
        ("###### Six", "###### Six"),
        ("   # Indented", "   ### Indented"),
        ("#\tTab", "###\tTab"),
        ("Setext\n===", "### Setext"),
        ("Setext two\n---", "### Setext two"),
        ("Two\nlines\n===", "### Two lines"),
        ("Issue #\n---", "### Issue \\#"),
        ("C#\n==", "### C#"),
        ("> ## Quoted", "> ### Quoted"),
        ("- # In a list", "- ### In a list"),
        ("> Quoted setext\n> ===", "> ### Quoted setext"),
        ("```\n# code\n```", "```\n# code\n```"),
        ("~~~\n## code\n~~~", "~~~\n## code\n~~~"),
        ("    # indented code", "    # indented code"),
        ("####### seven", "####### seven"),
        ("#hashtag", "#hashtag"),
        ("text # not a heading", "text # not a heading"),
        ("<!--\n# in html\n-->", "<!--\n# in html\n-->"),
    ],
)
def test_demote_headings_rewrites_only_what_the_parser_calls_a_heading(
    source: str, demoted: str
) -> None:
    assert demote_headings(source) == demoted


def test_demote_headings_keeps_everything_else_verbatim() -> None:
    text = "    indented\n\nText  \nwith *spaces*   \n\n# Heading\n\n\n"
    assert demote_headings(text) == "    indented\n\nText  \nwith *spaces*   \n\n### Heading\n\n\n"


def test_windows_newlines_become_unix() -> None:
    assert demote_headings("# A\r\nb\rc") == "### A\nb\nc"


# --- Blocks left open ----------------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "closed"),
    [
        ("fine", "fine"),
        ("```\ncode", "```\ncode\n```"),
        ("````js\ncode\n```", "````js\ncode\n```\n````"),
        ("~~~\ncode", "~~~\ncode\n~~~"),
        ("<!-- open comment", "<!-- open comment\n-->"),
        ("<script>\nx", "<script>\nx\n</script>"),
        ("<PRE class=x>\nx", "<PRE class=x>\nx\n</pre>"),
        ("<?php\nx", "<?php\nx\n?>"),
        ("<![CDATA[\nx", "<![CDATA[\nx\n]]>"),
        ("<!DOCTYPE\nx", "<!DOCTYPE\nx\n>"),
        ("- ```\n  code", "- ```\n  code"),
    ],
)
def test_close_open_blocks(text: str, closed: str) -> None:
    assert close_open_blocks(text) == closed


# --- Tables --------------------------------------------------------------------------
def _table(rows: int, columns: int = 2) -> str:
    header = "| " + " | ".join(f"h{c}" for c in range(columns)) + " |"
    rule = "|" + "---|" * columns
    body = "\n".join(
        "| " + " | ".join(f"r{r}c{c}" for c in range(columns)) + " |" for r in range(rows)
    )
    return f"{header}\n{rule}\n{body}"


def test_tables_render_with_alignment_classes_not_styles() -> None:
    rendered = render_html("| a | b | c |\n|:--|:-:|--:|\n| 1 | 2 | 3 |")
    assert '<th class="align-left">a</th>' in rendered
    assert '<td class="align-center">2</td>' in rendered
    assert '<td class="align-right">3</td>' in rendered
    assert "style" not in rendered


def test_a_table_over_the_row_limit_prints_as_source() -> None:
    small = render_html(_table(MAX_TABLE_ROWS - 1))
    large = render_html(_table(MAX_TABLE_ROWS))  # + the header row

    assert small.startswith("<table>")
    assert large.startswith('<pre class="table-source"><code><span>| h0 | h1 |')
    assert "<table>" not in large


def test_the_cell_budget_is_shared_by_the_document() -> None:
    budget = RenderBudget()
    first = render_html(_table(99, 10), budget)  # 100 rows x 10 = 1,000 cells
    second = render_html(_table(99, 10), budget)  # 2,000 cells: still fits
    third = render_html(_table(1, 2), budget)  # one more cell is too many

    assert first.startswith("<table>")
    assert second.startswith("<table>")
    assert third.startswith('<pre class="table-source">')
    assert budget.cells == MAX_TABLE_CELLS - 2_000


def test_task_lists_get_boxes() -> None:
    rendered = render_html("- [x] Done\n- [ ] Todo\n- Plain [x] text")
    assert rendered == (
        '<ul>\n<li class="task-item">'
        '<span class="task task-done" aria-label="Done"></span>Done</li>\n'
        '<li class="task-item"><span class="task" aria-label="Not done"></span>Todo</li>\n'
        "<li>Plain [x] text</li>\n</ul>\n"
    )


def test_deep_nesting_is_bounded() -> None:
    rendered = render_html(">" * 5_000 + " deep\n\n" + "- " * 5_000 + "x")
    assert rendered.count("<blockquote>") <= 20


def test_code_has_no_language_class() -> None:
    rendered = render_html('```js" onload="x\ncode\n```')
    assert rendered == "<pre><code>code\n</code></pre>\n"


# --- Bounded layout (WeasyPrint's cost grows with boxes and unbreakable runs) ---------
class _Balanced(HTMLParser):
    """Checks that every element is closed in order and counts start tags."""

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[str] = []
        self.counts: dict[str, int] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.counts[tag] = self.counts.get(tag, 0) + 1
        if tag not in ("br", "hr"):
            self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        assert self.stack, tag
        assert self.stack[-1] == tag, (self.stack, tag)
        self.stack.pop()


def balanced(html: str) -> dict[str, int]:
    parser = _Balanced()
    parser.feed(html)
    parser.close()
    assert parser.stack == [], parser.stack
    return parser.counts


NOTE = f'<p class="too-long">{TOO_LONG}</p>'


@pytest.mark.parametrize(
    ("markdown", "tag"),
    [
        ("- a\n" * 6_000, "li"),  # list items (each with its marker box)
        ("1. a\n\n" * 3_000, "li"),
        ("a\n\n" * 6_000, "p"),
        ("# a\n" * 6_000, "h3"),
        ("a\\\n" * 6_000, "br"),  # hard line breaks, in one paragraph
        ("*a*," * 6_000, "em"),  # inline elements, in one paragraph
        ("a*b*" * 8_000, "em"),
        ("`a`," * 6_000, "code"),
        ("\n\n".join(["[a](https://x.io)" * 1_000] * 3), "a"),  # links weigh 3
        ("---\n" * 6_000, "hr"),
    ],
    ids=[
        "list",
        "loose-list",
        "paragraphs",
        "headings",
        "hard-breaks",
        "emphasis",
        "intraword-emphasis",
        "code",
        "links",
        "rules",
    ],
)
def test_a_document_renders_a_bounded_number_of_boxes(markdown: str, tag: str) -> None:
    rendered = render_html(markdown)

    counts = balanced(rendered)
    assert 0 < counts.get(tag, 0) - (tag == "p") <= MAX_BOXES  # the note is a <p>
    assert rendered.endswith(NOTE + "\n")
    assert rendered.count(NOTE) == 1


def test_code_lines_count_as_boxes_and_long_code_is_cut() -> None:
    code = "```\n" + "x\n" * (MAX_BOXES + 10) + "```"

    rendered = render_html(f"Before\n\n{code}\n\nAfter")

    text = re.sub("</?span>", "", rendered)  # long text prints in pieces
    assert text.startswith("<p>Before</p>\n<pre><code>x\n")
    assert text.endswith(f"x\n</code></pre>\n{NOTE}\n")
    assert text.count("x\n") == MAX_BOXES - 1  # the paragraph took one box
    assert "After" not in text


def test_a_long_paragraph_is_cut_inside_and_its_elements_closed() -> None:
    budget = RenderBudget(boxes=7)  # the paragraph, then 2 links of 3 (with their URLs)

    rendered = render_html(
        "Read [one](https://a.io) and [two **b**](https://b.io) and [3](https://c.io)", budget
    )

    assert rendered == (
        f'<p>Read <a href="https://a.io">one</a>{printed("https://a.io")} and '
        f'<a href="https://b.io">two </a>{printed("https://b.io")}</p>\n{NOTE}\n'
    )
    balanced(rendered)


def test_ordinary_documents_are_far_from_the_budget() -> None:
    """Long prose in every section (15,000 characters, bold and a link per paragraph)
    plus a 50-item list with bold and code in each item use under half the budget."""
    paragraph = (
        "We would let customers **refund** orders themselves. "
        + "A plain sentence about the plan and what it changes for everyone. " * 10
        + "See [the spec](https://example.com)."
    )
    prose = "\n\n".join([paragraph] * 40)[:20_000]
    items = "\n".join(f"- Step {n}: do **this** and `that`" for n in range(50))
    budget = RenderBudget()
    for _ in range(8):
        rendered = render_html(f"{prose[:15_000]}\n\n{items}", budget)
        assert TOO_LONG not in rendered
    assert budget.boxes > MAX_BOXES // 2


def test_the_box_budget_is_shared_by_the_document_and_only_cuts_what_is_over() -> None:
    budget = RenderBudget()
    first = render_html("- a\n" * (MAX_BOXES // 2 - 10), budget)  # 2 boxes per item
    second = render_html("Short.\n\n" + "- b\n" * 100 + "\nAfter the list.", budget)
    third = render_html("Still room for this.", budget)

    assert TOO_LONG not in first
    assert second.startswith("<p>Short.</p>\n<ul>\n<li>b</li>\n")
    assert second.endswith(f"</ul>\n{NOTE}\n")  # the list is cut, the rest is dropped
    assert "After the list" not in second
    assert third == "<p>Still room for this.</p>\n"


def test_a_cut_leaves_no_empty_blocks_behind() -> None:
    budget = RenderBudget(boxes=7)  # the list, three items of 2: nothing left for "bold"

    rendered = render_html("- one\n- two\n- **bold** three\n- four", budget)

    assert rendered == f"<ul>\n<li>one</li>\n<li>two</li>\n</ul>\n{NOTE}\n"


def test_long_runs_get_a_break_opportunity_every_run_length_characters() -> None:
    rendered = render_html("a" * (RUN_LENGTH * 3 + 5))

    assert rendered == "<p>" + ("a" * RUN_LENGTH + BREAK) * 3 + "aaaaa</p>\n"


def test_words_shorter_than_the_run_length_are_untouched() -> None:
    text = " ".join(["internationalisation"] * 50) + " " + "x" * (RUN_LENGTH - 1)

    assert BREAK not in render_html(text)
    assert BREAK not in render_html(f"```\n{text}\n```")


def test_runs_continue_across_inline_elements() -> None:
    rendered = render_html("ab*cd*" * 20)  # 80 letters, no break opportunity

    assert rendered.count(BREAK) == 80 // RUN_LENGTH
    assert rendered.replace(BREAK, "") == "<p>" + "ab<em>cd</em>" * 20 + "</p>\n"


def test_long_runs_in_code_links_and_tables_get_break_opportunities() -> None:
    long = "x" * (RUN_LENGTH + 1)
    for markdown in (
        f"`{long}`",
        f"```\n{long}\n```",
        f"[{long}](https://example.com/{long})",
        f"| h |\n|---|\n| {long} |",
    ):
        rendered = render_html(markdown).split('<span class="link-url">')[0]
        assert rendered.count(BREAK) == 1, markdown
    link = render_html(f"[{long}](https://example.com/{long})")
    assert f'href="https://example.com/{long}"' in link  # targets are never changed


def test_breaks_never_split_a_character_sequence() -> None:
    accented = "e\u0301" * RUN_LENGTH  # e + combining acute
    family = "\U0001f468\u200d\U0001f469\u200d\U0001f467" * 20  # emoji ZWJ sequences
    flags = "\U0001f1ec\U0001f1e7" * 40  # regional indicator pairs

    for text in (accented, family, flags):
        rendered = render_html(text)
        assert BREAK in rendered
        assert BREAK + "\u0301" not in rendered
        assert BREAK + "\u200d" not in rendered
        assert "\u200d" + BREAK not in rendered
    chunks = render_html(flags)[3:-5].split(BREAK)
    assert all(len(chunk) % 2 == 0 for chunk in chunks)


def test_spaces_and_line_breaks_end_a_run_but_no_break_spaces_do_not() -> None:
    almost = "x" * (RUN_LENGTH - 1)

    assert BREAK not in render_html(f"{almost} {almost}\n{almost}\\\n{almost}")
    assert BREAK in render_html(f"{almost}\u00a0{almost}")


@pytest.mark.parametrize(
    "wrap",
    ["{}", "`{}`", "```\n{}\n```", "![{}](https://x.io/i.png)", "![{}](i.png)"],
    ids=["text", "code", "fence", "image-link", "image-text"],
)
def test_long_text_prints_in_pieces_that_end_at_a_break_opportunity(wrap: str) -> None:
    text = "i" * 3_100

    rendered = render_html(wrap.format(text))

    pieces = re.findall(r"<span>(.*?)</span>", rendered, flags=re.DOTALL)
    assert len(pieces) == 4
    assert all(PIECE_LENGTH <= len(piece) <= PIECE_LENGTH + RUN_LENGTH for piece in pieces[:-1])
    assert all(piece.endswith((BREAK, "\n")) for piece in pieces[:-1])
    assert "".join(pieces).replace(BREAK, "").strip() == text
    assert "<span>" not in render_html(wrap.format("i" * (PIECE_LENGTH - 40)))
