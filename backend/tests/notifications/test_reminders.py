"""Evaluation reminders (contract-phase3 section 3.7), with the worked example: zone
Europe/London, digest hour 08:00, reminder days 2,0."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db import session_scope
from app.email import delivery
from app.email.delivery import Runtime
from app.models.enums import (
    EvaluatorState,
    IdeaStatus,
    NotificationMode,
    NotificationType,
    ProjectRole,
)
from app.models.idea import Idea, IdeaEvaluator
from app.models.project import ProjectMember
from app.notifications.schedule import send_reminders
from tests.factories import add_evaluator, make_idea
from tests.notifications.conftest import SMTP, Clock, Outbox, RecordingTransport, Team, only

LONDON = ZoneInfo("Europe/London")


@pytest.fixture
def settings_overrides() -> dict[str, object]:
    return {**SMTP, "timezone": "Europe/London", "digest_hour": 8, "reminder_days": "2,0"}


def at(day: int, hour: int, minute: int = 0) -> datetime:
    """A time in October 2026 in London (Mon 5 ... Fri 9, Mon 12)."""
    return datetime(2026, 10, day, hour, minute, tzinfo=LONDON)


class Scene:
    def __init__(self, app: FastAPI, settings: Settings, db: AsyncSession, team: Team) -> None:
        self.app, self.settings, self.db, self.team = app, settings, db, team

    async def idea(self, *, due: datetime, invited: datetime, evaluators: int = 1) -> Idea:
        idea = await make_idea(
            self.db, self.team.project, owner=self.team.owner, status=IdeaStatus.EVALUATING
        )
        for evaluator in self.team.evaluators[:evaluators]:
            await add_evaluator(self.db, idea, evaluator)
        await self.db.execute(
            update(IdeaEvaluator).where(IdeaEvaluator.idea_id == idea.id).values(invited_at=invited)
        )
        await self.db.execute(update(Idea).where(Idea.id == idea.id).values(evaluation_due_at=due))
        await self.db.commit()
        return idea

    async def run(self, now: datetime) -> int:
        async with session_scope(self.app.state.sessionmaker) as db:
            return await send_reminders(db, self.settings, now)


@pytest.fixture
def scene(app: FastAPI, settings: Settings, db_session: AsyncSession, team: Team) -> Scene:
    return Scene(app, settings, db_session, team)


async def reminders(outbox: Outbox, team: Team) -> list[tuple[int, str]]:
    notes = await outbox.notifications(team.evaluators[0].id, NotificationType.EVALUATION_REMINDER)
    return [(note.payload["days_before"], note.dedupe_key.rsplit(":", 2)[1]) for note in notes]


async def test_the_worked_example(scene: Scene, outbox: Outbox, team: Team) -> None:
    await scene.idea(due=at(9, 17), invited=at(5, 9))

    assert await scene.run(at(6, 8)) == 0  # Tuesday: nothing
    assert await scene.run(at(7, 7, 59)) == 0  # Wednesday before the hour
    assert await scene.run(at(7, 8)) == 1  # Wednesday 08:00: "due Fri 9 Oct"
    assert await scene.run(at(7, 8, 30)) == 0  # two scans in one hour: one reminder
    assert await scene.run(at(8, 8)) == 0  # Thursday: nothing
    assert await scene.run(at(9, 8)) == 1  # Friday 08:00: "due today"

    assert await reminders(outbox, team) == [(2, "2026-10-09"), (0, "2026-10-09")]
    note = (await outbox.notifications(team.evaluators[0].id))[0]
    assert note.actor_id is None
    assert note.email_mode is NotificationMode.IMMEDIATE


async def test_invited_after_the_two_day_reminder_gets_only_the_due_day_one(
    scene: Scene, outbox: Outbox, team: Team
) -> None:
    await scene.idea(due=at(9, 17), invited=at(8, 10))

    for now in (at(7, 8), at(8, 8), at(9, 8)):
        await scene.run(now)

    assert await reminders(outbox, team) == [(0, "2026-10-09")]


async def test_due_before_the_hour_on_the_day_gets_only_the_earlier_reminder(
    scene: Scene, outbox: Outbox, team: Team
) -> None:
    await scene.idea(due=at(9, 7), invited=at(5, 9))

    for now in (at(7, 8), at(9, 8)):
        await scene.run(now)

    assert await reminders(outbox, team) == [(2, "2026-10-09")]


async def test_a_missed_day_is_not_caught_up(scene: Scene, outbox: Outbox, team: Team) -> None:
    """Worker down Tuesday to Friday 09:00: one "due today", no late "in two days"."""
    await scene.idea(due=at(9, 17), invited=at(5, 9))

    await scene.run(at(9, 9))

    assert await reminders(outbox, team) == [(0, "2026-10-09")]


async def test_a_moved_due_date_follows_the_new_schedule(
    scene: Scene, outbox: Outbox, team: Team, db_session: AsyncSession
) -> None:
    idea = await scene.idea(due=at(12, 17), invited=at(5, 9))
    await db_session.execute(
        update(Idea).where(Idea.id == idea.id).values(evaluation_due_at=at(8, 17))
    )
    await db_session.commit()

    assert await scene.run(at(7, 11)) == 0  # Thursday's 2-day reminder would have been Tuesday
    assert await scene.run(at(8, 8)) == 1

    assert await reminders(outbox, team) == [(0, "2026-10-08")]


async def test_overdue_submitted_removed_demoted_and_closed_get_nothing(
    scene: Scene, outbox: Outbox, team: Team, db_session: AsyncSession
) -> None:
    eve1, eve2, eve3 = team.evaluators
    overdue = await scene.idea(due=at(7, 7), invited=at(5, 9))  # due before the run
    submitted = await make_idea(db_session, team.project, status=IdeaStatus.EVALUATING)
    await add_evaluator(db_session, submitted, eve1, state=EvaluatorState.SUBMITTED)
    closed = await scene.idea(due=at(9, 17), invited=at(5, 9))
    await db_session.execute(
        update(Idea).where(Idea.id == closed.id).values(evaluation_closed_at=at(6, 9))
    )
    demoted = await make_idea(db_session, team.project, status=IdeaStatus.EVALUATING)
    await add_evaluator(db_session, demoted, eve2)
    await db_session.execute(
        update(ProjectMember)
        .where(ProjectMember.user_id == eve2.id, ProjectMember.project_id == team.project.id)
        .values(role=ProjectRole.VIEWER)
    )
    for idea in (submitted, demoted):
        await db_session.execute(
            update(IdeaEvaluator)
            .where(IdeaEvaluator.idea_id == idea.id)
            .values(invited_at=at(5, 9))
        )
        await db_session.execute(
            update(Idea).where(Idea.id == idea.id).values(evaluation_due_at=at(9, 17))
        )
    await db_session.commit()
    assert overdue.id
    assert eve3.id

    assert await scene.run(at(7, 8)) == 0
    assert await scene.run(at(9, 8)) == 0
    assert await outbox.notifications() == []


@pytest.mark.settings(**SMTP, timezone="Europe/London", digest_hour=8, reminder_days="")
async def test_no_reminder_days_no_reminders(scene: Scene, outbox: Outbox) -> None:
    await scene.idea(due=at(9, 17), invited=at(5, 9))

    assert await scene.run(at(9, 8)) == 0


async def test_the_reminder_email_names_the_date(
    scene: Scene,
    outbox: Outbox,
    team: Team,
    runtime: Runtime,
    transport: RecordingTransport,
    clock: Clock,
) -> None:
    await scene.idea(due=at(9, 17), invited=at(5, 9))
    await scene.run(at(7, 8))
    await scene.run(at(9, 8))
    first, second = await outbox.emails(team.evaluators[0].id)

    clock.now = at(7, 8, 1)
    await outbox.set(type(first), first.id, created_at=at(7, 8), next_attempt_at=at(7, 8))
    assert await delivery.send_email(runtime, first.id) == "sent"
    clock.now = at(9, 8, 1)
    await outbox.set(type(second), second.id, created_at=at(9, 8), next_attempt_at=at(9, 8))
    assert await delivery.send_email(runtime, second.id) == "sent"

    early, today = transport.messages
    assert early["Subject"].endswith(" is due Fri 9 Oct")
    assert today["Subject"].endswith(" is due today, Fri 9 Oct")
    body = today.get_body(("plain",))
    assert body is not None
    assert "?evaluate=1" in body.get_content()


async def test_a_reminder_past_its_due_time_is_cancelled(
    scene: Scene, outbox: Outbox, team: Team, runtime: Runtime, clock: Clock
) -> None:
    await scene.idea(due=at(9, 17), invited=at(5, 9))
    await scene.run(at(9, 8))
    email = only(await outbox.emails(team.evaluators[0].id))
    await outbox.set(type(email), email.id, created_at=at(9, 8), next_attempt_at=at(9, 8))

    clock.now = at(9, 17, 1)
    assert await delivery.send_email(runtime, email.id) == "cancelled"
    assert (await outbox.email(email.id)).last_error == "Not sent: no longer applies"
