"""The export document (contract-phase4 3.4 and 3.10): the Markdown export's text, and
the PDF's HTML: escaping, branding values in the stylesheet (validated hex and fixed
font faces only), contrast, and no URL but bundled fonts and the embedded logo."""

from __future__ import annotations

import io
import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from app.models.enums import BrandFont
from app.proposals.document import (
    DEFAULT_COLOR,
    INK,
    WHITE,
    ExportBranding,
    ExportDocument,
    ExportSection,
    build_html,
    build_markdown,
    contrast,
    font_face_css,
    safe_color,
    text_color_on,
)
from app.proposals.fonts import BRAND_FONTS, FONT_DIR, FONT_FILES
from app.schemas.proposals import PROPOSAL_TEMPLATE


def _png() -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGBA", (120, 40), (11, 110, 79, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


PNG = _png()


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
        "branding": ExportBranding(app_name="Soundings"),
    }
    values.update(overrides)
    return ExportDocument(**values)


# --- Markdown ------------------------------------------------------------------------
def test_the_markdown_export_has_front_matter_metadata_and_every_section_in_order() -> None:
    text = build_markdown(
        document(
            bodies={"summary": "Refunds in two clicks.", "risks": "# Fraud\n\nWe cap it."},
            score=Decimal("4.1"),
            score_count=5,
        )
    )

    assert text == (
        "---\n"
        'title: "Self-service refunds"\n'
        'idea: "CUST-12"\n'
        'project: "Customer Innovation"\n'
        'status: "Proposal"\n'
        'owner: "Olive Owner"\n'
        'exported: "2026-10-01"\n'
        'exported_by: "Ada Admin"\n'
        "aggregate_score: 4.1\n"
        "evaluations: 5\n"
        "---\n\n"
        "# Self-service refunds\n\n"
        "- Project: Customer Innovation\n"
        "- Idea: CUST-12\n"
        "- Status: Proposal\n"
        "- Owner: Olive Owner\n"
        "- Exported 1 October 2026 by Ada Admin\n"
        "- Aggregate score 4.1 from 5 evaluations\n\n"
        "## Summary\n\nRefunds in two clicks.\n\n"
        "## Problem\n\n_Not written yet._\n\n"
        "## Solution\n\n_Not written yet._\n\n"
        "## Market & users\n\n_Not written yet._\n\n"
        "## Cost & effort\n\n_Not written yet._\n\n"
        "## Benefits / revenue\n\n_Not written yet._\n\n"
        "## Risks\n\n### Fraud\n\nWe cap it.\n\n"
        "## Next steps / the ask\n\n_Not written yet._\n"
    )


def test_without_score_access_there_is_no_score_anywhere() -> None:
    text = build_markdown(document(owner_name=None))
    assert "score" not in text.lower()
    assert "evaluation" not in text.lower()
    assert "owner: null" in text
    assert "- Owner: Unassigned" in text


def test_one_evaluation_is_singular() -> None:
    text = build_markdown(document(score=Decimal("3.0"), score_count=1))
    assert "- Aggregate score 3.0 from 1 evaluation\n" in text


def test_section_text_is_verbatim_except_demoted_headings_and_closed_fences() -> None:
    body = "    indented code\n\nSetext\n===\n\n```\n# not a heading\n```\n\nText  \nbreak"
    text = build_markdown(document(bodies={"problem": body, "solution": "```\nopen fence"}))

    assert (
        "## Problem\n\n    indented code\n\n### Setext\n\n```\n# not a heading\n```\n\n"
        "Text  \nbreak\n\n## Solution\n\n```\nopen fence\n```\n\n## Market"
    ) in text


def test_titles_and_names_stay_text_in_markdown() -> None:
    text = build_markdown(
        document(title='# Not *bold* <script>x</script> [l](u) "q"', exported_by="Jo_Smith")
    )
    assert '# \\# Not \\*bold\\* \\<script\\>x\\</script\\> \\[l\\](u) "q"\n' in text
    assert 'title: "# Not *bold* <script>x</script> [l](u) \\"q\\""' in text
    assert "by Jo\\_Smith" in text


def test_ampersands_are_escaped_only_before_an_entity() -> None:
    text = build_markdown(document(title="R&D &amp; &#169; & more"))
    assert "# R&D \\&amp; \\&\\#169; & more\n" in text


def test_front_matter_escapes_line_separators() -> None:
    text = build_markdown(document(title=f"a{chr(0x2028)}b"))
    assert 'title: "a\\Lb"' in text


# --- HTML for the PDF ----------------------------------------------------------------
def _style(html: str) -> str:
    match = re.search(r"<style>(.*?)</style>", html, re.DOTALL)
    assert match is not None
    return match[1]


def test_the_html_escapes_every_value() -> None:
    hostile = '<img src="http://169.254.169.254/x"><script>alert(1)</script>'
    html = build_html(
        document(
            title=hostile,
            project_name=hostile,
            owner_name=hostile,
            exported_by=hostile,
            status_label=hostile,
            branding=ExportBranding(app_name=hostile),
        )
    )
    assert "<script>" not in html
    assert '<img src="http' not in html
    assert "&lt;script&gt;" in html


def test_sections_are_sanitised_markdown() -> None:
    html = build_html(
        document(
            bodies={
                "problem": (
                    '<script>x</script> <img src="http://169.254.169.254/"> '
                    "![a](file:///etc/passwd) [j](javascript:alert(1)) "
                    '<link rel="stylesheet" href="http://x/">'
                )
            }
        )
    )
    body = html[html.index("<body>") :]
    assert "<script" not in body
    assert "<img" not in body
    assert "<link" not in body
    assert "javascript:" not in body
    assert "file:" not in body
    assert "169.254.169.254" not in body


def test_the_only_urls_are_bundled_fonts_and_the_logo() -> None:
    html = build_html(
        document(
            branding=ExportBranding(app_name="Acme", logo_type="image/png", logo=PNG),
            bodies={"summary": "[link](https://example.com) ![i](https://example.com/i.png)"},
        )
    )
    urls = re.findall(r"url\(\"?([^)\"]*)", html)
    assert urls
    assert all(url.startswith("soundings-font:") for url in urls)
    sources = re.findall(r'src="([^"]*)"', html)
    assert len(sources) == 1
    assert sources[0].startswith("data:image/png;base64,")
    assert "<link" not in html


@pytest.mark.parametrize(
    "color",
    [
        "red",
        "#abc",
        "#1d5fa8;}body{background:url(http://evil/)}",
        "#1d5fa8ff",
        "rgb(0,0,0)",
        "</style><script>x</script>",
        "#GGGGGG",
        "",
        None,
    ],
)
def test_only_validated_hex_colours_reach_the_stylesheet(color: str | None) -> None:
    html = build_html(
        document(
            branding=ExportBranding(
                app_name="Acme",
                primary_color=color,  # type: ignore[arg-type]
                accent_color=color,  # type: ignore[arg-type]
            )
        )
    )
    style = _style(html)
    assert "evil" not in style
    assert "script" not in style
    assert "rgb(" not in style
    for value in re.findall(r"#[0-9A-Za-z]+", style):
        assert re.fullmatch(r"#[0-9a-f]{6}", value), value
    assert DEFAULT_COLOR in style


def test_valid_colours_are_used_lower_cased() -> None:
    style = _style(
        build_html(
            document(
                branding=ExportBranding(
                    app_name="Acme", primary_color="#0B6E4F", accent_color="#7C3AED"
                )
            )
        )
    )
    assert "background: #0b6e4f" in style
    assert "#7c3aed" in style


@pytest.mark.parametrize("font", ["Comic Sans MS", "inter;color:red", "../../etc/passwd", ""])
def test_unknown_fonts_fall_back_to_inter(font: str) -> None:
    css = font_face_css(font)
    assert css == font_face_css("inter")
    assert font not in css or font == ""


def test_each_brand_font_maps_to_fixed_faces_only() -> None:
    assert {font.value for font in BrandFont} == BRAND_FONTS
    for font in BRAND_FONTS:
        css = font_face_css(font)
        names = re.findall(r'url\("soundings-font:([^"]+)"\)', css)
        assert names
        assert all(name in FONT_FILES for name in names)
        assert all(name.startswith((font, "mono-")) for name in names)
        families = set(re.findall(r'font-family: "([^"]+)"', css))
        assert families == {
            "Soundings Brand",
            "Soundings Brand Ext",
            "Soundings Mono",
            "Soundings Mono Ext",
        }


def test_every_font_file_and_licence_is_bundled() -> None:
    for file_name in FONT_FILES.values():
        data = (FONT_DIR / file_name).read_bytes()
        assert data[:4] == b"wOF2", file_name
    for family in (
        "inter",
        "ibm-plex-sans",
        "source-serif-4",
        "atkinson-hyperlegible",
        "ibm-plex-mono",
    ):
        licence = (FONT_DIR / f"{family}-LICENSE.txt").read_text()
        assert "SIL Open Font License" in licence


@pytest.mark.parametrize(
    ("background", "text"),
    [
        ("#1d5fa8", WHITE),
        ("#000000", WHITE),
        ("#ffffff", INK),
        ("#ffd700", INK),
        ("#f59e0b", INK),
        ("#0b6e4f", WHITE),
    ],
)
def test_text_on_the_band_is_chosen_by_contrast(background: str, text: str) -> None:
    assert text_color_on(background) == text
    assert contrast(text, background) >= 4.5


def test_light_brand_colours_are_not_used_for_text_on_white() -> None:
    style = _style(
        build_html(
            document(
                branding=ExportBranding(
                    app_name="Acme", primary_color="#ffd700", accent_color="#ffd700"
                )
            )
        )
    )
    assert ".wordmark {" in style
    wordmark = style[style.index(".wordmark {") : style.index("}", style.index(".wordmark {"))]
    assert INK in wordmark
    assert "#ffd700" in style  # still the band


def test_safe_color() -> None:
    assert safe_color("#ABCDEF") == "#abcdef"
    assert safe_color("abcdef") == DEFAULT_COLOR
    assert safe_color(None, "#000000") == "#000000"


def test_the_cover_shows_the_score_only_when_given() -> None:
    with_score = build_html(document(score=Decimal("4.1"), score_count=5))
    without = build_html(document())
    assert "Aggregate score 4.1 from 5 evaluations" in with_score
    assert "Aggregate score" not in without


def test_a_logo_replaces_the_wordmark() -> None:
    with_logo = build_html(
        document(branding=ExportBranding(app_name="Acme", logo_type="image/png", logo=PNG))
    )
    assert 'class="wordmark"' not in with_logo
    assert 'alt="Acme"' in with_logo
    other = build_html(
        document(branding=ExportBranding(app_name="Acme", logo_type="text/html", logo=b"<b>"))
    )
    assert 'class="wordmark"' in other
    assert "data:" not in other


@pytest.mark.parametrize(("primary", "text"), [("#1d5fa8", WHITE), ("#ffd700", INK)])
def test_the_band_text_colour_follows_the_contrast_rule(primary: str, text: str) -> None:
    style = _style(
        build_html(document(branding=ExportBranding(app_name="Acme", primary_color=primary)))
    )
    band = style[style.index(".cover-band {") : style.index("}", style.index(".cover-band {"))]
    assert f"background: {primary};" in band
    assert f"color: {text};" in band


def test_no_owner_no_author_metadata() -> None:
    assert '<meta name="author"' not in build_html(document(owner_name=None))
    assert '<meta name="author" content="Olive Owner">' in build_html(document())
