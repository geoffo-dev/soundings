"""Blind safety of notification content (contract-phase3 section 3.11, role matrix
section 3): no email, digest or inbox item ever carries score data, evaluation
comments or recommendations, for a pending evaluator or for the owner."""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db import session_scope
from app.email import delivery
from app.email.delivery import Runtime
from app.models.base import utcnow
from app.models.enums import NotificationMode, NotificationType
from app.models.idea import Idea, IdeaEvaluator
from app.models.notification import NotificationPreference, OutboundEmail
from app.notifications.schedule import build_digests, send_reminders
from tests.notifications.conftest import AsUser, Outbox, RecordingTransport, Team, ok

pytestmark = pytest.mark.usefixtures("team")

SECRET_REMARK = "Confidential remark: strong numbers on value"
FORBIDDEN_WORDS = r"score|aggregate|disagree|recommend|confidential remark|no-go|\bmaybe\b"


def scores(team: Team, value: int) -> list[dict[str, Any]]:
    return [{"criterion_id": str(c.id), "score": value} for c in team.rubric]


async def build_story(api: AsUser, team: Team, db_session: AsyncSession) -> float:
    """An idea with two submitted evaluations (an aggregate, recommendations and
    comments), a pending third evaluator, and every kind of notification about it."""
    eve1, eve2, eve3 = team.evaluators
    member, admin = await api(team.member), await api(team.admin)
    idea = (await member.create_idea(team.slug, title="Self-service refunds"))["key"]
    # Everyone gets everything immediately, and the member also a digest.
    for user in (team.owner, eve3, team.member):
        db_session.add_all(
            NotificationPreference(user_id=user.id, type=type_, mode=NotificationMode.IMMEDIATE)
            for type_ in (NotificationType.STATUS_CHANGED, NotificationType.COMMENT)
            if user is not team.member
        )
    await db_session.commit()
    ok(await admin.put(f"/ideas/{idea}/owner", {"user_id": str(team.owner.id)}))
    ok(await admin.post(f"/ideas/{idea}/evaluators", {"user_ids": [str(eve1.id), str(eve2.id)]}))
    for user, value, recommendation in ((eve1, 5, "go"), (eve2, 4, "maybe")):
        body = {
            "scores": scores(team, value),
            "recommendation": recommendation,
            "comment": SECRET_REMARK,
            "submit": True,
        }
        ok(await (await api(user)).put(f"/ideas/{idea}/evaluations/me", body))
    aggregate: float = ok(await (await api(team.owner)).get(f"/ideas/{idea}"))["aggregate"][
        "overall"
    ]
    due = (utcnow() + timedelta(days=2)).replace(hour=17, minute=0, second=0, microsecond=0)
    ok(
        await admin.post(
            f"/ideas/{idea}/evaluators", {"user_ids": [str(eve3.id)], "due_at": due.isoformat()}
        )
    )
    ok(await admin.post(f"/ideas/{idea}/status", {"status": "evaluating"}))
    ok(
        await member.post(
            f"/ideas/{idea}/comments",
            {"body_md": f"Thoughts, @[x](user:{team.owner.id}) and @[y](user:{eve3.id})?"},
        ),
        201,
    )
    ok(await member.post(f"/ideas/{idea}/comments", {"body_md": "Another one"}), 201)
    ok(await admin.post(f"/ideas/{idea}/status", {"status": "shortlisted"}))
    return aggregate


async def test_no_email_or_inbox_item_carries_score_data(
    app: FastAPI,
    api: AsUser,
    team: Team,
    db_session: AsyncSession,
    outbox: Outbox,
    runtime: Runtime,
    transport: RecordingTransport,
    settings: Settings,
) -> None:
    aggregate = await build_story(api, team, db_session)
    forbidden = re.compile(FORBIDDEN_WORDS + "|" + re.escape(f"{aggregate:.1f}"), re.IGNORECASE)
    eve3 = team.evaluators[2]
    # A reminder for the pending evaluator (invited "earlier", due today).
    now = utcnow()
    await db_session.execute(
        update(IdeaEvaluator)
        .where(IdeaEvaluator.user_id == eve3.id)
        .values(invited_at=now - timedelta(days=3))
    )
    await db_session.execute(update(Idea).values(evaluation_due_at=now.replace(hour=23, minute=59)))
    await db_session.commit()
    reminder_settings = settings.model_copy(update={"digest_hour": 0, "reminder_days": [0]})
    async with session_scope(app.state.sessionmaker) as db:
        assert await send_reminders(db, reminder_settings, now) == 1
    # And a digest for the member (status changes and comments by default).
    assert await build_digests(app.state.sessionmaker, reminder_settings, now) >= 1

    emails = await outbox.emails()
    for email in emails:
        await delivery.send_email(runtime, email.id)
    sent_types = {
        row.type.value
        for row in await db_session.scalars(
            select(OutboundEmail).execution_options(populate_existing=True)
        )
        if row.sent_at is not None
    }
    assert sent_types >= {
        "owner_assigned",
        "evaluator_invited",
        "evaluation_reminder",
        "evaluations_complete",
        "status_changed",
        "comment",
        "mention",
        "digest",
    }
    for message in transport.messages:
        html = message.get_body(("html",))
        text = message.get_body(("plain",))
        assert html is not None
        assert text is not None
        for content in (str(message["Subject"]), html.get_content(), text.get_content()):
            assert not forbidden.search(content), (message["Subject"], forbidden.search(content))

    for user in (team.owner, eve3, team.member):
        page = (await (await api(user)).get("/me/notifications")).text
        assert page.count('"type"') >= 1
        assert not forbidden.search(page.replace("evaluations_complete", "")), user.display_name
