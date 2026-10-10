"""The PDF renderer (contract-phase4 3.4, ADR 0011; tests first): a URL fetcher that
answers only bundled fonts and ``data:`` URIs, WeasyPrint's own fetcher never called, a
child process killed after its time limit, one render at a time, and what the PDF
contains (cover, contents, page numbers, outline, metadata, fonts)."""

from __future__ import annotations

import asyncio
import contextlib
import io
import os
import re
import socket
import time
import warnings
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import ImageFile
from pypdf import PdfReader

from app.proposals import pdf
from app.proposals.document import ExportBranding, ExportDocument, ExportSection, build_html
from app.proposals.fonts import FONT_FILES
from app.proposals.markdown import BREAK, TOO_LONG
from app.proposals.pdf import ExportBusy, Renderer, RenderFailed
from app.schemas.proposals import PROPOSAL_TEMPLATE
from tests.proposals import children

with warnings.catch_warnings():
    # WeasyPrint warns at import where HarfBuzz-Subset is missing (it uses fontTools).
    warnings.simplefilter("ignore", DeprecationWarning)
    try:
        from app.proposals import pdf_child
    except (ImportError, OSError) as missing:  # pragma: no cover - a host without Pango
        pytest.skip(f"WeasyPrint can't load: {missing}", allow_module_level=True)
# Importing WeasyPrint turns on Pillow's LOAD_TRUNCATED_IMAGES for the whole process. Only
# the PDF child imports it in production; here, keep the rest of the session's Pillow
# strict (the branding upload tests expect truncated PNGs to fail).
ImageFile.LOAD_TRUNCATED_IMAGES = False


def _png() -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGBA", (120, 40), (11, 110, 79, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


PNG = _png()
SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
    b'<rect width="10" height="10" fill="#1d5fa8"/></svg>'
)
HOSTILE = "\n\n".join(
    [
        "a <b>x</b> c",
        "<script>alert(1)</script>",
        '<img src="http://169.254.169.254/latest/meta-data/">',
        '<iframe src="http://169.254.169.254/"></iframe>',
        '<link rel="stylesheet" href="http://169.254.169.254/x.css">',
        "<style>@import url(http://169.254.169.254/y.css);"
        " body { background: url(file:///etc/passwd) }</style>",
        '<object data="file:///etc/passwd"></object>',
        "![metadata](http://169.254.169.254/latest/meta-data/)",
        "![passwd](file:///etc/passwd)",
        "[js](javascript:alert(1)) and [passwd](file:///etc/passwd)",
        '<svg><image href="http://169.254.169.254/z.png"/></svg>',
        '<link rel="attachment" href="file:///etc/passwd">',
    ]
)


def document(**overrides: Any) -> ExportDocument:
    bodies = overrides.pop("bodies", {})
    values: dict[str, Any] = {
        "title": "Self-service refunds",
        "idea_key": "CUST-12",
        "project_name": "Customer Innovation",
        "status_label": "Proposal",
        "owner_name": "Olive Owner",
        "exported_at": datetime(2026, 10, 1, 9, 30, tzinfo=UTC),
        "exported_by": "Ada Admin",
        "sections": tuple(
            ExportSection(t.key.value, t.title, bodies.get(t.key.value, ""))
            for t in PROPOSAL_TEMPLATE
        ),
        "branding": ExportBranding(app_name="Acme Ideas", primary_color="#0b6e4f"),
    }
    values.update(overrides)
    return ExportDocument(**values)


def text_of(data: bytes) -> list[str]:
    return [page.extract_text() for page in PdfReader(io.BytesIO(data)).pages]


def resources(page: Any) -> dict[str, Any]:
    found: dict[str, Any] = page["/Resources"].get_object()
    return found


def fonts_of(data: bytes) -> set[str]:
    found = set()
    for page in PdfReader(io.BytesIO(data)).pages:
        for font in resources(page).get("/Font", {}).values():
            found.add(str(font.get_object()["/BaseFont"]).split("+", 1)[-1])
    return found


@pytest.fixture
def recorded(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every URL WeasyPrint asks for; WeasyPrint's own fetcher and any socket fail."""
    from weasyprint.urls import URLFetcher

    urls: list[str] = []
    original = pdf_child.LocalOnlyFetcher.fetch

    def recording(self: Any, url: str, headers: Any = None) -> Any:
        urls.append(url)
        return original(self, url, headers)

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError(f"network or default fetcher used: {args!r}")

    monkeypatch.setattr(pdf_child.LocalOnlyFetcher, "fetch", recording)
    monkeypatch.setattr(URLFetcher, "fetch", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    return urls


# --- The fetcher ---------------------------------------------------------------------
def test_the_fetcher_answers_bundled_fonts_by_name() -> None:
    fetcher = pdf_child.LocalOnlyFetcher()
    for name in FONT_FILES:
        response = fetcher.fetch(f"soundings-font:{name}")
        assert response.read()[:4] == b"wOF2"


@pytest.mark.parametrize(
    ("url", "media_type", "data"),
    [
        ("data:image/png;base64,iVBORw0KGgo=", "image/png", b"\x89PNG\r\n\x1a\n"),
        ("data:image/svg+xml;base64,PHN2Zy8+", "image/svg+xml", b"<svg/>"),
    ],
)
def test_the_fetcher_decodes_image_data_uris(url: str, media_type: str, data: bytes) -> None:
    response = pdf_child.LocalOnlyFetcher().fetch(url)
    assert response.read() == data
    assert response.content_type == media_type


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",
        "https://example.com/font.woff2",
        "file:///etc/passwd",
        "FILE:///etc/passwd",
        "ftp://example.com/x",
        "soundings-font:../../../../etc/passwd",
        "soundings-font:/etc/passwd",
        "soundings-font:inter-400.woff2",
        "soundings-font:",
        "data:text/html;base64,PGI+eDwvYj4=",
        "data:image/png,rawbytes",
        "data:image/png;base64,***",
        "data:,hello",
        "relative/path.png",
        "/absolute/path.png",
        "//169.254.169.254/x",
        "",
    ],
)
def test_the_fetcher_refuses_everything_else(url: str) -> None:
    with pytest.raises(pdf_child.BlockedURL):
        pdf_child.LocalOnlyFetcher().fetch(url)


def test_the_fetcher_never_uses_urllib(monkeypatch: pytest.MonkeyPatch) -> None:
    from weasyprint.urls import URLFetcher

    monkeypatch.setattr(URLFetcher, "fetch", lambda *a, **k: pytest.fail("default fetcher"))
    with pytest.raises(pdf_child.BlockedURL):
        pdf_child.LocalOnlyFetcher().open("http://example.com/")
    with pytest.raises(pdf_child.BlockedURL):
        pdf_child.LocalOnlyFetcher()("file:///etc/passwd")


# --- Rendering (in this process) -----------------------------------------------------
def test_a_hostile_proposal_fetches_nothing_and_renders_like_the_spa(
    recorded: list[str],
) -> None:
    logo = ExportBranding(app_name="Acme", logo_type="image/svg+xml", logo=SVG)
    data = pdf_child.render_document(
        document(bodies=dict.fromkeys(("summary", "risks"), HOSTILE), branding=logo)
    )

    assert data.startswith(b"%PDF-")
    assert recorded, "the fonts and logo come through the fetcher"
    assert all(url.startswith(("data:", "soundings-font:")) for url in recorded), recorded
    text = "\n".join(text_of(data))
    assert "a x c" in text
    assert "metadata" in text
    assert "passwd" in text  # images and links as their labels
    assert "alert" not in text
    assert "<script" not in text
    # The image's target is only ever printed text, in brackets after its label.
    printed = re.findall(r"\(([^()]*)\)", text.replace(BREAK, ""))
    assert "169.254" not in re.sub(r"\([^()]*\)", "", text.replace(BREAK, ""))
    assert any("169.254.169.254" in url.replace("\n", "") for url in printed)


def test_the_pdf_has_cover_contents_sections_page_numbers_and_metadata(
    recorded: list[str],
) -> None:
    long = "A plain sentence about the plan and what it changes for everyone. " * 140
    data = pdf_child.render_document(
        document(
            bodies={"summary": "Refunds in two clicks.", "problem": f"# Calls\n\n{long}"},
            score=Decimal("4.1"),
            score_count=5,
        )
    )

    reader = PdfReader(io.BytesIO(data))
    pages = [page.extract_text() for page in reader.pages]
    cover, contents = pages[0], pages[1]
    assert "Acme Ideas" in cover
    assert "Self-service refunds" in cover
    assert "Customer Innovation" in cover
    assert "CUST-12" in cover
    assert "Olive Owner" in cover
    assert "Exported 1 October 2026 by Ada Admin" in cover
    assert "Aggregate score 4.1 from 5 evaluations" in cover
    assert "Page" not in cover  # no header or footer on the cover
    assert "CONTENTS" not in cover.upper()  # a long document: the contents have their own page
    assert "Contents" in contents
    assert "Next steps / the ask" in contents
    assert "Solution · Not written yet." in contents  # empty sections say so
    assert f"Page 2 of {len(pages)}" in contents
    assert "Acme Ideas" in contents
    assert "CUST-12" in contents  # running header
    body = "\n".join(pages[2:])
    assert "Refunds in two clicks." in body
    assert "Not written yet." in body
    assert reader.metadata is not None
    assert reader.metadata.title == "Self-service refunds"
    assert reader.metadata.author == "Olive Owner"
    assert reader.metadata.creator == "Acme Ideas"
    outline = [item.title for item in reader.outline if not isinstance(item, list)]
    assert outline == ["Self-service refunds"]
    sections = [item.title for item in reader.outline[1] if not isinstance(item, list)]
    assert sections[:2] == ["Summary", "Problem"]
    assert len(sections) == 8


def test_a_short_documents_contents_are_on_the_cover() -> None:
    """UX review m4: no page of contents in front of a two-page body."""
    data = pdf_child.render_document(
        document(bodies={"summary": "Refunds in two clicks.", "problem": "## Calls\n\nToo many."})
    )

    pages = [page.extract_text() for page in PdfReader(io.BytesIO(data)).pages]
    cover = pages[0]
    assert "CONTENTS" in cover.upper()
    assert "Summary" in cover
    assert "Next steps / the ask · Not written yet." in cover
    assert "Page" not in cover
    assert "Refunds in two clicks." in pages[1]  # the sections start on page 2
    assert "Acme Ideas" in pages[1]  # with the running header
    assert "CUST-12" in pages[1]
    assert f"Page 2 of {len(pages)}" in pages[1]


def test_headings_and_links_in_a_section_print_as_the_spa_shows_them() -> None:
    """UX review M4/m5: every heading level is semibold and above body size or muted,
    and a link prints its URL."""
    html = build_html(
        document(
            bodies={
                "summary": "### Who\n\nSee [the survey](https://example.com/s) or "
                "[mail us](mailto:team@example.com)."
            }
        )
    )
    assert "<h4>Who</h4>" in html
    style = html[html.index("<style>") : html.index("</style>")]
    for level, size in (("h3", "13pt"), ("h4", "11.5pt"), ("h5", "10.5pt"), ("h6", "9.5pt")):
        rule = style[style.index(f".section {level} {{") :]
        assert f"font-size: {size};" in rule[: rule.index("}")]
    assert "font-weight: 500" not in style  # no weight without a bundled face
    text = "\n".join(text_of(pdf_child.render_html(html))).replace(BREAK, "")
    assert "the survey (https://example.com/s)" in " ".join(text.split())
    assert "mail us (team@example.com)" in text


@pytest.mark.parametrize(
    ("font", "embedded"),
    [
        ("inter", "Soundings-Brand"),
        ("source_serif_4", "Soundings-Brand"),
        ("nope", "Soundings-Brand"),
    ],
)
def test_only_the_bundled_fonts_are_embedded(recorded: list[str], font: str, embedded: str) -> None:
    data = pdf_child.render_document(
        document(
            branding=ExportBranding(app_name="Acme", font=font),
            bodies={"summary": "Plain *italic* **bold** `code` Žluťoučký kůň"},
        )
    )
    fonts = fonts_of(data)
    assert embedded in fonts
    assert fonts <= {
        "Soundings-Brand",
        "Soundings-Brand-Bold",
        "Soundings-Brand-Semi-Bold",
        "Soundings-Brand-Italic",
        "Soundings-Brand-Ext",
        "Soundings-Brand-Ext-Bold",
        "Soundings-Brand-Ext-Semi-Bold",
        "Soundings-Brand-Ext-Italic",
        "Soundings-Mono",
        "Soundings-Mono-Ext",
    }, fonts
    assert "Žluťoučký kůň" in "\n".join(text_of(data))


def test_a_png_logo_is_embedded(recorded: list[str]) -> None:
    data = pdf_child.render_document(
        document(branding=ExportBranding(app_name="Acme", logo_type="image/png", logo=PNG))
    )
    assert any(url.startswith("data:image/png;base64,") for url in recorded)
    cover = PdfReader(io.BytesIO(data)).pages[0]
    assert resources(cover).get("/XObject"), "the logo is an image on the cover"


def test_tables_beyond_the_budget_print_as_source(recorded: list[str]) -> None:
    table = "| a | b |\n|---|---|\n" + "\n".join(f"| {r} | x |" for r in range(250))
    html = build_html(document(bodies={"summary": table}))
    sections = html.split('<section class="section"', 1)[1]
    assert "<table>" not in sections
    assert 'class="table-source"' in sections
    data = pdf_child.render_document(document(bodies={"summary": table}))
    assert "| 249 | x |" in "\n".join(text_of(data))


# --- The child process ---------------------------------------------------------------
@pytest.fixture
def fresh_renderer(monkeypatch: pytest.MonkeyPatch) -> Iterator[Renderer]:
    renderer = Renderer()
    monkeypatch.setattr(pdf, "_renderer", renderer)
    yield renderer
    renderer.stop()


def _alive(pid: int | None) -> bool:
    import os

    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:  # a zombie still answers kill(0): check its state
        with open(f"/proc/{pid}/stat") as stat:
            return stat.read().split(")")[-1].split()[0] != "Z"
    except FileNotFoundError:
        return False


def test_the_renderer_returns_the_pdf_and_stays_warm(fresh_renderer: Renderer) -> None:
    first = fresh_renderer.render(document(), timeout=20, wait=1)
    pid = fresh_renderer.pid
    second = fresh_renderer.render(document(title="Another"), timeout=20, wait=1)

    assert first.startswith(b"%PDF-")
    assert second.startswith(b"%PDF-")
    assert "Another" in text_of(second)[0]
    assert fresh_renderer.pid == pid  # the same child served both


def test_a_render_over_the_limit_is_killed_and_the_next_one_works() -> None:
    slow = Renderer(target=children.sleep_forever)
    started = time.monotonic()
    with pytest.raises(ExportBusy) as busy:
        slow.render(document(), timeout=1.0, wait=1)
    assert busy.value.reason == "timeout"
    assert time.monotonic() - started < 10
    assert slow.pid is None

    working = Renderer()
    try:
        assert working.render(document(), timeout=20, wait=1).startswith(b"%PDF-")
    finally:
        working.stop()


def test_the_killed_child_is_gone() -> None:
    slow = Renderer(target=children.sleep_forever)
    slow._start()
    pid = slow.pid
    assert _alive(pid)
    with pytest.raises(ExportBusy):
        slow.render(document(), timeout=0.5, wait=1)
    assert not _alive(pid)


def test_a_killed_render_leaves_no_temporary_files() -> None:
    slow = Renderer(target=children.sleep_forever_with_temp_files)
    slow._start()
    scratch = slow.scratch
    assert scratch is not None
    assert os.path.isdir(scratch)
    with pytest.raises(ExportBusy):
        slow.render(document(), timeout=1.0, wait=1)
    assert not os.path.exists(scratch)
    assert slow.scratch is None


def test_the_child_writes_temporary_files_in_its_own_folder(fresh_renderer: Renderer) -> None:
    fresh_renderer.render(document(), timeout=20, wait=1)
    scratch = fresh_renderer.scratch
    assert scratch is not None
    assert os.listdir(scratch)  # WeasyPrint's font folder is in it, not in /tmp
    fresh_renderer.stop()
    assert not os.path.exists(scratch)


def test_a_crashing_child_is_a_render_failure() -> None:
    renderer = Renderer(target=children.crash)
    with pytest.raises(RenderFailed):
        renderer.render(document(), timeout=20, wait=1)
    assert renderer.pid is None


def test_a_render_error_is_reported_by_class_name_only() -> None:
    renderer = Renderer(target=children.answer_error)
    try:
        with pytest.raises(RenderFailed, match=r"^ValueError$"):
            renderer.render(document(), timeout=20, wait=1)
    finally:
        renderer.stop()


def test_a_child_that_exited_while_idle_is_replaced(fresh_renderer: Renderer) -> None:
    import os
    import signal

    fresh_renderer.render(document(), timeout=20, wait=1)
    pid = fresh_renderer.pid
    assert pid is not None
    os.kill(pid, signal.SIGKILL)  # as if it had exited after IDLE_EXIT
    time.sleep(0.2)

    assert fresh_renderer.render(document(), timeout=20, wait=1).startswith(b"%PDF-")
    assert fresh_renderer.pid != pid


def test_one_render_at_a_time(monkeypatch: pytest.MonkeyPatch) -> None:
    slow = Renderer(target=children.sleep_forever)
    import threading

    started = threading.Event()

    def first() -> None:
        started.set()
        with contextlib.suppress(ExportBusy):
            slow.render(document(), timeout=2, wait=1)

    thread = threading.Thread(target=first)
    thread.start()
    started.wait()
    time.sleep(0.3)
    with pytest.raises(ExportBusy) as busy:
        slow.render(document(), timeout=2, wait=0.3)
    assert busy.value.reason == "busy"
    thread.join()


async def test_waiting_for_the_slot_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pdf, "SLOT_TIMEOUT", 0.3)
    state = SimpleNamespace()
    slot = pdf._slot(state)
    await slot.acquire()  # someone else is rendering
    try:
        with pytest.raises(ExportBusy) as busy:
            await pdf.render_pdf(state, document())
        assert busy.value.reason == "busy"
    finally:
        slot.release()


async def test_the_event_loop_keeps_running_during_a_render(fresh_renderer: Renderer) -> None:
    long_text = (
        "Prose with **bold** and _emphasis_ and a [link](https://example.com). " * 30 + "\n\n"
    ) * 8
    big = document(bodies={t.key.value: long_text[:20_000] for t in PROPOSAL_TEMPLATE})
    lag = 0.0

    async def tick() -> None:
        nonlocal lag
        while True:
            before = time.monotonic()
            await asyncio.sleep(0.01)
            lag = max(lag, time.monotonic() - before - 0.01)

    ticker = asyncio.create_task(tick())
    try:
        started = time.monotonic()
        data = await pdf.render_pdf(SimpleNamespace(), big)
        took = time.monotonic() - started
    finally:
        ticker.cancel()
    assert data.startswith(b"%PDF-")
    assert lag < 0.25, f"the event loop paused for {lag:.3f} s during a {took:.1f} s render"


def test_the_longest_prose_proposal_renders_well_within_the_limit(
    fresh_renderer: Renderer,
) -> None:
    """8 x 20,000 characters of ordinary prose (some bold, a link per paragraph): about
    3 s on the build machine (contract 3.4 measured about 2 s)."""
    paragraph = (
        "We would let customers **refund** orders themselves. "
        + "A plain sentence about the plan and what it changes for everyone. " * 10
        + "See [the spec](https://example.com)."
    )
    body = "\n\n".join([paragraph] * 40)[:20_000]
    big = document(bodies={t.key.value: body for t in PROPOSAL_TEMPLATE})
    fresh_renderer.render(document(), timeout=20, wait=1)  # warm

    started = time.monotonic()
    data = fresh_renderer.render(big, timeout=20, wait=1)
    took = time.monotonic() - started

    assert len(PdfReader(io.BytesIO(data)).pages) > 20
    assert took < 10, f"8 x 20,000 characters took {took:.1f} s"


HOSTILE_LAYOUTS = (
    "- a\n" * 5_000,  # list items: the costliest boxes
    "a\\\n" * 6_666,  # hard line breaks
    "a\n\n" * 6_666,  # paragraphs
    "*a*," * 5_000,  # inline elements
    "a*b*" * 5_000,  # one run across 5,000 inline elements
    "```\n" + "a\n" * 9_990 + "```\n",  # code lines
    "i" * 20_000,  # one narrow 20,000-character word
    "| " + "i" * 19_980 + " |\n|-|\n| b |",  # ... in a table cell
)


def test_hostile_layouts_render_well_within_the_limit(fresh_renderer: Renderer) -> None:
    """One section each of what made WeasyPrint slow or large (code review H1: 9-25 s
    and up to 250 MB per section before the box budget and break opportunities):
    about 6 s for all eight on one CPU of the build machine, and cut with a note."""
    hostile = document(
        bodies={
            t.key.value: body for t, body in zip(PROPOSAL_TEMPLATE, HOSTILE_LAYOUTS, strict=True)
        }
    )
    assert all(len(body) <= 20_000 for body in HOSTILE_LAYOUTS)
    fresh_renderer.render(document(), timeout=20, wait=1)  # warm

    started = time.monotonic()
    data = fresh_renderer.render(hostile, timeout=20, wait=1)
    took = time.monotonic() - started

    text = " ".join(" ".join(text_of(data)).split())
    assert TOO_LONG in text
    assert took < 15, f"the hostile layouts took {took:.1f} s"


def test_the_child_memory_limit_is_half_the_containers(tmp_path: Any) -> None:
    v2 = tmp_path / "v2"
    v2.mkdir()
    (v2 / "memory.max").write_text("536870912\n")  # 512 MiB
    v1 = tmp_path / "v1"
    (v1 / "memory").mkdir(parents=True)
    (v1 / "memory" / "memory.limit_in_bytes").write_text("1073741824\n")
    unlimited_v1 = tmp_path / "unlimited-v1"
    (unlimited_v1 / "memory").mkdir(parents=True)
    (unlimited_v1 / "memory" / "memory.limit_in_bytes").write_text("9223372036854771712\n")
    unlimited_v2 = tmp_path / "unlimited-v2"
    unlimited_v2.mkdir()
    (unlimited_v2 / "memory.max").write_text("max\n")
    large = tmp_path / "large"
    large.mkdir()
    (large / "memory.max").write_text(str(8 * 1024**3))

    assert pdf_child.memory_limit(v2) == 256 * 1024**2
    assert pdf_child.memory_limit(v1) == 512 * 1024**2
    assert pdf_child.memory_limit(unlimited_v1) == pdf_child.MEMORY_CAP
    assert pdf_child.memory_limit(unlimited_v2) == pdf_child.MEMORY_CAP
    assert pdf_child.memory_limit(large) == pdf_child.MEMORY_CAP
    assert pdf_child.memory_limit(tmp_path / "missing") == pdf_child.MEMORY_CAP


def test_the_child_runs_with_its_memory_limit(fresh_renderer: Renderer) -> None:
    fresh_renderer.render(document(), timeout=20, wait=1)

    with open(f"/proc/{fresh_renderer.pid}/limits") as limits:
        [line] = [line for line in limits if line.startswith("Max data size")]
    assert line.split()[3] == str(pdf_child.memory_limit())


def test_a_child_that_grew_large_is_replaced_by_a_fresh_one() -> None:
    """Python keeps what a large render grew (a warm child crept from 185 to 197 MB
    over six hostile exports): past half its limit, the child exits after replying."""
    renderer = Renderer(target=children.serve_and_retire)
    try:
        assert renderer.render(document(), timeout=20, wait=1).startswith(b"%PDF-")
        first = renderer.pid
        assert renderer.render(document(), timeout=20, wait=1).startswith(b"%PDF-")
        assert renderer.pid != first
    finally:
        renderer.stop()


def test_a_large_api_process_does_not_make_the_child_retire() -> None:
    """The child judges its own peak, not the parent's: Linux keeps the peak resident
    size of the address space ``execve`` replaced, so a spawned child's ``ru_maxrss``
    starts at the API process's peak (CI: a pytest process past 512 MiB retired the
    child after every render)."""
    ballast = b"\1" * (children.RETIRE_ABOVE_256_MIB + 64 * 1024**2)  # resident, then freed
    del ballast
    renderer = Renderer(target=children.serve_retiring_above_256_mib)
    try:
        assert renderer.render(document(), timeout=20, wait=1).startswith(b"%PDF-")
        first = renderer.pid
        assert renderer.render(document(), timeout=20, wait=1).startswith(b"%PDF-")
        assert renderer.pid == first
    finally:
        renderer.stop()


def test_the_peak_memory_is_the_childs_own(tmp_path: Any) -> None:
    status = tmp_path / "status"
    status.write_text("Name:\tpython\nVmPeak:\t  900000 kB\nVmHWM:\t  112640 kB\nVmRSS:\t 1 kB\n")
    assert pdf_child._peak_memory(status) == 112640 * 1024
    assert pdf_child._peak_memory(tmp_path / "missing") > 0  # getrusage where /proc is missing


def test_the_child_gets_no_secrets_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    monkeypatch.setenv("SOUNDINGS_SECRET_KEY", "s3cret")
    monkeypatch.setenv("SOUNDINGS_DATABASE_URL", "postgresql+psycopg://u:p@db/x")
    monkeypatch.setenv("SOUNDINGS_OIDC_CLIENT_SECRET", "oidc")
    monkeypatch.setenv("LC_ALL", "C.UTF-8")
    monkeypatch.setenv("XDG_CACHE_HOME", "/var/cache/soundings")
    renderer = Renderer(target=children.report_environment)
    try:
        names = set(json.loads(renderer.render(document(), timeout=20, wait=1)))
    finally:
        renderer.stop()

    assert not any(name.startswith("SOUNDINGS_") for name in names), names
    assert {"LC_ALL", "XDG_CACHE_HOME", "TMPDIR"} <= names
    assert names <= pdf.CHILD_ENVIRONMENT | {"LC_ALL"} | {n for n in names if n.startswith("LC_")}


def test_the_most_table_cells_render_well_within_the_limit(fresh_renderer: Renderer) -> None:
    rows = "\n".join(f"| {r} | b | c | d | e |" for r in range(199))
    table = f"| a | b | c | d | e |\n|---|---|---|---|---|\n{rows}"  # 1,000 cells
    tables = document(bodies={t.key.value: table for t in PROPOSAL_TEMPLATE})
    fresh_renderer.render(document(), timeout=20, wait=1)  # warm

    started = time.monotonic()
    data = fresh_renderer.render(tables, timeout=20, wait=1)
    took = time.monotonic() - started

    assert data.startswith(b"%PDF-")
    assert took < 15, f"2,000 cells plus 6,000 as source took {took:.1f} s"


def test_an_unreadable_logo_falls_back_to_the_wordmark(recorded: list[str]) -> None:
    broken = ExportBranding(app_name="Acme Ideas", logo_type="image/png", logo=PNG[:60])
    data = pdf_child.render_document(document(branding=broken))
    assert "Acme Ideas" in text_of(data)[0]


def test_the_limit_covers_sending_to_a_child_that_stopped_reading() -> None:
    stuck = Renderer(target=children.never_read)
    large = document(
        branding=ExportBranding(app_name="Acme", logo_type="image/png", logo=b"\0" * 4_000_000)
    )
    started = time.monotonic()
    with pytest.raises(ExportBusy) as busy:
        stuck.render(large, timeout=1.0, wait=1)
    assert busy.value.reason == "timeout"
    assert time.monotonic() - started < 5
    assert stuck.pid is None


@pytest.mark.parametrize(
    ("logo_type", "logo", "readable"),
    [
        ("image/png", PNG, True),
        ("image/png", PNG[:60], False),
        ("image/png", b"<svg/>", False),
        ("image/svg+xml", SVG, True),
        ("image/svg+xml", b"<svg", False),
        ("image/svg+xml", b'<!DOCTYPE svg [<!ENTITY a "aaaa">]><svg>&a;</svg>', False),
        ("text/html", b"<b>x</b>", False),
    ],
)
def test_logo_readable(logo_type: str, logo: bytes, readable: bool) -> None:
    branding = ExportBranding(app_name="Acme", logo_type=logo_type, logo=logo)
    assert pdf_child.logo_readable(branding) is readable
