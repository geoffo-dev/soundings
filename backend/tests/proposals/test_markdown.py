"""Proposal Markdown as the SPA renders it (contract-phase4 3.4, tests first): raw HTML
dropped, images as links, safe link targets, headings demoted through the parser,
bounded tables. Pure functions: no database."""

from __future__ import annotations

from html.parser import HTMLParser

import pytest

from app.proposals.markdown import (
    MAX_TABLE_CELLS,
    MAX_TABLE_ROWS,
    TableBudget,
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
@pytest.mark.parametrize(
    ("markdown", "html"),
    [
        (
            "[ok](https://example.com/a?b=1&c=2)",
            '<a href="https://example.com/a?b=1&amp;c=2">ok</a>',
        ),
        ("[web](http://example.com)", '<a href="http://example.com">web</a>'),
        ("[mail](mailto:jo@example.com)", '<a href="mailto:jo@example.com">mail</a>'),
        ("<https://auto.example>", '<a href="https://auto.example">https://auto.example</a>'),
        ("[js](javascript:alert(1))", "js"),
        ("[js](JaVaScRiPt:alert(1))", "js"),
        ("[tab](java\tscript:alert(1))", "[tab](java\tscript:alert(1))"),
        ("[file](file:///etc/passwd)", "file"),
        ("[data](data:text/html,<b>x</b>)", "data"),
        ("[relative](/ideas/CUST-1)", "relative"),
        ("[meta](http://169.254.169.254/)", '<a href="http://169.254.169.254/">meta</a>'),
        ("<javascript:alert(1)>", "javascript:alert(1)"),
    ],
)
def test_links_keep_only_http_https_and_mailto_targets(markdown: str, html: str) -> None:
    assert render_html(markdown) == f"<p>{html}</p>\n"


@pytest.mark.parametrize(
    ("markdown", "html"),
    [
        (
            "![Chart](https://example.com/c.png)",
            '<a class="image-link" href="https://example.com/c.png">Chart</a>',
        ),
        (
            "![](http://example.com/c.png)",
            '<a class="image-link" href="http://example.com/c.png">Image</a>',
        ),
        ("![Local](file:///etc/passwd)", "Local"),
        ("![Inline](data:image/png;base64,AAAA)", "Inline"),
        ("![Rel](c.png)", "Rel"),
        ("![](javascript:x)", ""),
        ("[![In a link](https://x/i.png)](https://y/)", '<a href="https://y/">In a link</a>'),
    ],
)
def test_images_are_never_images(markdown: str, html: str) -> None:
    assert render_html(markdown) == f"<p>{html}</p>\n"


def test_safe_href() -> None:
    assert safe_href("https://x") == "https://x"
    assert safe_href("MAILTO:a@b") == "MAILTO:a@b"
    for bad in ("javascript:x", "vbscript:x", "file:///x", "data:,x", "/rel", "x", "", "ftp://x"):
        assert safe_href(bad) is None


# --- Headings ------------------------------------------------------------------------
def test_headings_move_down_two_levels_capped_at_six() -> None:
    rendered = render_html("# One\n## Two\n### Three\n#### Four\n##### Five\n###### Six")
    assert rendered == (
        "<h3>One</h3>\n<h4>Two</h4>\n<h5>Three</h5>\n<h6>Four</h6>\n<h6>Five</h6>\n<h6>Six</h6>\n"
    )


def test_setext_headings_are_demoted_and_code_is_not() -> None:
    rendered = render_html("Setext\n===\n\nTwo\n---\n\n```\n# not a heading\n```")
    assert rendered == (
        "<h3>Setext</h3>\n<h4>Two</h4>\n<pre><code># not a heading\n</code></pre>\n"
    )


@pytest.mark.parametrize(
    ("source", "demoted"),
    [
        ("# One", "### One"),
        ("## Two ##", "#### Two ##"),
        ("#### Four", "###### Four"),
        ("###### Six", "###### Six"),
        ("   # Indented", "   ### Indented"),
        ("#\tTab", "###\tTab"),
        ("Setext\n===", "### Setext"),
        ("Setext two\n---", "#### Setext two"),
        ("Two\nlines\n===", "### Two lines"),
        ("Issue #\n---", "#### Issue \\#"),
        ("C#\n==", "### C#"),
        ("> ## Quoted", "> #### Quoted"),
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
    assert large.startswith('<pre class="table-source"><code>| h0 | h1 |')
    assert "<table>" not in large


def test_the_cell_budget_is_shared_by_the_document() -> None:
    budget = TableBudget()
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
