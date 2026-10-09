"""Phase 8b research reminders (contract-phase8b section 6.3), with the worked example:
zone Europe/London, digest hour 08:00, reminder days 2,0.

Bob is asked Mon 09:00, due Fri 17:00 -> Wed 08:00 and Fri 08:00. Asked Thu 10:00 for the
same date -> Fri only. Bob answers the last required item Thu -> nothing on Fri. Bob hands
back Wed 10:00 -> the owner gets Fri 08:00 (as owner). Nobody assigned and no due date ->
no reminders. Plus every stop condition, dedupe across scans, a DST change, and the email.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from sqlalchemy import delete, event, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db import session_scope
from app.email import delivery
from app.email.delivery import Runtime
from app.models.enums import (
    IdeaStatus,
    NotificationMode,
    NotificationType,
    ProjectVisibility,
    ResearchStep,
)
from app.models.idea import Idea
from app.models.project import Project, ProjectMember
from app.models.research import ResearchChecklistItem
from app.models.user import User
from app.notifications.schedule import send_research_reminders
from tests.factories import make_idea
from tests.notifications.conftest import SMTP, Clock, Outbox, RecordingTransport, Team, only
from tests.research.conftest import answer, set_step

LONDON = ZoneInfo("Europe/London")
REMINDER = NotificationType.RESEARCH_REMINDER


@pytest.fixture
def settings_overrides() -> dict[str, object]:
    return {**SMTP, "timezone": "Europe/London", "digest_hour": 8, "reminder_days": "2,0"}


def at(day: int, hour: int, minute: int = 0, month: int = 10) -> datetime:
    """A time in October 2026 in London (Mon 5 ... Fri 9, Mon 12)."""
    return datetime(2026, month, day, hour, minute, tzinfo=LONDON)


class Scene:
    def __init__(self, app: FastAPI, settings: Settings, db: AsyncSession, team: Team) -> None:
        self.app, self.settings, self.db, self.team = app, settings, db, team
        self.items: list[ResearchChecklistItem] = []

    async def idea(
        self,
        *,
        due: datetime | None,
        researcher: User | None,
        asked: datetime | None = None,
        status: IdeaStatus = IdeaStatus.RESEARCH,
        step: ResearchStep = ResearchStep.BEFORE_EVALUATION,
    ) -> Idea:
        self.items = await set_step(self.db, self.team.project, step)
        idea = await make_idea(self.db, self.team.project, owner=self.team.owner, status=status)
        await self.set(
            idea,
            researcher_id=researcher.id if researcher else None,
            research_assigned_at=asked if researcher else None,
            research_due_at=due,
        )
        return idea

    async def set(self, idea: Idea, **values: Any) -> None:
        await self.db.execute(update(Idea).where(Idea.id == idea.id).values(**values))
        await self.db.commit()

    async def answer_all(self, idea: Idea) -> None:
        for item in self.items:
            if item.required:
                await answer(self.db, idea, item, self.team.owner)

    async def run(self, now: datetime) -> int:
        async with session_scope(self.app.state.sessionmaker, settings=self.settings) as db:
            return await send_research_reminders(db, self.settings, now)


@pytest.fixture
def scene(app: FastAPI, settings: Settings, db_session: AsyncSession, team: Team) -> Scene:
    return Scene(app, settings, db_session, team)


async def reminders(outbox: Outbox, user: User) -> list[tuple[int, str, bool]]:
    notes = await outbox.notifications(user.id, REMINDER)
    return [
        (note.payload["days_before"], note.dedupe_key.rsplit(":", 2)[1], note.payload["as_owner"])
        for note in notes
    ]


async def test_the_worked_example(scene: Scene, outbox: Outbox, team: Team) -> None:
    await scene.idea(due=at(9, 17), researcher=team.member, asked=at(5, 9))

    assert await scene.run(at(6, 8)) == 0  # Tuesday: nothing
    assert await scene.run(at(7, 7, 59)) == 0  # Wednesday before the hour
    assert await scene.run(at(7, 8)) == 1  # Wednesday 08:00
    assert await scene.run(at(7, 8, 30)) == 0  # two scans in one hour: one reminder
    assert await scene.run(at(8, 8)) == 0  # Thursday: nothing
    assert await scene.run(at(9, 8)) == 1  # Friday 08:00: "due today"
    assert await scene.run(at(9, 9)) == 0  # a restarted worker repeats nothing

    assert await reminders(outbox, team.member) == [
        (2, "2026-10-09", False),
        (0, "2026-10-09", False),
    ]
    note = (await outbox.notifications(team.member.id, REMINDER))[0]
    assert note.actor_id is None
    assert note.email_mode is NotificationMode.IMMEDIATE
    assert await outbox.notifications(team.owner.id, REMINDER) == []


async def test_asked_after_the_two_day_reminder_gets_only_the_due_day_one(
    scene: Scene, outbox: Outbox, team: Team
) -> None:
    await scene.idea(due=at(9, 17), researcher=team.member, asked=at(8, 10))

    for now in (at(7, 8), at(8, 8), at(8, 11), at(9, 8)):
        await scene.run(now)

    assert await reminders(outbox, team.member) == [(0, "2026-10-09", False)]


async def test_asked_on_the_day_after_the_hour_gets_none(
    scene: Scene, outbox: Outbox, team: Team
) -> None:
    """``fire(n) > research_assigned_at``: "Asked to research" already gave the date."""
    await scene.idea(due=at(9, 17), researcher=team.member, asked=at(9, 8, 30))

    await scene.run(at(9, 9))

    assert await reminders(outbox, team.member) == []


async def test_answering_the_last_required_item_stops_them(
    scene: Scene, outbox: Outbox, team: Team
) -> None:
    idea = await scene.idea(due=at(9, 17), researcher=team.member, asked=at(5, 9))
    await scene.run(at(7, 8))
    await scene.answer_all(idea)

    assert await scene.run(at(9, 8)) == 0

    assert await reminders(outbox, team.member) == [(2, "2026-10-09", False)]


async def test_handed_back_the_owner_gets_the_rest(
    scene: Scene, outbox: Outbox, team: Team
) -> None:
    idea = await scene.idea(due=at(9, 17), researcher=team.member, asked=at(5, 9))
    await scene.run(at(7, 8))
    await scene.set(idea, researcher_id=None, research_assigned_at=None)  # Wed 10:00

    await scene.run(at(9, 8))

    assert await reminders(outbox, team.member) == [(2, "2026-10-09", False)]
    assert await reminders(outbox, team.owner) == [(0, "2026-10-09", True)]


async def test_nobody_assigned_and_no_due_date_no_reminders(
    scene: Scene, outbox: Outbox, team: Team
) -> None:
    await scene.idea(due=None, researcher=None)

    for now in (at(7, 8), at(9, 8)):
        assert await scene.run(now) == 0


async def test_the_owner_with_a_due_date_and_nobody_assigned(
    scene: Scene, outbox: Outbox, team: Team
) -> None:
    await scene.idea(due=at(9, 17), researcher=None)

    await scene.run(at(7, 8))
    await scene.run(at(9, 8))

    assert await reminders(outbox, team.owner) == [
        (2, "2026-10-09", True),
        (0, "2026-10-09", True),
    ]


async def test_a_moved_due_date_follows_the_new_schedule(
    scene: Scene, outbox: Outbox, team: Team
) -> None:
    idea = await scene.idea(due=at(12, 17), researcher=team.member, asked=at(5, 9))
    await scene.set(idea, research_due_at=at(8, 17))

    assert await scene.run(at(7, 11)) == 0
    assert await scene.run(at(8, 8)) == 1

    assert await reminders(outbox, team.member) == [(0, "2026-10-08", False)]


@pytest.mark.parametrize(
    "stop",
    [
        "past_research",
        "closed",
        "step_off",
        "due_cleared",
        "due_passed",
        "archived",
        "held",
        "reassigned_after",
        "researcher_deactivated",
    ],
)
async def test_every_stop_condition(
    scene: Scene, outbox: Outbox, team: Team, db_session: AsyncSession, stop: str
) -> None:
    idea = await scene.idea(due=at(9, 17), researcher=team.member, asked=at(5, 9))
    now = at(9, 8)
    if stop == "past_research":
        await scene.set(idea, status=IdeaStatus.EVALUATING)
    elif stop == "closed":
        await scene.set(idea, status=IdeaStatus.CLOSED, resolution="parked")
    elif stop == "step_off":
        await db_session.execute(
            update(Project)
            .where(Project.id == team.project.id)
            .values(research_step=ResearchStep.OFF)
        )
        await db_session.commit()
    elif stop == "due_cleared":
        await scene.set(idea, research_due_at=None)
    elif stop == "due_passed":
        now = at(9, 18)
        await scene.set(idea, research_due_at=at(9, 7))
    elif stop == "archived":
        await db_session.execute(
            update(Project).where(Project.id == team.project.id).values(archived_at=at(8, 9))
        )
        await db_session.commit()
    elif stop == "held":
        await scene.set(idea, held_for="moderation")
    elif stop == "reassigned_after":
        await scene.set(idea, researcher_id=team.evaluators[0].id, research_assigned_at=at(9, 8, 1))
        now = at(9, 8, 30)
    else:
        await db_session.execute(
            update(User).where(User.id == team.member.id).values(is_active=False)
        )
        await db_session.commit()

    assert await scene.run(now) == 0


@pytest.mark.parametrize("visibility", [ProjectVisibility.PRIVATE, ProjectVisibility.INTERNAL])
async def test_an_owner_who_lost_their_role_gets_none(
    scene: Scene, outbox: Outbox, team: Team, db_session: AsyncSession, visibility: str
) -> None:
    """Review S3: they may no longer answer it (internal projects included)."""
    await db_session.execute(
        update(Project).where(Project.id == team.project.id).values(visibility=visibility)
    )
    await scene.idea(due=at(9, 17), researcher=None)
    await db_session.execute(
        delete(ProjectMember).where(
            ProjectMember.project_id == team.project.id, ProjectMember.user_id == team.owner.id
        )
    )
    await db_session.commit()

    assert await scene.run(at(9, 8)) == 0


async def test_a_guest_researcher_is_reminded(scene: Scene, outbox: Outbox, team: Team) -> None:
    await scene.idea(due=at(9, 17), researcher=team.outsider, asked=at(5, 9))

    assert await scene.run(at(9, 8)) == 1

    assert await reminders(outbox, team.outsider) == [(0, "2026-10-09", False)]


async def test_across_the_clocks_going_back(scene: Scene, outbox: Outbox, team: Team) -> None:
    """Due Tue 27 Oct 17:00 GMT; the clocks go back at 02:00 on Sun 25 Oct, the two-day
    reminder's day: it fires at 08:00 GMT (not 08:00 BST, an hour earlier in UTC)."""
    await scene.idea(due=at(27, 17), researcher=team.member, asked=at(19, 9))

    assert await scene.run(at(24, 8)) == 0
    assert await scene.run(at(25, 7, 59)) == 0
    assert await scene.run(at(25, 8)) == 1
    assert await scene.run(at(27, 8)) == 1

    assert await reminders(outbox, team.member) == [
        (2, "2026-10-27", False),
        (0, "2026-10-27", False),
    ]


async def test_the_reminder_email(
    scene: Scene,
    outbox: Outbox,
    team: Team,
    runtime: Runtime,
    transport: RecordingTransport,
    clock: Clock,
) -> None:
    await scene.idea(due=at(9, 17), researcher=None)
    await scene.run(at(9, 8))
    clock.now = at(9, 8, 5)

    email = only(await outbox.emails(team.owner.id))
    await delivery.send_email(runtime, email.id)

    message = only(transport.messages)
    assert str(message["Subject"]).endswith('" is due today, Fri 9 Oct')
    assert "Reminder: research for" in str(message["Subject"])
    text = message.get_body(("plain",))
    assert text is not None
    content = text.get_content()
    assert "You own" in content
    assert "2 required items" in content
    assert "?research=1" in content


async def test_the_hourly_scan_skips_in_sql_what_it_wouldnt_remind(
    scene: Scene, outbox: Outbox, team: Team, db_session: AsyncSession
) -> None:
    """8b code review N4: ideas in the due window that are past Research, have nothing
    required open, aren't due on a reminder day or were reminded since today's hour cost
    the scan nothing beyond its one query."""
    past = await scene.idea(due=at(9, 17), researcher=team.member, asked=at(5, 9))
    await scene.set(past, status=IdeaStatus.EVALUATING)
    done = await scene.idea(due=at(9, 17), researcher=team.member, asked=at(5, 9))
    await scene.answer_all(done)
    await scene.idea(due=at(8, 17), researcher=team.member, asked=at(5, 9))  # Thu: no day
    due = await scene.idea(due=at(9, 17), researcher=team.member, asked=at(5, 9))
    statements: list[str] = []

    def count(*args: Any, **_: Any) -> None:
        statements.append(str(args[2]))

    engine = db_session.bind.sync_engine  # type: ignore[union-attr]
    event.listen(engine, "before_cursor_execute", count)
    try:
        assert await scene.run(at(7, 8)) == 1  # Wednesday 08:00: only ``due``
        first = len(statements)
        statements.clear()
        assert await scene.run(at(7, 9)) == 0  # an hour later: already reminded
        again = list(statements)
    finally:
        event.remove(engine, "before_cursor_execute", count)

    assert [n.idea_id for n in await outbox.notifications(team.member.id, REMINDER)] == [due.id]
    assert first >= 1
    assert len(again) == 1, again  # the scan's own query, nothing per idea
