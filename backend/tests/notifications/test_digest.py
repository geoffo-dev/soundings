"""Daily digests and the cleanup (contract-phase3 sections 3.6 and 3.9)."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db import session_scope
from app.email import delivery
from app.email.delivery import Runtime
from app.models.enums import (
    EmailStatus,
    EmailType,
    IdeaStatus,
    NotificationMode,
    NotificationType,
)
from app.models.idea import Idea
from app.models.notification import Notification, NotificationPreference, OutboundEmail
from app.models.project import ProjectMember
from app.models.user import User
from app.notifications.schedule import build_digests, cleanup, run_schedule
from app.notifications.unsubscribe import read_token
from app.schemas.notifications import UnsubscribeScope
from tests.factories import make_idea
from tests.notifications.conftest import SMTP, Clock, Outbox, RecordingTransport, Team, only

LONDON = ZoneInfo("Europe/London")


@pytest.fixture
def settings_overrides() -> dict[str, object]:
    return {**SMTP, "timezone": "Europe/London", "digest_hour": 8, "reminder_days": "2,0"}


def at(month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=LONDON)


MOVE = {
    "from_status": "new",
    "from_resolution": None,
    "to_status": "evaluating",
    "to_resolution": None,
}


async def pending(
    db: AsyncSession,
    user: User,
    idea: Idea,
    created_at: datetime,
    *,
    type_: NotificationType = NotificationType.STATUS_CHANGED,
    actor: User | None = None,
    **values: Any,
) -> Notification:
    note = Notification(
        id=uuid4(),
        user_id=user.id,
        type=type_,
        idea_id=idea.id,
        actor_id=actor.id if actor else None,
        payload=MOVE if type_ is NotificationType.STATUS_CHANGED else {},
        dedupe_key=f"test:{uuid4()}",
        email_mode=NotificationMode.DIGEST,
        created_at=created_at,
        **values,
    )
    db.add(note)
    await db.commit()
    return note


async def digests(app: FastAPI, settings: Settings, now: datetime) -> int:
    return await build_digests(app.state.sessionmaker, settings, now)


async def test_one_digest_per_local_day_at_or_after_the_hour(
    app: FastAPI, settings: Settings, team: Team, db_session: AsyncSession, outbox: Outbox
) -> None:
    idea = await make_idea(db_session, team.project, status=IdeaStatus.EVALUATING)
    first = await pending(db_session, team.member, idea, at(10, 6, 15), actor=team.admin)
    second = await pending(db_session, team.member, idea, at(10, 7, 6), actor=team.owner)

    assert await digests(app, settings, at(10, 7, 7, 59)) == 0  # before the hour
    assert await digests(app, settings, at(10, 7, 11)) == 1  # a missed 08:00 is caught up
    assert await digests(app, settings, at(10, 7, 12)) == 0  # two runs, one email

    email = only(await outbox.emails(team.member.id))
    assert (email.type, email.idempotency_key) == (
        EmailType.DIGEST,
        f"digest:{team.member.id}:2026-10-07",
    )
    assert {note.email_id for note in await outbox.notifications(team.member.id)} == {email.id}
    assert first.id != second.id
    # Something new after today's digest waits for tomorrow's.
    await pending(db_session, team.member, idea, at(10, 7, 13))
    assert await digests(app, settings, at(10, 7, 14)) == 0
    assert await digests(app, settings, at(10, 8, 8)) == 1


async def test_read_turned_off_and_no_longer_viewable_items_are_left_out(
    app: FastAPI, settings: Settings, team: Team, db_session: AsyncSession, outbox: Outbox
) -> None:
    idea = await make_idea(db_session, team.project, status=IdeaStatus.EVALUATING)
    keep = await pending(db_session, team.member, idea, at(10, 7, 1))
    read = await pending(db_session, team.member, idea, at(10, 7, 2), read_at=at(10, 7, 3))
    off = await pending(
        db_session, team.member, idea, at(10, 7, 4), type_=NotificationType.OWNER_ASSIGNED
    )
    db_session.add(
        NotificationPreference(
            user_id=team.member.id,
            type=NotificationType.OWNER_ASSIGNED,
            mode=NotificationMode.OFF,
        )
    )
    outsider_note = await pending(db_session, team.outsider, idea, at(10, 7, 5))  # private
    await db_session.commit()

    assert await digests(app, settings, at(10, 7, 8)) == 1

    modes = {note.id: (note.email_mode, note.email_id) for note in await outbox.notifications()}
    email = only(await outbox.emails())
    assert modes[keep.id] == (NotificationMode.DIGEST, email.id)
    assert modes[read.id] == (NotificationMode.OFF, None)
    assert modes[off.id] == (NotificationMode.OFF, None)
    assert modes[outsider_note.id] == (NotificationMode.OFF, None)


async def test_items_older_than_a_week_are_never_collected(
    app: FastAPI, settings: Settings, team: Team, db_session: AsyncSession, outbox: Outbox
) -> None:
    idea = await make_idea(db_session, team.project)
    await pending(db_session, team.member, idea, at(9, 29, 7))

    assert await digests(app, settings, at(10, 7, 8)) == 0
    assert await outbox.emails() == []


async def test_a_digest_pruned_by_the_cleanup_is_never_sent_again(
    app: FastAPI, settings: Settings, team: Team, db_session: AsyncSession, outbox: Outbox
) -> None:
    """Pruning a sent digest sets its items' email_id back to null; the cleanup turns
    them off in the same run, so they never look pending again."""
    idea = await make_idea(db_session, team.project)
    note = await pending(db_session, team.member, idea, at(9, 1, 7))
    assert await digests(app, settings, at(9, 1, 8)) == 1
    email = only(await outbox.emails())
    await outbox.set(
        OutboundEmail,
        email.id,
        status=EmailStatus.SENT,
        sent_at=at(9, 1, 8),
        next_attempt_at=None,
        updated_at=at(9, 1, 8, 1),
    )

    async with session_scope(app.state.sessionmaker) as db:
        await cleanup(db, at(10, 5, 8))

    assert await outbox.emails() == []
    [after] = await outbox.notifications()
    assert (after.id, after.email_id, after.email_mode) == (note.id, None, NotificationMode.OFF)
    assert await digests(app, settings, at(10, 5, 9)) == 0


async def test_cleanup_prunes_old_rows(
    app: FastAPI, settings: Settings, team: Team, db_session: AsyncSession, outbox: Outbox
) -> None:
    idea = await make_idea(db_session, team.project)
    old = await pending(db_session, team.member, idea, at(6, 1, 9))
    recent = await pending(db_session, team.member, idea, at(10, 1, 9))
    now = at(10, 5, 8)
    for status, age in (
        (EmailStatus.SENT, 31),
        (EmailStatus.CANCELLED, 31),
        (EmailStatus.FAILED, 89),
        (EmailStatus.FAILED, 91),
        (EmailStatus.SENT, 29),
    ):
        when = now - timedelta(days=age)
        await db_session.execute(
            insert(OutboundEmail).values(
                id=uuid4(),
                type=EmailType.TEST,
                status=status,
                recipient_user_id=team.member.id,
                message_id=f"<{uuid4().hex}@testserver>",
                next_attempt_at=None,
                sent_at=when if status is EmailStatus.SENT else None,
                created_at=when,
                updated_at=when,
            )
        )
    await db_session.commit()

    async with session_scope(app.state.sessionmaker) as db:
        await cleanup(db, now)

    left = sorted((row.status.value, (now - row.updated_at).days) for row in await outbox.emails())
    assert left == [("failed", 89), ("sent", 29)]
    assert [note.id for note in await outbox.notifications()] == [recent.id]
    assert old.id


async def test_no_pending_items_no_digest_and_nothing_without_smtp(
    app: FastAPI, settings: Settings, team: Team, db_session: AsyncSession
) -> None:
    assert await digests(app, settings, at(10, 7, 9)) == 0
    idea = await make_idea(db_session, team.project)
    await pending(db_session, team.member, idea, at(10, 7, 7))
    off = settings.model_copy(update={"smtp_host": None, "smtp_from": None})

    assert await digests(app, off, at(10, 7, 9)) == 0


@pytest.mark.parametrize(
    ("before", "after"),
    [
        # Sunday 25 October 2026: clocks go back at 02:00 BST; 08:00 local is 08:00 UTC.
        (datetime(2026, 10, 25, 7, 59, tzinfo=UTC), datetime(2026, 10, 25, 8, 0, tzinfo=UTC)),
        # The day before (BST): 08:00 local is 07:00 UTC.
        (datetime(2026, 10, 24, 6, 59, tzinfo=UTC), datetime(2026, 10, 24, 7, 0, tzinfo=UTC)),
    ],
)
async def test_the_digest_hour_follows_daylight_saving_time(
    app: FastAPI,
    settings: Settings,
    team: Team,
    db_session: AsyncSession,
    before: datetime,
    after: datetime,
) -> None:
    idea = await make_idea(db_session, team.project)
    await pending(db_session, team.member, idea, before - timedelta(hours=3))

    assert await digests(app, settings, before) == 0
    assert await digests(app, settings, after) == 1


async def test_the_digest_email(
    app: FastAPI,
    settings: Settings,
    team: Team,
    db_session: AsyncSession,
    outbox: Outbox,
    runtime: Runtime,
    transport: RecordingTransport,
    clock: Clock,
) -> None:
    one = await make_idea(db_session, team.project, title="Refunds <b>now</b>")
    two = await make_idea(db_session, team.project, title="Faster onboarding")
    await pending(db_session, team.member, one, at(10, 6, 9), actor=team.admin)
    await pending(db_session, team.member, two, at(10, 6, 10), actor=team.owner)
    await pending(db_session, team.member, one, at(10, 6, 11), actor=team.owner)
    await digests(app, settings, at(10, 7, 8))
    email = only(await outbox.emails())
    clock.now = at(10, 7, 8, 1)

    assert await delivery.send_email(runtime, email.id) == "sent"

    message = only(transport.messages)
    assert message["Subject"] == "Soundings digest: 3 updates on 2 ideas"
    assert message["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    text_part = message.get_body(("plain",))
    html_part = message.get_body(("html",))
    assert text_part is not None
    assert html_part is not None
    text = text_part.get_content()
    assert "Ada Admin moved it from New to Evaluating" in text
    assert text.index("Refunds <b>now</b>") < text.index("Faster onboarding")  # newest first
    html = html_part.get_content()
    assert "Refunds &lt;b&gt;now&lt;/b&gt;" in html
    assert "<b>now</b>" not in html
    # The digest's link turns off the digest's types; only "all email" turns off all.
    links = dict(re.findall(r"^Unsubscribe from (the daily digest|all email): (\S+)$", text, re.M))
    scopes = {
        label: read_token(settings, parse_qs(urlsplit(url).query)["token"][0])
        for label, url in links.items()
    }
    assert {label: found and found.scope for label, found in scopes.items()} == {
        "the daily digest": UnsubscribeScope.DIGEST,
        "all email": UnsubscribeScope.ALL,
    }


async def test_a_digest_older_than_two_days_is_cancelled(
    app: FastAPI,
    settings: Settings,
    team: Team,
    db_session: AsyncSession,
    outbox: Outbox,
    runtime: Runtime,
    clock: Clock,
) -> None:
    idea = await make_idea(db_session, team.project)
    await pending(db_session, team.member, idea, at(10, 6, 9))
    await digests(app, settings, at(10, 7, 8))
    email = only(await outbox.emails())
    clock.now = at(10, 9, 8, 1)
    await outbox.set(OutboundEmail, email.id, next_attempt_at=clock.now)

    assert await delivery.send_email(runtime, email.id) == "cancelled"
    assert (await outbox.email(email.id)).last_error == "Not sent: out of date"


async def test_a_digest_whose_ideas_are_all_gone_is_cancelled(
    app: FastAPI,
    settings: Settings,
    team: Team,
    db_session: AsyncSession,
    outbox: Outbox,
    runtime: Runtime,
    clock: Clock,
) -> None:
    idea = await make_idea(db_session, team.project)
    await pending(db_session, team.member, idea, at(10, 6, 9))
    await digests(app, settings, at(10, 7, 8))
    email = only(await outbox.emails())
    await db_session.execute(
        update(User).where(User.id == team.member.id).values(is_platform_admin=False)
    )
    await db_session.execute(delete(ProjectMember).where(ProjectMember.user_id == team.member.id))
    await db_session.commit()
    clock.now = at(10, 7, 8, 1)

    assert await delivery.send_email(runtime, email.id) == "cancelled"
    assert (await outbox.email(email.id)).last_error == "Not sent: nothing left to send"


async def test_the_hourly_job_runs_reminders_digests_and_cleanup(
    app: FastAPI, settings: Settings, team: Team, db_session: AsyncSession
) -> None:
    idea = await make_idea(db_session, team.project)
    await pending(db_session, team.member, idea, at(10, 7, 7))

    result = await run_schedule(app.state.sessionmaker, settings, at(10, 7, 8, 5))
    assert (result.digests, result.cleaned) == (1, True)
    later = await run_schedule(app.state.sessionmaker, settings, at(10, 7, 9, 5))
    assert (later.digests, later.cleaned) == (0, True)
    assert await db_session.scalar(select(OutboundEmail.id)) is not None


async def test_a_run_that_misses_the_digest_hour_still_cleans_up(
    app: FastAPI, settings: Settings, team: Team, db_session: AsyncSession, outbox: Outbox
) -> None:
    """Review nit: the cleanup ran only in a run whose local hour was the digest hour,
    so a late run (or a day whose digest hour falls in a DST gap) skipped it."""
    idea = await make_idea(db_session, team.project)
    old = await pending(db_session, team.member, idea, at(6, 1, 9))

    result = await run_schedule(app.state.sessionmaker, settings, at(10, 7, 9, 40))

    assert result.cleaned
    assert old.id not in [note.id for note in await outbox.notifications()]
