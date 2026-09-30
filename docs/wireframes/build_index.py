#!/usr/bin/env python3
"""Build docs/wireframes/index.html from the screen files (0*.md) next to it.

    python3 docs/wireframes/build_index.py

Standard library only. It understands the small Markdown subset the wireframe files
use: headings, paragraphs, "- " lists (with indented continuation lines), fenced code
blocks, and inline `code`, **bold** and [links](target). The output is one
self-contained HTML file (no external assets) that reads well in light and dark mode.
The output is deterministic, so re-running without changes produces no diff.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "index.html"

INLINE = re.compile(r"`([^`]+)`|\*\*([^*]+)\*\*|\[([^\]]+)\]\(([^)\s]+)\)")


def inline(text: str) -> str:
    """Escape text and render inline code, bold and links."""
    out: list[str] = []
    pos = 0
    for match in INLINE.finditer(text):
        out.append(html.escape(text[pos : match.start()]))
        code, bold, label, target = match.groups()
        if code is not None:
            out.append(f"<code>{html.escape(code)}</code>")
        elif bold is not None:
            out.append(f"<strong>{html.escape(bold)}</strong>")
        else:
            out.append(f'<a href="{html.escape(target)}">{html.escape(label)}</a>')
        pos = match.end()
    out.append(html.escape(text[pos:]))
    return "".join(out)


def render(markdown: str) -> tuple[str, str]:
    """Return (title, html body) for one screen file."""
    title = ""
    parts: list[str] = []
    paragraph: list[str] = []
    items: list[str] = []
    lines = markdown.splitlines()
    i = 0

    def flush() -> None:
        if paragraph:
            parts.append(f"<p>{inline(' '.join(paragraph))}</p>")
            paragraph.clear()
        if items:
            parts.append("<ul>" + "".join(f"<li>{inline(t)}</li>" for t in items) + "</ul>")
            items.clear()

    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            flush()
            block: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                block.append(lines[i])
                i += 1
            parts.append(
                '<pre tabindex="0"><code>' + html.escape("\n".join(block)) + "</code></pre>"
            )
        elif line.startswith("# "):
            flush()
            title = line[2:].strip()
        elif line.startswith("## "):
            flush()
            parts.append(f"<h3>{inline(line[3:].strip())}</h3>")
        elif line.startswith("- "):
            if paragraph:
                flush()
            items.append(line[2:].strip())
        elif line.startswith("  ") and items and line.strip():
            items[-1] += " " + line.strip()
        elif not line.strip():
            flush()
        else:
            if items:
                flush()
            paragraph.append(line.strip())
        i += 1
    flush()
    return title, "\n".join(parts)


STYLE = """
:root {
  --bg: #f6f6f7; --surface: #ffffff; --fg: #1a1a1f; --muted: #5d5d66;
  --border: #e2e2e7; --code-bg: #f1f2f5; --accent: #1d5fa8; --accent-fg: #ffffff;
  --accent-subtle: #e8f0fa; color-scheme: light;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #111114; --surface: #19191d; --fg: #ececf1; --muted: #a3a3ad;
    --border: #2c2c33; --code-bg: #141418; --accent: #7fb0ea; --accent-fg: #0b1522;
    --accent-subtle: #17263a; color-scheme: dark;
  }
}
:root[data-theme="dark"] {
  --bg: #111114; --surface: #19191d; --fg: #ececf1; --muted: #a3a3ad;
  --border: #2c2c33; --code-bg: #141418; --accent: #7fb0ea; --accent-fg: #0b1522;
  --accent-subtle: #17263a; color-scheme: dark;
}
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body {
  margin: 0; background: var(--bg); color: var(--fg);
  font: 15px/1.55 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
}
a { color: var(--accent); }
a:focus-visible, button:focus-visible, pre:focus-visible {
  outline: 2px solid var(--accent); outline-offset: 2px;
}
.wrap { max-width: 1120px; margin: 0 auto; padding: 32px 16px 64px; }
header { display: flex; flex-wrap: wrap; gap: 12px 24px; align-items: flex-start;
  justify-content: space-between; margin-bottom: 8px; }
h1 { font-size: 26px; line-height: 1.2; margin: 0 0 4px; letter-spacing: -0.01em; }
.sub { color: var(--muted); margin: 0; }
button.theme {
  font: inherit; font-size: 13px; color: var(--fg); background: var(--surface);
  border: 1px solid var(--border); border-radius: 8px; padding: 6px 12px; cursor: pointer;
}
.intro { max-width: 72ch; }
nav ol { list-style: none; padding: 0; margin: 20px 0 32px; display: flex;
  flex-wrap: wrap; gap: 8px; }
nav li { margin: 0; }
nav a { display: inline-block; padding: 6px 12px; border-radius: 999px;
  background: var(--accent-subtle); text-decoration: none; font-size: 14px; }
section { background: var(--surface); border: 1px solid var(--border);
  border-radius: 12px; padding: 24px; margin: 0 0 24px; }
section h2 { font-size: 21px; margin: 0 0 8px; }
section h3 { font-size: 15px; text-transform: uppercase; letter-spacing: 0.04em;
  color: var(--muted); margin: 28px 0 8px; }
pre { background: var(--code-bg); border: 1px solid var(--border); border-radius: 8px;
  padding: 12px 14px; overflow-x: auto; margin: 8px 0;
  font: 12.5px/1.35 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
pre code { font: inherit; background: none; padding: 0; }
code { font: 0.92em ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  background: var(--code-bg); padding: 1px 4px; border-radius: 4px; }
ul { padding-left: 20px; } li { margin: 6px 0; } li, p { max-width: 80ch; }
footer { color: var(--muted); font-size: 13px; }
@media (max-width: 600px) { section { padding: 16px; } h1 { font-size: 22px; } }
"""

SCRIPT = """
(function () {
  var root = document.documentElement, btn = document.getElementById('theme');
  var order = ['system', 'light', 'dark'], mode = 'system';
  try { mode = localStorage.getItem('wireframes-theme') || 'system'; } catch (e) {}
  function apply() {
    if (mode === 'system') root.removeAttribute('data-theme');
    else root.setAttribute('data-theme', mode);
    btn.textContent = 'Theme: ' + mode;
  }
  btn.addEventListener('click', function () {
    mode = order[(order.indexOf(mode) + 1) % order.length];
    try { localStorage.setItem('wireframes-theme', mode); } catch (e) {}
    apply();
  });
  apply();
})();
"""


def main() -> None:
    screens = []
    for path in sorted(HERE.glob("0*.md")):
        title, body = render(path.read_text(encoding="utf-8"))
        anchor = path.stem.split("-", 1)[1]  # "03-idea-page" -> "idea-page"
        screens.append((anchor, title, body, path.name))

    nav = "".join(f'<li><a href="#{a}">{html.escape(t)}</a></li>' for a, t, _, _ in screens)
    sections = "\n".join(
        f'<section id="{a}" aria-labelledby="{a}-h">'
        f'<h2 id="{a}-h">{html.escape(t)}</h2>'
        f'<p class="sub">Source: <a href="{n}">docs/wireframes/{n}</a></p>\n{b}</section>'
        for a, t, b, n in screens
    )
    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Soundings wireframes</title>
<meta name="description"
  content="Low-fi wireframes of the seven Soundings screens for Phase 0 review.">
<style>{STYLE}</style>
</head>
<body>
<div class="wrap">
<header>
  <div>
    <h1>Soundings wireframes</h1>
    <p class="sub">Low-fi, Phase 0 review &middot; seven screens from SPEC section 5</p>
  </div>
  <button type="button" class="theme" id="theme">Theme: system</button>
</header>
<p class="intro">Each screen shows desktop and mobile layouts with notes on the
primary action, loading, empty and error states, keyboard use and mobile behaviour.
<code>[## Label ##]</code> marks the single primary (accent) button;
<code>[ Label ]</code> is secondary; <code>2/3</code> is evaluator progress;
<code>!</code> flags high disagreement. Permissions follow
<a href="../role-matrix.md">docs/role-matrix.md</a>.</p>
<nav aria-label="Screens"><ol>{nav}</ol></nav>
<main>
{sections}
</main>
<footer>Generated from <code>docs/wireframes/0*.md</code> by
<code>python3 docs/wireframes/build_index.py</code>. Edit the Markdown, then re-run.</footer>
</div>
<script>{SCRIPT}</script>
</body>
</html>
"""
    OUT.write_text(page, encoding="utf-8")
    print(f"wrote {OUT.relative_to(HERE.parent.parent)} ({len(screens)} screens)")


if __name__ == "__main__":
    main()
