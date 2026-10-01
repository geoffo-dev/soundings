"""Sample images for the branding tests: PNGs built with Pillow and SVG snippets."""

from __future__ import annotations

import io
import zlib
from struct import pack
from typing import Any

from PIL import Image, PngImagePlugin

SVG_NS = "http://www.w3.org/2000/svg"

FIGMA_LOGO = b"""<?xml version="1.0" encoding="UTF-8"?>
<!-- Generator: Figma -->
<svg width="120" height="32" viewBox="0 0 120 32" fill="none"
     xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">
<title>Acme &amp; Co</title>
<g clip-path="url(#clip0_1_2)">
<path d="M10 4h20v24H10z" fill="url(#paint0_linear_1_2)"/>
<rect x="40" y="8" width="70" height="16" rx="4" fill="#1D5FA8" fill-opacity=".9"/>
<circle cx="6" cy="16" r="3" fill="rgb(11, 110, 79)" transform="rotate(45 6 16)"/>
<text x="44" y="20" font-family="'IBM Plex Sans', sans-serif" font-size="12" fill="white"
      xml:space="preserve">Acme <tspan font-weight="600">Ideas</tspan></text>
</g>
<defs>
<linearGradient id="paint0_linear_1_2" x1="10" y1="4" x2="30" y2="28"
                gradientUnits="userSpaceOnUse">
<stop stop-color="#0B6E4F"/>
<stop offset="1" stop-color="#F59E0B"/>
</linearGradient>
<clipPath id="clip0_1_2">
<rect width="120" height="32" fill="white"/>
</clipPath>
</defs>
</svg>
"""


def svg(body: str, *, attrs: str = "", prolog: str = "") -> bytes:
    """``body`` inside an ``<svg>`` root in the SVG namespace."""
    return (f'{prolog}<svg xmlns="{SVG_NS}" width="24" height="24" {attrs}>{body}</svg>').encode()


def png(
    size: tuple[int, int] = (64, 32),
    mode: str = "RGBA",
    *,
    colour: Any = (29, 95, 168, 255),
    **save: Any,
) -> bytes:
    image = Image.new(mode, size, colour)
    out = io.BytesIO()
    image.save(out, format="PNG", **save)
    return out.getvalue()


def png_with_metadata() -> bytes:
    """A PNG carrying text chunks (a comment, a GPS-ish description), EXIF and an ICC
    profile, as phones and editors write them."""
    info = PngImagePlugin.PngInfo()
    info.add_text("Comment", "secret location 51.5007,-0.1246")
    info.add_itxt("Description", "taken at home")
    exif = Image.Exif()
    exif[0x010E] = "GPS 51.5007 -0.1246"  # ImageDescription
    return png(pnginfo=info, exif=exif.tobytes(), icc_profile=b"\0" * 128)


def encoded(fmt: str, size: tuple[int, int] = (16, 16), **save: Any) -> bytes:
    """An image in another format (GIF, JPEG, WEBP, ICO, BMP)."""
    image = Image.new("RGB", size, (200, 30, 30))
    out = io.BytesIO()
    image.save(out, format=fmt, **save)
    return out.getvalue()


def _chunk(kind: bytes, data: bytes) -> bytes:
    return pack(">I", len(data)) + kind + data + pack(">I", zlib.crc32(kind + data))


def png_header_only(width: int, height: int) -> bytes:
    """A PNG signature and IHDR claiming ``width`` x ``height`` (no pixel data): a
    decompression bomb's header, built without allocating anything."""
    ihdr = pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IEND", b"")


def png_bomb(width: int, height: int) -> bytes:
    """A real, tiny (all-zero, 1-bit) PNG of ``width`` x ``height`` pixels."""
    raw = b"".join(b"\x00" + b"\x00" * ((width + 7) // 8) for _ in range(height))
    ihdr = pack(">IIBBBBB", width, height, 1, 0, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(raw, 9))
        + _chunk(b"IEND", b"")
    )
