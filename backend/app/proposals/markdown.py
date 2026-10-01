"""Proposal Markdown, read the way the SPA reads it (``components/ui/markdown.tsx``).

CommonMark plus GFM tables and strikethrough (markdown-it-py, ``maxNesting`` 20), so
the editor's preview is what the exports show (docs/api/contract-phase4.md 3.4):

* **raw HTML is dropped**: ``html_block`` and ``html_inline`` render as nothing, as
  react-markdown's ``skipHtml`` does (``a <b>x</b> c`` prints "a x c");
* **links** keep their target only for absolute ``http``, ``https`` and ``mailto``
  URLs; any other link is its plain label;
* **an image is never an image**: ``![alt](url)`` is a link labelled with its alt text
  (or "Image") when ``url`` is ``http(s)``, else the plain alt text. Nothing here ever
  produces ``<img>``, ``<link>``, ``<object>``, ``style`` or CSS ``url()``;
* **headings move down two levels** (``#`` -> ``h3``, never past ``h6``): the section
  titles are the ``h2``. :func:`demote_headings` does the same to the Markdown source,
  found through the parser's tokens (setext headings too, never a ``#`` line inside a
  code fence);
* **tables are bounded**: per document at most :data:`MAX_TABLE_CELLS` cells and
  :data:`MAX_TABLE_ROWS` rows per table render as tables (large tables are what makes
  WeasyPrint slow); any other table prints as its Markdown source in a code block.

Pure functions, no I/O: the PDF child process renders with them.
"""

from __future__ import annotations

import re
from collections.abc import MutableMapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from markdown_it import MarkdownIt
from markdown_it.common.utils import escapeHtml
from markdown_it.renderer import RendererHTML
from markdown_it.token import Token
from markdown_it.utils import OptionsDict

__all__ = [
    "LINK_SCHEMES",
    "MAX_NESTING",
    "MAX_TABLE_CELLS",
    "MAX_TABLE_ROWS",
    "TableBudget",
    "close_open_blocks",
    "demote_headings",
    "normalise_newlines",
    "render_html",
    "safe_href",
]

MAX_NESTING: Final = 20
MAX_TABLE_CELLS: Final = 2_000
"""Table cells (header cells included) rendered as tables per document."""
MAX_TABLE_ROWS: Final = 200
"""Rows (the header row included) of one table rendered as a table."""
HEADING_SHIFT: Final = 2
LINK_SCHEMES: Final = frozenset({"http", "https", "mailto"})
_WEB_SCHEMES: Final = frozenset({"http", "https"})
_SCHEME: Final = re.compile(r"([A-Za-z][A-Za-z0-9+.\-]*):")
_TASK: Final = re.compile(r"\[([ xX])\][ \t]")
_CONTAINER_PREFIX: Final = re.compile(r"[ \t>*+\-0-9.)]*")
_CLOSING_SEQUENCE: Final = re.compile(r"(?:^|[ \t])#+$")
_ALIGN: Final = {
    "text-align:left": "left",
    "text-align:center": "center",
    "text-align:right": "right",
}

Env = MutableMapping[str, Any]


def _scheme(url: str) -> str | None:
    match = _SCHEME.match(url)
    return match[1].lower() if match else None


def safe_href(url: str) -> str | None:
    """``url`` if it is an absolute ``http``, ``https`` or ``mailto`` URL, else ``None``.

    markdown-it has already percent-encoded it, so control characters and spaces can't
    hide another scheme (``java%09script:`` has no scheme at all)."""
    return url if _scheme(url) in LINK_SCHEMES else None


def normalise_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


# --- Parsing ---------------------------------------------------------------------------
def _parser() -> MarkdownIt:
    md = MarkdownIt(
        "commonmark",
        # html: parse raw HTML into html_* tokens, so the renderer can drop them (with
        # html off, markdown-it would print the tags as text instead).
        {"html": True, "maxNesting": MAX_NESTING, "xhtmlOut": False, "linkify": False},
    )
    md.enable(["table", "strikethrough"])
    # Keep every link and image a token; the renderer decides what each may become.
    md.validateLink = lambda url: True  # type: ignore[method-assign]
    for rule in ("html_block", "html_inline"):
        md.add_render_rule(rule, _nothing)
    md.add_render_rule("link_open", _link_open)
    md.add_render_rule("link_close", _link_close)
    md.add_render_rule("image", _image)
    md.add_render_rule("heading_open", _heading)
    md.add_render_rule("heading_close", _heading)
    md.add_render_rule("fence", _code_block)
    md.add_render_rule("code_block", _code_block)
    md.add_render_rule("th_open", _cell_open)
    md.add_render_rule("td_open", _cell_open)
    md.add_render_rule("table_source", _table_source)
    md.add_render_rule("task_box", _task_box)
    return md


# Render rules: (renderer, tokens, idx, options, env) -> HTML.
def _nothing(
    self: RendererHTML, tokens: Sequence[Token], idx: int, options: OptionsDict, env: Env
) -> str:
    return ""


def _link_open(
    self: RendererHTML, tokens: Sequence[Token], idx: int, options: OptionsDict, env: Env
) -> str:
    href = safe_href(str(tokens[idx].attrGet("href") or ""))
    env.setdefault("_links", []).append(href is not None)
    return "" if href is None else f'<a href="{escapeHtml(href)}">'


def _link_close(
    self: RendererHTML, tokens: Sequence[Token], idx: int, options: OptionsDict, env: Env
) -> str:
    links: list[bool] = env.get("_links") or [False]
    return "</a>" if links.pop() else ""


def _image(
    self: RendererHTML, tokens: Sequence[Token], idx: int, options: OptionsDict, env: Env
) -> str:
    token = tokens[idx]
    alt = self.renderInlineAsText(token.children or [], options, env)
    src = str(token.attrGet("src") or "")
    in_link = bool(env.get("_links")) and env["_links"][-1]
    if _scheme(src) in _WEB_SCHEMES and not in_link:
        return f'<a class="image-link" href="{escapeHtml(src)}">{escapeHtml(alt or "Image")}</a>'
    return escapeHtml(alt)


def _heading(
    self: RendererHTML, tokens: Sequence[Token], idx: int, options: OptionsDict, env: Env
) -> str:
    token = tokens[idx]
    level = min(int(token.tag[1:]) + HEADING_SHIFT, 6)
    return f"<h{level}>" if token.nesting == 1 else f"</h{level}>\n"


def _code_block(
    self: RendererHTML, tokens: Sequence[Token], idx: int, options: OptionsDict, env: Env
) -> str:
    # No language class: the info string is the writer's text, not ours to reuse.
    return f"<pre><code>{escapeHtml(tokens[idx].content)}</code></pre>\n"


def _cell_open(
    self: RendererHTML, tokens: Sequence[Token], idx: int, options: OptionsDict, env: Env
) -> str:
    # markdown-it writes alignment as a style attribute; a class keeps styles ours.
    token = tokens[idx]
    align = _ALIGN.get(str(token.attrGet("style") or ""))
    return f'<{token.tag} class="align-{align}">' if align else f"<{token.tag}>"


def _table_source(
    self: RendererHTML, tokens: Sequence[Token], idx: int, options: OptionsDict, env: Env
) -> str:
    return f'<pre class="table-source"><code>{escapeHtml(tokens[idx].content)}</code></pre>\n'


def _task_box(
    self: RendererHTML, tokens: Sequence[Token], idx: int, options: OptionsDict, env: Env
) -> str:
    done = bool(tokens[idx].meta.get("checked"))
    label = "Done" if done else "Not done"
    return f'<span class="task{" task-done" if done else ""}" aria-label="{label}"></span>'


_md: Final = _parser()


@dataclass(slots=True)
class TableBudget:
    """Table cells a document may still render as tables (shared by its sections)."""

    cells: int = MAX_TABLE_CELLS

    def take(self, cells: int) -> bool:
        if cells > self.cells:
            return False
        self.cells -= cells
        return True


def _closing(tokens: Sequence[Token], start: int, close_type: str) -> int:
    level = tokens[start].level
    for index in range(start + 1, len(tokens)):
        if tokens[index].type == close_type and tokens[index].level == level:
            return index
    return len(tokens) - 1  # pragma: no cover - markdown-it always closes blocks


def _bound_tables(tokens: list[Token], lines: Sequence[str], budget: TableBudget) -> list[Token]:
    """Replace each table over the limits by its Markdown source."""
    result: list[Token] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.type != "table_open":
            result.append(token)
            index += 1
            continue
        end = _closing(tokens, index, "table_close")
        table = tokens[index : end + 1]
        rows = sum(1 for item in table if item.type == "tr_open")
        cells = sum(1 for item in table if item.type in ("th_open", "td_open"))
        if rows <= MAX_TABLE_ROWS and budget.take(cells):
            result.extend(table)
        else:
            first, last = token.map or (0, 0)
            source = Token("table_source", "pre", 0, block=True, level=token.level)
            source.content = "\n".join(lines[first:last]).rstrip("\n") + "\n"
            result.append(source)
        index = end + 1
    return result


def _mark_tasks(tokens: Sequence[Token]) -> None:
    """GFM task list items (``- [x] Done``) get a box instead of the brackets."""
    for index in range(2, len(tokens)):
        token = tokens[index]
        if (
            token.type != "inline"
            or tokens[index - 1].type != "paragraph_open"
            or tokens[index - 2].type != "list_item_open"
            or not token.children
            or token.children[0].type != "text"
        ):
            continue
        first = token.children[0]
        match = _TASK.match(first.content)
        if match is None:
            continue
        first.content = first.content[match.end() :]
        box = Token("task_box", "span", 0, meta={"checked": match[1] != " "})
        token.children.insert(0, box)
        tokens[index - 2].attrSet("class", "task-item")


def _hide_html_only_paragraphs(tokens: Sequence[Token]) -> None:
    """A paragraph of nothing but raw HTML (``<object ...></object>``) leaves no empty
    ``<p>`` behind."""
    for index in range(1, len(tokens) - 1):
        token = tokens[index]
        if token.type != "inline" or tokens[index - 1].type != "paragraph_open":
            continue
        if all(
            child.type in ("html_inline", "softbreak")
            or (child.type == "text" and not child.content.strip())
            for child in token.children or []
        ):
            tokens[index - 1].hidden = True
            tokens[index + 1].hidden = True


def render_html(text: str, budget: TableBudget | None = None) -> str:
    """One section's Markdown as safe HTML (see the module docstring)."""
    text = normalise_newlines(text)
    env: Env = {}
    tokens = _md.parse(text, env)
    tokens = _bound_tables(tokens, text.split("\n"), budget or TableBudget())
    _mark_tasks(tokens)
    _hide_html_only_paragraphs(tokens)
    return str(_md.renderer.render(tokens, _md.options, env))


# --- The Markdown export ---------------------------------------------------------------
def _demote_atx(line: str, markup: str, demoted: str) -> str | None:
    for match in re.finditer(re.escape(markup) + r"(?!#)", line):
        start = match.start()
        if (start == 0 or line[start - 1] != "#") and _CONTAINER_PREFIX.fullmatch(line[:start]):
            return line[:start] + demoted + line[match.end() :]
    return None  # pragma: no cover - the parser found a heading on this line


def demote_headings(text: str) -> str:
    """The section's Markdown with every heading two levels down (``#`` -> ``###``,
    capped at ``######``), found with the parser: ATX headings get two more ``#``,
    setext headings (``Title`` over ``===``) are rewritten as the demoted ATX heading,
    and ``#`` lines in code are untouched. Everything else is kept verbatim."""
    text = normalise_newlines(text)
    lines = text.split("\n")
    tokens = _md.parse(text)
    replacements: dict[int, tuple[int, str]] = {}
    for index, token in enumerate(tokens):
        if token.type != "heading_open" or token.map is None:
            continue
        first, last = token.map
        demoted = "#" * min(int(token.tag[1:]) + HEADING_SHIFT, 6)
        if token.markup.startswith("#"):
            line = _demote_atx(lines[first], token.markup, demoted)
            if line is not None:
                replacements[first] = (first + 1, line)
            continue
        # Setext: the content lines and the underline become one ATX line.
        content = tokens[index + 1].content
        head = content.split("\n", 1)[0]
        at = lines[first].find(head)
        prefix = lines[first][:at] if at > 0 else ""
        if not _CONTAINER_PREFIX.fullmatch(prefix):
            prefix = ""
        heading = " ".join(part.strip() for part in content.split("\n"))
        if _CLOSING_SEQUENCE.search(heading):  # "Issue #" would lose its "#" in ATX
            heading = heading[:-1] + "\\#"
        replacements[first] = (last, f"{prefix}{demoted} {heading}".rstrip())
    if not replacements:
        return text
    result: list[str] = []
    index = 0
    while index < len(lines):
        if index in replacements:
            end, line = replacements[index]
            result.append(line)
            index = end
        else:
            result.append(lines[index])
            index += 1
    return "\n".join(result)


_SENTINEL: Final = "soundings-section-end"
_HTML_BLOCK_CLOSERS: Final = (
    (re.compile(r"<(script|pre|style|textarea)(?:[\s>]|$)", re.IGNORECASE), None),
    (re.compile(r"<!--"), "-->"),
    (re.compile(r"<\?"), "?>"),
    (re.compile(r"<!\[CDATA\["), "]]>"),
    (re.compile(r"<![A-Za-z]"), ">"),
)
"""CommonMark HTML blocks of types 1-5 run until their end marker (or the end of the
document); these give the marker for each."""


def _closers(text: str) -> list[str]:
    """What could close the block ``text`` leaves open: its last code fence's marker,
    or the end marker of its last raw HTML block."""
    closers: list[str] = []
    for token in reversed(_md.parse(text)):
        if token.level != 0:
            continue
        if token.type == "fence":
            closers.append(token.markup)
        elif token.type == "html_block":
            start = token.content.lstrip()
            for pattern, marker in _HTML_BLOCK_CLOSERS:
                match = pattern.match(start)
                if match:
                    closers.append(marker or f"</{match[1].lower()}>")
                    break
        break
    return closers


def _ends_cleanly(text: str) -> bool:
    """Would a heading right after ``text`` still be a heading (not code, not HTML)?"""
    tokens = _md.parse(f"{text}\n\n## {_SENTINEL}\n")
    return any(
        token.type == "inline"
        and token.content == _SENTINEL
        and tokens[index - 1].type == "heading_open"
        and tokens[index - 1].level == 0
        for index, token in enumerate(tokens)
    )


def close_open_blocks(text: str) -> str:
    """``text`` plus whatever closes a code fence or raw HTML block it leaves open, so
    the next section's heading stays a heading in the exported document (the editor
    renders each section on its own, so there it ends with the section)."""
    if _ends_cleanly(text):
        return text
    body = text.rstrip("\n")
    for closer in _closers(text):
        candidate = f"{body}\n{closer}"
        if _ends_cleanly(candidate):
            return candidate
    return text  # pragma: no cover - every CommonMark container closes with one of these
