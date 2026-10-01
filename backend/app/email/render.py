"""Render :class:`~app.email.model.EmailContent` to HTML and plain text with Jinja2.

Templates live in ``app/templates/email`` (shipped in the wheel): ``_layout.html`` /
``_layout.txt`` and one ``<template>.html`` / ``.txt`` pair per email. HTML autoescaping
is on (every value is escaped text; nothing user-written is rendered as HTML or
Markdown); the text templates are not escaped. Undefined variables raise, so a
template bug fails the attempt ("Internal error") instead of sending a broken email.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from app.email.model import DEFAULT_BRANDING, Branding, EmailContent, clean_subject

__all__ = ["TEMPLATES", "TEMPLATE_DIR", "RenderedEmail", "render"]

TEMPLATE_DIR: Final = Path(__file__).resolve().parent.parent / "templates" / "email"

TEMPLATES: Final = (
    "owner_assigned",
    "evaluator_invited",
    "evaluation_reminder",
    "evaluations_complete",
    "status_changed",
    "comment",
    "mention",
    "digest",
    "test",
    "submission_received",
    "submission_status_changed",
)
"""Every email template (``<name>.html`` + ``<name>.txt``)."""

_FONT: Final = "-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica Neue,Arial,sans-serif"

_STYLES: Final = {
    "font": _FONT,
    "h1": "margin:0 0 14px 0;font-size:20px;line-height:1.3;font-weight:600;",
    "p": "margin:0 0 14px 0;font-size:15px;line-height:1.55;",
}


def _colours(brand: Branding) -> dict[str, str]:
    """Light palette (contrast >= 4.5:1 for text on bg, card and panel)."""
    return {
        "bg": "#f4f5f7",
        "card": "#ffffff",
        "panel": "#f6f7f9",
        "border": "#e3e5e8",
        "rule": "#c9ccd1",
        "text": "#1a1a1f",
        "muted": "#5c5f66",
        "link": brand.accent,
    }


@functools.cache
def _environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(
            enabled_extensions=("html",), disabled_extensions=("txt",), default=True
        ),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        auto_reload=False,
    )


@dataclass(frozen=True, slots=True)
class RenderedEmail:
    subject: str
    html: str
    text: str


SIGNATURE_SEPARATOR: Final = "-- "
"""Starts the footer of the text part (RFC 3676 4.3): clients dim it and leave it out
of replies. Its trailing space is kept."""


def _tidy_text(text: str) -> str:
    """At most one blank line in a row; no trailing spaces (but the footer's ``-- ``)."""
    lines = [
        line if line == SIGNATURE_SEPARATOR else line.rstrip() for line in text.strip().splitlines()
    ]
    tidy: list[str] = []
    for line in lines:
        if line or (tidy and tidy[-1]):
            tidy.append(line)
    return "\n".join(tidy) + "\n"


def render(content: EmailContent, branding: Branding = DEFAULT_BRANDING) -> RenderedEmail:
    environment = _environment()
    subject = clean_subject(content.subject)
    context: dict[str, Any] = {
        **content.context,
        "subject": subject,
        "preheader": content.preheader,
        "button": content.button,
        "reason": content.reason,
        "preferences_url": content.preferences_url,
        "unsubscribe_url": content.unsubscribe_url,
        "unsubscribe_label": content.unsubscribe_label,
        "brand": branding,
        "s": _STYLES,
        "c": _colours(branding),
    }
    html = environment.get_template(f"{content.template}.html").render(context)
    text = environment.get_template(f"{content.template}.txt").render(context)
    return RenderedEmail(subject=subject, html=html, text=_tidy_text(text))
