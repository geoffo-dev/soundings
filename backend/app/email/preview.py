"""``soundings email-preview``: render every email with sample data to files, for
reviewing templates in browsers and mail clients (no database, SMTP or settings needed).

Writes ``<template>.html``, ``<template>.txt`` and an ``index.html`` linking them.
"""

from __future__ import annotations

import html
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final
from uuid import UUID

from app.email.model import (
    DEFAULT_BRANDING,
    TYPE_LABELS,
    Button,
    EmailContent,
    IdeaInfo,
    Links,
    format_day,
    format_moment,
)
from app.email.render import TEMPLATES, render
from app.models.enums import NotificationType

__all__ = ["sample_contents", "write_previews"]

_ZONE: Final = UTC
_ZONE_NAME: Final = "UTC"
_NOW: Final = datetime(2026, 10, 7, 8, 0, tzinfo=UTC)
_DUE: Final = datetime(2026, 10, 9, 17, 0, tzinfo=UTC)
_COMMENT: Final = UUID("3e9d2c71-6b4a-4f1e-8d0c-5a7b9e2f1c46")


def sample_contents(base_url: str = "http://localhost:8000") -> dict[str, EmailContent]:
    """One sample :class:`EmailContent` per template."""
    links = Links(base_url)
    idea = IdeaInfo(
        key="CUST-12",
        title="Self-service refunds for orders under €50",
        project="Customer Innovation",
        status="Evaluating",
        url=links.idea("CUST-12"),
    )
    other = IdeaInfo(
        key="OPS-4",
        title="Pick-path optimisation in the north warehouse",
        project="Operations",
        status="Shortlisted",
        url=links.idea("OPS-4"),
    )
    token = "sample-token.preview-only"  # noqa: S105 - not a secret

    def footer(type_: NotificationType, reason: str) -> dict[str, str]:
        return {
            "reason": reason,
            "preferences_url": links.preferences(),
            "unsubscribe_url": links.unsubscribe_page(token),
            "unsubscribe_label": TYPE_LABELS[type_],
        }

    evaluate = Button("Evaluate", links.idea(idea.key, evaluate=True))
    open_idea = Button("Open the idea", idea.url)
    excerpt = (
        "Love this. @Carol Chen, could finance confirm the refund ceiling? We'd also want "
        "the fraud checks <script> & friends to stay in place."
    )
    day, moment = format_day(_DUE, _ZONE, now=_NOW), format_moment(_DUE, _ZONE, _ZONE_NAME)
    return {
        "owner_assigned": EmailContent(
            template="owner_assigned",
            subject=f'[CUST-12] You\'re now the owner of "{idea.title}"',
            preheader="Alice Admin made you the owner of CUST-12.",
            context={"actor": "Alice Admin", "idea": idea},
            button=open_idea,
            **footer(NotificationType.OWNER_ASSIGNED, "You're the owner of CUST-12."),
        ),
        "evaluator_invited": EmailContent(
            template="evaluator_invited",
            subject=f'[CUST-12] Please evaluate "{idea.title}" by {day}',
            preheader=f"Bob Baker asked you to evaluate CUST-12 by {day}.",
            context={"actor": "Bob Baker", "idea": idea, "due": moment},
            button=evaluate,
            **footer(NotificationType.EVALUATOR_INVITED, "You're evaluating CUST-12."),
        ),
        "evaluation_reminder": EmailContent(
            template="evaluation_reminder",
            subject=f'[CUST-12] Reminder: your evaluation of "{idea.title}" is due {day}',
            preheader=f"Your evaluation of CUST-12 is due {day}.",
            context={"idea": idea, "due": moment, "due_day": day, "due_today": False},
            button=evaluate,
            **footer(NotificationType.EVALUATION_REMINDER, "You're evaluating CUST-12."),
        ),
        "evaluations_complete": EmailContent(
            template="evaluations_complete",
            subject=f'[CUST-12] All 3 evaluations are in for "{idea.title}"',
            preheader="All 3 evaluations are in for CUST-12.",
            context={"idea": idea, "count": 3},
            button=open_idea,
            **footer(NotificationType.EVALUATIONS_COMPLETE, "You're the owner of CUST-12."),
        ),
        "status_changed": EmailContent(
            template="status_changed",
            subject=f'[CUST-12] "{idea.title}" moved to Shortlisted',
            preheader="Bob Baker moved CUST-12 from Evaluating to Shortlisted.",
            context={
                "actor": "Bob Baker",
                "idea": idea,
                "from_label": "Evaluating",
                "to_label": "Shortlisted",
            },
            button=open_idea,
            **footer(NotificationType.STATUS_CHANGED, "You watch CUST-12."),
        ),
        "comment": EmailContent(
            template="comment",
            subject=f'[CUST-12] Bob Baker commented on "{idea.title}"',
            preheader=excerpt[:120],
            context={"actor": "Bob Baker", "idea": idea, "excerpt": excerpt},
            button=Button("Reply", links.idea(idea.key, comment_id=_COMMENT)),
            **footer(NotificationType.COMMENT, "You watch CUST-12."),
        ),
        "mention": EmailContent(
            template="mention",
            subject=f'[CUST-12] Bob Baker mentioned you on "{idea.title}"',
            preheader=excerpt[:120],
            context={"actor": "Bob Baker", "idea": idea, "excerpt": excerpt},
            button=Button("Reply", links.idea(idea.key, comment_id=_COMMENT)),
            **footer(NotificationType.MENTION, "You were mentioned in a comment on CUST-12."),
        ),
        "digest": EmailContent(
            template="digest",
            subject="Soundings digest: 4 updates on 2 ideas",
            preheader="4 updates on 2 ideas you follow.",
            context={
                "summary": "4 updates on 2 ideas you follow.",
                "groups": [
                    {
                        "idea": idea,
                        "lines": [
                            "Bob Baker moved it from New to Evaluating",
                            f"Dan Diaz commented: “{excerpt[:90]}…”",
                        ],
                    },
                    {
                        "idea": other,
                        "lines": [
                            "Erin Evans moved it from Evaluating to Shortlisted",
                            "Carol Chen commented: “Shall we pilot it in October?”",
                        ],
                    },
                ],
                "more": 0,
                "inbox_url": links.inbox(),
            },
            button=Button("Open your inbox", links.inbox()),
            reason="You get one email a day with updates you chose to receive as a digest.",
            preferences_url=links.preferences(),
            unsubscribe_url=links.unsubscribe_page(token),
            unsubscribe_label="the daily digest",
        ),
        "test": EmailContent(
            template="test",
            subject="Soundings test email",
            preheader="Email from Soundings works.",
            context={
                "base_url": base_url,
                "sent_by": "Alice Admin",
                "sent_at": format_moment(_NOW - timedelta(minutes=1), _ZONE, _ZONE_NAME),
            },
            reason="An administrator sent this to check the email settings.",
        ),
        "submission_received": EmailContent(
            template="submission_received",
            subject='We received your idea: "Recycle packaging at the till"',
            preheader="Thanks for your idea for Customer Innovation.",
            context={
                "title": "Recycle packaging at the till",
                "project": "Customer Innovation",
                "key": "CUST-31",
                "tracking_url": None,
            },
            reason="You submitted an idea to Customer Innovation.",
        ),
        "submission_status_changed": EmailContent(
            template="submission_status_changed",
            subject='Your idea "Recycle packaging at the till" moved to Shortlisted',
            preheader="Your idea is now Shortlisted.",
            context={
                "title": "Recycle packaging at the till",
                "project": "Customer Innovation",
                "status": "Shortlisted",
                "tracking_url": None,
            },
            reason="You asked for updates on an idea you submitted to Customer Innovation.",
        ),
    }


def write_previews(directory: Path, base_url: str = "http://localhost:8000") -> list[Path]:
    """Render every template to ``directory``; returns the files written."""
    directory.mkdir(parents=True, exist_ok=True)
    contents = sample_contents(base_url)
    missing = set(TEMPLATES) - set(contents)
    if missing:  # pragma: no cover - guarded by tests
        raise RuntimeError(f"no sample for {sorted(missing)}")
    written: list[Path] = []
    rows: list[str] = []
    for name in TEMPLATES:
        rendered = render(contents[name], DEFAULT_BRANDING)
        html_path = directory / f"{name}.html"
        text_path = directory / f"{name}.txt"
        html_path.write_text(rendered.html, encoding="utf-8")
        text_path.write_text(f"Subject: {rendered.subject}\n\n{rendered.text}", encoding="utf-8")
        written += [html_path, text_path]
        rows.append(
            f'<li><a href="{name}.html">{html.escape(name)}</a> '
            f'(<a href="{name}.txt">text</a>): {html.escape(rendered.subject)}</li>'
        )
    index = directory / "index.html"
    index.write_text(
        '<!DOCTYPE html><html lang="en"><meta charset="utf-8"><title>Email previews</title>'
        '<body style="font-family:system-ui,sans-serif;margin:2rem"><h1>Email previews</h1><ul>'
        + "".join(rows)
        + "</ul></body></html>\n",
        encoding="utf-8",
    )
    written.append(index)
    return written
