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
    "TYPE_LABELS",
    "Branding",
    "Button",
    "EmailContent",
    "IdeaInfo",
    "Links",
    "clean_subject",
    "format_day",
    "format_moment",
    "plural",
    "subject_title",
]

SUBJECT_TITLE_LENGTH: Final = 80

TYPE_LABELS: Final[Mapping[NotificationType, str]] = {
    NotificationType.OWNER_ASSIGNED: "owner assignments",
    NotificationType.EVALUATOR_INVITED: "evaluation requests",
    NotificationType.EVALUATION_REMINDER: "evaluation reminders",
    NotificationType.EVALUATIONS_COMPLETE: "“all evaluations are in” emails",
    NotificationType.STATUS_CHANGED: "status changes",
    NotificationType.COMMENT: "new comments",
    NotificationType.MENTION: "mentions",
}
""""Unsubscribe from <label>" in an email's footer."""


@dataclass(frozen=True, slots=True)
class Branding:
    """The product name, colours and footer line of every email. Phase 4's branding
    profiles replace :data:`DEFAULT_BRANDING` (accent text must keep >= 4.5:1 contrast on
    the accent)."""

    product_name: str = "Soundings"
    accent: str = "#1d5fa8"
    accent_text: str = "#ffffff"
    footer_text: str | None = None

    @property
    def initial(self) -> str:
        return (self.product_name.strip()[:1] or "S").upper()


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
    list_unsubscribe_url: str | None = None
    """``List-Unsubscribe`` (with ``List-Unsubscribe-Post: List-Unsubscribe=One-Click``)."""
    references: str | None = None
    """``References: <idea-<id>@host>``, so clients thread one idea's emails."""


class Links:
    """Absolute links into the app (``settings.public_base_url``)."""

    def __init__(self, base_url: str) -> None:
        self.base = base_url.rstrip("/")

    def idea(self, key: str, *, evaluate: bool = False, comment_id: object = None) -> str:
        url = f"{self.base}/ideas/{quote(key)}"
        if evaluate:
            url += "?evaluate=1"
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


_CONTROL: Final = re.compile("[\\x00-\\x1f\\x7f\\u2028\\u2029]+")


def clean_subject(subject: str) -> str:
    """No line breaks or control characters in a header (no header injection)."""
    return " ".join(_CONTROL.sub(" ", subject).split())


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
