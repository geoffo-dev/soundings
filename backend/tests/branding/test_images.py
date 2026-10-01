"""Uploaded logos and favicons (contract-phase4 section 3.11, ADR 0012): the bytes
decide; PNGs are decoded defensively and re-encoded; SVGs are parsed with expat against
an allow-list (no DOCTYPE, scripts, styles, hrefs, ``use``, reference chains or
rendering bombs) and stored re-serialised. Every refusal is a quick 422
``invalid_image``: nothing is rendered and nothing recurses."""

from __future__ import annotations

import io
import time
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from PIL import Image

from app.errors import ProblemError
from app.models.enums import BrandAssetKind
from app.services.brand_assets import (
    PNG_MAX_SIDE,
    SVG_MAX_DEPTH,
    SVG_MAX_ELEMENTS,
    SVG_REFERENCE_BUDGET,
    check_image,
)
from tests.branding.images import (
    FIGMA_LOGO,
    SVG_NS,
    encoded,
    png,
    png_bomb,
    png_header_only,
    png_with_metadata,
    svg,
)

LOGO = BrandAssetKind.LOGO
FAVICON = BrandAssetKind.FAVICON


@contextmanager
def refused(match: str | None = None, *, within: float = 1.0) -> Iterator[None]:
    """The check refuses with 422 invalid_image, quickly (no render, no recursion)."""
    started = time.perf_counter()
    with pytest.raises(ProblemError) as caught:
        yield
    elapsed = time.perf_counter() - started
    assert caught.value.status == 422
    assert caught.value.code == "invalid_image"
    if match is not None:
        assert match.lower() in (caught.value.detail or "").lower(), caught.value.detail
    assert elapsed < within, f"took {elapsed:.2f}s"


# --- PNG ---------------------------------------------------------------------------------
def test_a_png_is_re_encoded_with_its_size() -> None:
    checked = check_image(png((64, 32)), LOGO)

    assert checked.content_type == "image/png"
    assert (checked.width, checked.height) == (64, 32)
    with Image.open(io.BytesIO(checked.data)) as image:
        assert image.format == "PNG"
        assert image.size == (64, 32)


def test_metadata_is_stripped() -> None:
    original = png_with_metadata()
    assert b"tEXt" in original or b"iTXt" in original
    assert b"eXIf" in original
    assert b"iCCP" in original

    data = check_image(original, LOGO).data

    for chunk in (b"tEXt", b"iTXt", b"zTXt", b"eXIf", b"iCCP"):
        assert chunk not in data, chunk
    assert b"51.5007" not in data
    with Image.open(io.BytesIO(data)) as image:
        assert "exif" not in image.info
        assert "Comment" not in image.info


def test_trailing_data_is_dropped() -> None:
    """A polyglot (a PNG with an HTML page or a ZIP after IEND) comes back as a PNG only."""
    polyglot = png() + b"<html><script>alert(1)</script></html>PK\x03\x04"

    data = check_image(polyglot, LOGO).data

    assert b"<script>" not in data
    assert data.endswith(b"IEND\xaeB`\x82")


@pytest.mark.parametrize(
    ("size", "kind", "ok"),
    [
        ((PNG_MAX_SIDE[LOGO], PNG_MAX_SIDE[LOGO]), LOGO, True),
        ((PNG_MAX_SIDE[LOGO] + 1, 10), LOGO, False),
        ((10, PNG_MAX_SIDE[LOGO] + 1), LOGO, False),
        ((PNG_MAX_SIDE[FAVICON], PNG_MAX_SIDE[FAVICON]), FAVICON, True),
        ((PNG_MAX_SIDE[FAVICON] + 1, 16), FAVICON, False),
    ],
)
def test_pixel_limits(size: tuple[int, int], kind: BrandAssetKind, ok: bool) -> None:
    data = png(size, "L", colour=0)
    if ok:
        assert (check_image(data, kind).width, check_image(data, kind).height) == size
    else:
        with refused("pixels"):
            check_image(data, kind)


def test_a_4096_square_png_is_refused() -> None:
    with refused():
        check_image(png((4096, 4096), "1", colour=0), LOGO)


@pytest.mark.parametrize(
    "data",
    [
        png_header_only(100_000, 100_000),  # far over 2x MAX_IMAGE_PIXELS
        png_header_only(30_000, 30_000),
        png_bomb(2_896, 2_896),  # between 1x and 2x MAX_IMAGE_PIXELS (a warning only)
        png_bomb(4_000, 1_100),
    ],
)
def test_decompression_bombs_are_refused_before_decoding(data: bytes) -> None:
    with refused():
        check_image(data, LOGO)


def test_a_truncated_png_is_refused() -> None:
    data = png((300, 200), "RGB", colour=(1, 2, 3))
    noisy = Image.effect_noise((300, 200), 64).convert("RGB")
    out = io.BytesIO()
    noisy.save(out, format="PNG")
    for broken in (data[: len(data) // 2], out.getvalue()[: len(out.getvalue()) // 2]):
        with refused():
            check_image(broken, LOGO)


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(b"", id="empty"),
        pytest.param(b"<!DOCTYPE html><html><script>alert(1)</script></html>", id="html"),
        pytest.param(b"<html><body onload=alert(1)></body></html>", id="html-no-doctype"),
        pytest.param(encoded("GIF"), id="gif"),
        pytest.param(encoded("JPEG"), id="jpeg"),
        pytest.param(encoded("WEBP"), id="webp"),
        pytest.param(encoded("ICO", sizes=[(16, 16)]), id="ico"),
        pytest.param(encoded("BMP"), id="bmp"),
        pytest.param(b"\x89PNG\r\n\x1a\n" + b"\0" * 64, id="png-signature-only"),
        pytest.param(b"GIF89a" + png(), id="gif-header-png-body"),
        pytest.param(b"%PDF-1.7\n", id="pdf"),
        pytest.param(b"\xef\xbb\xbf   ", id="bom-only"),
    ],
)
def test_anything_but_png_or_svg_is_refused(data: bytes) -> None:
    with refused():
        check_image(data, LOGO)


# --- SVG: what is accepted ---------------------------------------------------------------
def test_a_figma_export_round_trips_with_a_default_namespace() -> None:
    checked = check_image(FIGMA_LOGO, LOGO)

    text = checked.data.decode("utf-8")
    assert checked.content_type == "image/svg+xml"
    assert (checked.width, checked.height) == (120, 32)
    assert text.startswith('<?xml version="1.0" encoding="UTF-8"?>\n<svg xmlns="' + SVG_NS + '"')
    assert "ns0:" not in text
    assert "xmlns:" not in text
    assert "<!--" not in text  # comments are dropped
    for kept in (
        'clip-path="url(#clip0_1_2)"',
        'fill="url(#paint0_linear_1_2)"',
        "<linearGradient",
        "<clipPath",
        "<title>Acme &amp; Co</title>",
        'xml:space="preserve"',
        "<tspan",
        'transform="rotate(45 6 16)"',
    ):
        assert kept in text, kept
    # Checking the stored bytes again changes nothing (idempotent).
    assert check_image(checked.data, LOGO).data == checked.data


def test_size_comes_from_width_and_height() -> None:
    checked = check_image(svg("<path d='M0 0h1v1z'/>", attrs='viewBox="0 0 300 100"'), LOGO)
    assert (checked.width, checked.height) == (24, 24)


def test_size_falls_back_to_the_view_box_or_none() -> None:
    view_box = f'<svg xmlns="{SVG_NS}" viewBox="0 0 300.5 100"><rect width="1" height="1"/></svg>'
    sized = check_image(view_box.encode(), LOGO)
    assert (sized.width, sized.height) == (300, 100)

    bare = f'<svg xmlns="{SVG_NS}" width="100%"><rect width="1" height="1"/></svg>'
    unsized = check_image(bare.encode(), LOGO)
    assert (unsized.width, unsized.height) == (None, None)


def test_text_is_escaped_when_stored() -> None:
    data = svg("<text>a &lt;script&gt; &amp; <![CDATA[<b>x</b>]]></text>")

    text = check_image(data, LOGO).data.decode()

    assert "<script" not in text
    assert "<b>" not in text
    assert "&lt;script&gt; &amp; &lt;b&gt;x&lt;/b&gt;" in text


def test_a_reference_fan_out_within_the_budget_is_fine() -> None:
    shapes = "".join(f'<rect x="{i}" width="1" height="1"/>' for i in range(50))
    users = "".join(f'<rect y="{i}" width="1" height="1" mask="url(#m)"/>' for i in range(100))
    checked = check_image(svg(f'<defs><mask id="m">{shapes}</mask></defs>{users}'), LOGO)
    assert checked.content_type == "image/svg+xml"


# --- SVG: what is refused ----------------------------------------------------------------
BILLION_LAUGHS = b"""<?xml version="1.0"?>
<!DOCTYPE lolz [
 <!ENTITY lol "lol">
 <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
 <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
 <!ENTITY lol9 "&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;">
]>
<svg xmlns="http://www.w3.org/2000/svg"><text>&lol9;</text></svg>"""

EXTERNAL_ENTITY = b"""<?xml version="1.0"?>
<!DOCTYPE svg [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<svg xmlns="http://www.w3.org/2000/svg"><text>&xxe;</text></svg>"""

UNUSED_ENTITY = b"""<!DOCTYPE svg [<!ENTITY a "b">]>
<svg xmlns="http://www.w3.org/2000/svg"><rect width="1" height="1"/></svg>"""

PLAIN_DOCTYPE = b"""<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN"
  "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">
<svg xmlns="http://www.w3.org/2000/svg"><rect width="1" height="1"/></svg>"""


def _nested(depth: int) -> bytes:
    return svg("<g>" * depth + "<rect width='1' height='1'/>" + "</g>" * depth)


def _mask_chain(links: int) -> bytes:
    masks = '<mask id="m0"><rect width="9" height="9" fill="white"/></mask>' + "".join(
        f'<mask id="m{i}"><rect width="9" height="9" mask="url(#m{i - 1})"/>'
        f'<rect width="9" height="9" mask="url(#m{i - 1})"/></mask>'
        for i in range(1, links)
    )
    return svg(f"<defs>{masks}</defs><rect width='9' height='9' mask='url(#m{links - 1})'/>")


def _clip_chain(links: int) -> bytes:
    clips = '<clipPath id="c0"><rect width="9" height="9"/></clipPath>' + "".join(
        f'<clipPath id="c{i}" clip-path="url(#c{i - 1})"><rect width="9" height="9"/></clipPath>'
        for i in range(1, links)
    )
    return svg(f"<defs>{clips}</defs><rect width='9' height='9' clip-path='url(#c{links - 1})'/>")


def _fan_out(shapes: int, users: int) -> bytes:
    inner = "".join(f'<rect x="{i}" width="1" height="1"/>' for i in range(shapes))
    outer = "".join(f'<rect y="{i}" width="1" height="1" mask="url(#m)"/>' for i in range(users))
    return svg(f'<defs><mask id="m">{inner}</mask></defs>{outer}')


@pytest.mark.parametrize(
    ("data", "why"),
    [
        pytest.param(svg("<script>alert(1)</script>"), "script", id="script"),
        pytest.param(svg("<rect width='1' height='1' onload='alert(1)'/>"), "onload", id="onload"),
        pytest.param(svg("", attrs="onload='alert(1)'"), "onload", id="root-onload"),
        pytest.param(
            svg("<foreignObject><div xmlns='http://www.w3.org/1999/xhtml'>x</div></foreignObject>"),
            "foreignObject",
            id="foreignObject",
        ),
        pytest.param(svg("<image href='http://169.254.169.254/x'/>"), "image", id="image-href"),
        pytest.param(
            svg(
                "<a xlink:href='javascript:alert(1)'><rect width='1' height='1'/></a>",
                attrs="xmlns:xlink='http://www.w3.org/1999/xlink'",
            ),
            "a",
            id="a-javascript",
        ),
        pytest.param(
            svg(
                "<linearGradient id='g' xlink:href='#h'/>",
                attrs="xmlns:xlink='http://www.w3.org/1999/xlink'",
            ),
            "href",
            id="xlink-href",
        ),
        pytest.param(svg("<linearGradient id='g' href='#h'/>"), "href", id="href"),
        pytest.param(svg("<rect id='r'/><use href='#r'/>"), "use", id="use"),
        pytest.param(svg("<symbol id='s'><rect/></symbol>"), "symbol", id="symbol"),
        pytest.param(
            svg("<rect width='1' height='1' style='background:url(http://evil.test/x)'/>"),
            "style",
            id="style-attribute",
        ),
        pytest.param(svg("<style>rect{fill:url(http://evil.test)}</style>"), "style", id="style"),
        pytest.param(
            svg("", prolog='<?xml-stylesheet href="http://evil.test/a.css"?>'),
            "processing instruction",
            id="xml-stylesheet",
        ),
        pytest.param(svg("<?foo bar?><rect/>"), "processing instruction", id="pi-inside"),
        pytest.param(PLAIN_DOCTYPE, "DOCTYPE", id="doctype"),
        pytest.param(BILLION_LAUGHS, "DOCTYPE", id="billion-laughs"),
        pytest.param(EXTERNAL_ENTITY, "DOCTYPE", id="external-entity"),
        pytest.param(UNUSED_ENTITY, "DOCTYPE", id="internal-entity-unused"),
        pytest.param(svg("<text>&undefined;</text>"), None, id="undefined-entity"),
        pytest.param(svg("<pattern id='p'/>"), "pattern", id="pattern"),
        pytest.param(svg("<marker id='m'/>"), "marker", id="marker"),
        pytest.param(svg("<filter id='f'/>"), "filter", id="filter"),
        pytest.param(svg("<animate attributeName='x'/>"), "animate", id="animate"),
        pytest.param(svg("<set attributeName='x' to='1'/>"), "set", id="set"),
        pytest.param(svg("<switch><rect/></switch>"), "switch", id="switch"),
        pytest.param(
            svg("<sodipodi:namedview xmlns:sodipodi='http://sodipodi.sourceforge.net/DTD'/>"),
            "namespace",
            id="foreign-element",
        ),
        pytest.param(
            svg("<g inkscape:label='Layer' xmlns:inkscape='http://www.inkscape.org/namespaces/'/>"),
            "inkscape",
            id="foreign-attribute",
        ),
        pytest.param(b"<svg><rect width='1' height='1'/></svg>", "namespace", id="no-namespace"),
        pytest.param(f'<html xmlns="{SVG_NS}"><rect/></html>'.encode(), "html", id="root-not-svg"),
        pytest.param(svg("<rect fill='url(http://evil.test/x)'/>"), "url", id="remote-url"),
        pytest.param(svg("<rect fill='url(#missing)'/>"), "missing", id="dangling-url"),
        pytest.param(
            svg("<rect id='r' width='1' height='1'/><rect fill='url(#r)'/>"),
            "gradient",
            id="fill-not-a-gradient",
        ),
        pytest.param(svg("<rect fill='\\75rl(http://evil.test)'/>"), "fill", id="css-escape"),
        pytest.param(svg("<rect fill='image(http://evil.test)'/>"), "image", id="css-image"),
        pytest.param(svg("<rect width='expression(alert(1))'/>"), "width", id="expression"),
        pytest.param(svg("<rect cursor='url(x.cur)'/>"), "cursor", id="cursor"),
        pytest.param(svg("<rect filter='url(#f)'/>"), "filter", id="filter-attribute"),
        pytest.param(svg("<rect id='a'/><rect id='a'/>"), "id", id="duplicate-id"),
        pytest.param(_mask_chain(16), "mask", id="mask-chain"),
        pytest.param(_clip_chain(16), "clip", id="clip-path-chain"),
        pytest.param(
            svg(
                "<defs><linearGradient id='g'><stop stop-color='red'/></linearGradient>"
                "<mask id='m'><rect fill='url(#g)'/></mask></defs><rect mask='url(#m)'/>"
            ),
            "mask",
            id="gradient-inside-mask",
        ),
        pytest.param(_fan_out(1_000, 990), None, id="fan-out-1000x990"),
        pytest.param(_fan_out(10, 995), "references", id="fan-out-10x995"),
        pytest.param(_fan_out(100, 100), "references", id="fan-out-100x100"),
        pytest.param(
            svg("<rect width='1' height='1'/>" * SVG_MAX_ELEMENTS), "elements", id="2001-elements"
        ),
        pytest.param(_nested(SVG_MAX_DEPTH), "deep", id="33-levels"),
        pytest.param(_nested(100_000), "deep", id="100000-levels"),
        pytest.param(b"<svg xmlns='" + SVG_NS.encode() + b"'><rect", None, id="truncated"),
        pytest.param(svg("<text>a\x00b</text>"), None, id="nul"),
        pytest.param(svg("<rect/>") + b"<svg/>", None, id="junk-after-root"),
    ],
)
def test_svgs_outside_the_allow_list_are_refused(data: bytes, why: str | None) -> None:
    with refused(why):
        check_image(data, LOGO)


def test_the_limits_are_the_contracts() -> None:
    assert (SVG_MAX_ELEMENTS, SVG_MAX_DEPTH, SVG_REFERENCE_BUDGET) == (2_000, 32, 10_000)
    assert PNG_MAX_SIDE == {LOGO: 2_048, FAVICON: 512}


def test_just_within_the_element_and_depth_limits_is_fine() -> None:
    # The root counts: 1 + 1,999 rects.
    check_image(svg("<rect width='1' height='1'/>" * (SVG_MAX_ELEMENTS - 1)), LOGO)
    check_image(_nested(SVG_MAX_DEPTH - 2), LOGO)  # svg > 30 g > rect = 32 levels
