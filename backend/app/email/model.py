"""What an email says, independent of how it is rendered.

:class:`EmailContent` is built from the current data at send time
(:mod:`app.email.content`) or from sample data (:mod:`app.email.preview`), and rendered
by :mod:`app.email.render` with the shared branded layout. Everything in it is plain
text (titles, names, excerpts): the HTML templates escape it.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, tzinfo
from typing import Any, Final
from urllib.parse import quote, urlencode

from app.models.enums import NotificationType
from app.notifications.excerpt import shorten

__all__ = [
    "DEFAULT_BRANDING",
    "SYSTEM_FONT_STACK",
    "TYPE_LABELS",
    "Branding",
    "Button",
    "EmailContent",
    "IdeaInfo",
    "Links",
    "clean_subject",
    "format_day",
    "format_moment",
    "one_line",
    "plural",
    "subject_title",
]

SUBJECT_TITLE_LENGTH: Final = 80
_HEX_COLOUR: Final = re.compile(r"#(?:[0-9A-Fa-f]{3}|[0-9A-Fa-f]{6})")

TYPE_LABELS: Final[Mapping[NotificationType, str]] = {
    NotificationType.OWNER_ASSIGNED: "owner assignments",
    NotificationType.EVALUATOR_INVITED: "evaluation requests",
    NotificationType.EVALUATION_REMINDER: "evaluation reminders",
    NotificationType.EVALUATIONS_COMPLETE: "“all evaluations are in” emails",
    NotificationType.STATUS_CHANGED: "status changes",
    NotificationType.COMMENT: "new comments",
    NotificationType.MENTION: "mentions",
    NotificationType.RESEARCHER_ASSIGNED: "research requests",
    NotificationType.RESEARCH_REMINDER: "research reminders",
}
""""Unsubscribe from <label>" in an email's footer."""


SYSTEM_FONT_STACK: Final = (
    "-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica Neue,Arial,sans-serif"
)
_FONT_STACK: Final = re.compile(r"[A-Za-z0-9 ,'-]{1,200}")
"""Font family names, commas, spaces and single quotes only: nothing that can end the
inline ``font-family`` declaration (``;``, ``:``, ``(``, ``"``, ``<``...)."""


@dataclass(frozen=True, slots=True)
class Branding:
    """The product name, colours, font and footer of every email: the effective
    branding (``app.services.branding``: global for staff, the project's for public
    submitters). Accent text must keep >= 4.5:1 contrast on the accent, and ``link``
    on the white card."""

    product_name: str = "Soundings"
    accent: str = "#1d5fa8"
    accent_text: str = "#ffffff"
    footer_text: str | None = None
    link: str | None = None
    """Links in the body; ``None``: the accent."""
    font_stack: str = SYSTEM_FONT_STACK

    def __post_init__(self) -> None:
        # Colours go into inline CSS and bgcolor attributes, where HTML escaping
        # doesn't stop "#fff;background:url(...)": only hex colours are accepted.
        for colour in (self.accent, self.accent_text, self.link or self.accent):
            if not _HEX_COLOUR.fullmatch(colour):
                raise ValueError(
                    f"branding colours must be a hex colour such as #1d5fa8: {colour!r}"
                )
        if not _FONT_STACK.fullmatch(self.font_stack):
            raise ValueError(f"not a plain font stack: {self.font_stack!r}")

    @property
    def initial(self) -> str:
        return (self.product_name.strip()[:1] or "S").upper()

    @property
    def link_colour(self) -> str:
        return self.link or self.accent

    @property
    def footer_lines(self) -> list[str]:
        """The footer's lines (up to 5, as saved), or the default line."""
        if self.footer_text:
            lines = [line for line in self.footer_text.splitlines() if line.strip()]
            if lines:
                return lines
        return [f"Sent by {self.product_name}."]


DEFAULT_BRANDING: Final = Branding()


@dataclass(frozen=True, slots=True)
class Button:
    label: str
    url: str


@dataclass(frozen=True, slots=True)
class IdeaInfo:
    """The idea as an email shows it: key, title, project, status label and link."""

    key: str
    title: str
    project: str
    status: str
    url: str


@dataclass(frozen=True, slots=True)
class EmailContent:
    """One email, ready to render: ``template`` names ``<template>.html`` / ``.txt`` in
    ``app/templates/email``; ``context`` holds the template's own fields."""

    template: str
    subject: str
    preheader: str
    context: Mapping[str, Any] = field(default_factory=dict)
    button: Button | None = None
    reason: str | None = None
    preferences_url: str | None = None
    unsubscribe_url: str | None = None
    unsubscribe_label: str | None = None
    unsubscribe_all_url: str | None = None
    """"Unsubscribe from all email": the only link whose token turns off every type."""
    stop_url: str | None = None
    """"Stop these emails" in the footer: where the recipient turns these emails off
    without an unsubscribe token (a public submitter's tracking page)."""
    list_unsubscribe_url: str | None = None
    """``List-Unsubscribe`` (with ``List-Unsubscribe-Post: List-Unsubscribe=One-Click``)."""
    references: str | None = None
    """``References: <idea-<id>@host>``, so clients thread one idea's emails."""


class Links:
    """Absolute links into the app (``settings.public_base_url``)."""

    def __init__(self, base_url: str) -> None:
        self.base = base_url.rstrip("/")

    def idea(
        self,
        key: str,
        *,
        evaluate: bool = False,
        comment_id: object = None,
        research: bool = False,
    ) -> str:
        url = f"{self.base}/ideas/{quote(key)}"
        if evaluate:
            url += "?evaluate=1"
        elif research:  # Phase 8b: open the idea at its Research panel
            url += "?research=1"
        if comment_id is not None:
            url += f"#comment-{quote(str(comment_id))}"
        return url

    def inbox(self) -> str:
        return f"{self.base}/notifications"

    def preferences(self) -> str:
        return f"{self.base}/settings/notifications"

    def unsubscribe_page(self, token: str) -> str:
        return f"{self.base}/unsubscribe?{urlencode({'token': token})}"

    def unsubscribe_api(self, token: str) -> str:
        return f"{self.base}/api/v1/unsubscribe?{urlencode({'token': token})}"

    def home(self) -> str:
        return f"{self.base}/"


_LINE_BREAKS: Final = re.compile("[\\x00-\\x1f\\x7f-\\x9f\\u2028\\u2029]+")
"""Control characters (C0, DEL, C1 such as NEL) and the Unicode line and paragraph
separators: each can start a new line in a text part or a header."""
_BIDI_CONTROLS: Final = re.compile("[\\u061c\\u202a-\\u202e\\u2066-\\u2069]")
"""Bidirectional embeddings, overrides and isolates: they can reorder the text around a
value (a reversed link or name)."""


def one_line(text: str) -> str:
    """``text`` without line breaks, control characters or bidi controls (each break
    becomes a space): every value an email shows is one line of plain text."""
    return _BIDI_CONTROLS.sub("", _LINE_BREAKS.sub(" ", text))


def clean_subject(subject: str) -> str:
    """No line breaks or control characters in a header (no header injection)."""
    return " ".join(one_line(subject).split())


def subject_title(title: str) -> str:
    """An idea title for a subject line: one line, at most 80 characters."""
    return shorten(clean_subject(title), SUBJECT_TITLE_LENGTH)


def plural(count: int, singular: str, plural_form: str | None = None) -> str:
    return f"{count} {singular if count == 1 else plural_form or singular + 's'}"


def format_day(moment: datetime, tz: tzinfo, *, now: datetime | None = None) -> str:
    """``Fri 9 Oct`` in the instance time zone (with the year when it isn't this year)."""
    local = moment.astimezone(tz)
    text = f"{local:%a} {local.day} {local:%b}"
    if now is not None and now.astimezone(tz).year != local.year:
        text += f" {local.year}"
    return text


def format_moment(
    moment: datetime, tz: tzinfo, zone_name: str, *, now: datetime | None = None
) -> str:
    """``Fri 9 Oct, 17:00 (Europe/London)``."""
    local = moment.astimezone(tz)
    return f"{format_day(moment, tz, now=now)}, {local:%H:%M} ({zone_name})"
