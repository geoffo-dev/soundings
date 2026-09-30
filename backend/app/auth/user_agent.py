"""A short, non-identifying summary of a User-Agent header ("Firefox on macOS").

Stored on the session row for a future "your sessions" list instead of the full
header, which is long and fingerprintable.
"""

from __future__ import annotations

__all__ = ["summarise_user_agent"]

# Order matters: Edge and Opera also claim Chrome; Chrome also claims Safari.
_BROWSERS = (
    ("Edg/", "Edge"),
    ("OPR/", "Opera"),
    ("Firefox/", "Firefox"),
    ("Chrome/", "Chrome"),
    ("Chromium/", "Chromium"),
    ("Safari/", "Safari"),
    ("curl/", "curl"),
    ("python-httpx/", "httpx"),
)
_SYSTEMS = (
    ("Android", "Android"),
    ("iPhone", "iOS"),
    ("iPad", "iPadOS"),
    ("Mac OS X", "macOS"),
    ("Macintosh", "macOS"),
    ("Windows", "Windows"),
    ("CrOS", "ChromeOS"),
    ("Linux", "Linux"),
)


def summarise_user_agent(header: str | None) -> str | None:
    if not header:
        return None
    browser = next((name for marker, name in _BROWSERS if marker in header), "Other browser")
    system = next((name for marker, name in _SYSTEMS if marker in header), None)
    return f"{browser} on {system}" if system else browser
