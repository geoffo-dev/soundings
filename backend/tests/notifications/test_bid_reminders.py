"""Phase 10 bid assessment reminders (contract-phase10 section 11), with a worked example:
zone Europe/London, digest hour 08:00, reminder days 2,0.

Carol (Technical) is assigned Mon 09:00 and the assessments are due Fri 17:00 -> Wed 08:00
(2 days before) and Fri 08:00 (on the day). Sven (Delivery) is assigned Thu 10:00 -> Fri
only (his "Asked to assess bids" gave the date). Carol submits both bids Thu -> nothing on
Fri for her. Plus every stop condition (not assessing, closed or held idea, archived
project, an assessor who left the private project, only rejected bids left, another due
date), dedupe across scans and the email.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db import session_scope
from app.email import delivery
from app.email.delivery import Runtime
from app.models.base import utcnow
from app.models.bid import Bid, BidCall, BidSectionAssessor
from app.models.enums import (
    BidCallStatus,
    BidStatus,
    EmailStatus,
    HoldReason,
    IdeaStatus,
    NotificationType,
    Resolution,
)
from app.models.idea import Idea
from app.models.project import Project, ProjectMember
from app.models.user import User
from app.notifications.bids import send_assessment_reminders
from tests.bids.conftest import (
    Crew,
    add_bid,
    assign,
    open_call,
    qualify,
    sections_by_title,
    start,
    submit,
    to_assessing,
)
from tests.notifications.conftest import SMTP, AsUser, Outbox, RecordingTransport, ok, only

LONDON = ZoneInfo("Europe/London")
REMINDER = NotificationType.ASSESSMENT_REMINDER


@pytest.fixture
def settings_overrides() -> dict[str, object]:
    return {**SMTP, "timezone": "Europe/London", "digest_hour": 8, "reminder_days": "2,0"}


def at(day: int, hour: int, minute: int = 0) -> datetime:
    """A time in October 2026 in London (Mon 5 ... Fri 9)."""
    return datetime(2026, 10, day, hour, minute, tzinfo=LONDON)


class Scene:
    """A call being assessed on the crew's idea: two qualified bids, Carol on Technical and
    Sven on Delivery, due ``due``; each assignment's time set in the database."""

    def __init__(self, app: FastAPI, settings: Settings, db: AsyncSession, crew: Crew) -> None:
        self.app, self.settings, self.db, self.crew = app, settings, db, crew
        self.view: dict[str, Any] = {}
        self.bids: list[dict[str, Any]] = []

    async def build(self, api: AsUser, *, due: datetime, assigned: dict[User, datetime]) -> None:
        crew = self.crew
        owner = await api(crew.owner)
        await start(owner, crew)
        view = await open_call(owner, crew)
        for name in ("Northwind Data Ltd", "Tessellate Software"):
            bid = await add_bid(owner, crew, name, price="1000.00")
            await qualify(self.db, bid["id"], crew.owner)
            self.bids.append(bid)
        self.view = await assign(
            owner, crew, view, {"Technical": [crew.tech1], "Delivery": [crew.delivery]}
        )
        await to_assessing(owner, crew)
        await self.set_call(assessment_due_at=due)
        for user, when in assigned.items():
            await self.db.execute(
                update(BidSectionAssessor)
                .where(
                    BidSectionAssessor.call_id == self.call_id,
                    BidSectionAssessor.user_id == user.id,
                )
                .values(assigned_at=when)
            )
        await self.db.commit()

    @property
    def call_id(self) -> UUID:
        return UUID(self.view["call"]["id"])

    async def set_call(self, **values: Any) -> None:
        await self.db.execute(update(BidCall).where(BidCall.id == self.call_id).values(**values))
        await self.db.commit()

    async def set_idea(self, **values: Any) -> None:
        await self.db.execute(update(Idea).where(Idea.id == self.crew.idea.id).values(**values))
        await self.db.commit()

    async def run(self, now: datetime) -> int:
        async with session_scope(self.app.state.sessionmaker, settings=self.settings) as db:
            return await send_assessment_reminders(db, self.settings, now)


@pytest.fixture
def scene(app: FastAPI, settings: Settings, db_session: AsyncSession, crew: Crew) -> Scene:
    return Scene(app, settings, db_session, crew)


async def reminders(outbox: Outbox, user: User) -> list[tuple[int, str]]:
    notes = await outbox.notifications(user.id, REMINDER)
    return [(note.payload["days_before"], note.dedupe_key.rsplit(":", 2)[1]) for note in notes]


async def test_the_worked_example(
    scene: Scene, api: AsUser, outbox: Outbox, crew: Crew, db_session: AsyncSession
) -> None:
    await scene.build(api, due=at(9, 17), assigned={crew.tech1: at(5, 9), crew.delivery: at(8, 10)})

    assert await scene.run(at(6, 8)) == 0  # Tuesday: nothing
    assert await scene.run(at(7, 7, 59)) == 0  # Wednesday before the hour
    assert await scene.run(at(7, 8)) == 1  # Carol; Sven isn't assigned yet
    assert await scene.run(at(7, 9)) == 0  # the next hour: already reminded
    assert await reminders(outbox, crew.tech1) == [(2, "2026-10-09")]
    assert await reminders(outbox, crew.delivery) == []
    note = only(await outbox.notifications(crew.tech1.id, REMINDER))
    assert note.actor_id is None
    assert set(note.payload) == {"call_id", "due_at", "days_before"}

    # Thursday: Carol submits Technical for both bids.
    tech = await api(crew.tech1)
    technical = sections_by_title(scene.view)["Technical"]
    for bid in scene.bids:
        await submit(tech, crew, bid["id"], technical, 4)
    assert await scene.run(at(8, 8)) == 0

    # Friday: Sven only (assigned Thursday, before Friday's hour); Carol owes nothing.
    assert await scene.run(at(9, 8)) == 1
    assert await reminders(outbox, crew.delivery) == [(0, "2026-10-09")]
    assert await reminders(outbox, crew.tech1) == [(2, "2026-10-09")]
    assert await scene.run(at(9, 17, 1)) == 0  # after the due time
    items = ok(await (await api(crew.delivery)).get("/me/notifications"))["items"]
    reminder = next(i for i in items if i["type"] == "assessment_reminder")
    assert reminder["call"]["title"] == "Data platform build"
    assert reminder["days_before"] == 0
    assert reminder["due_at"].startswith("2026-10-09T16:00:00")  # 17:00 BST in UTC
    del db_session


@pytest.mark.parametrize(
    "stop",
    [
        "call_open",
        "call_awarded",
        "idea_closed",
        "idea_held",
        "project_archived",
        "left_project",
        "bids_rejected",
        "another_date",
        "nothing_owed",
    ],
)
async def test_every_stop_condition(
    scene: Scene, api: AsUser, crew: Crew, db_session: AsyncSession, stop: str
) -> None:
    await scene.build(api, due=at(9, 17), assigned={crew.tech1: at(5, 9), crew.delivery: at(5, 9)})
    match stop:
        case "call_open":
            await scene.set_call(status=BidCallStatus.OPEN)
        case "call_awarded":
            await scene.set_call(status=BidCallStatus.AWARDED, awarded_at=utcnow())
        case "idea_closed":
            await scene.set_idea(status=IdeaStatus.CLOSED, resolution=Resolution.PARKED)
        case "idea_held":
            await scene.set_idea(held_for=HoldReason.MODERATION)
        case "project_archived":
            await db_session.execute(
                update(Project).where(Project.id == crew.project.id).values(archived_at=utcnow())
            )
            await db_session.commit()
        case "left_project":
            await db_session.execute(
                delete(ProjectMember).where(
                    ProjectMember.project_id == crew.project.id,
                    ProjectMember.user_id.in_([crew.tech1.id, crew.delivery.id]),
                )
            )
            await db_session.commit()
        case "bids_rejected":
            await db_session.execute(
                update(Bid)
                .where(Bid.call_id == scene.call_id)
                .values(
                    status=BidStatus.REJECTED,
                    rejected_at=utcnow(),
                    rejected_by_id=crew.owner.id,
                    rejection_reason="Out.",
                )
            )
            await db_session.commit()
        case "another_date":
            await scene.set_call(assessment_due_at=at(10, 17))
        case "nothing_owed":
            for user, title in ((crew.tech1, "Technical"), (crew.delivery, "Delivery")):
                who = await api(user)
                section = sections_by_title(scene.view)[title]
                for bid in scene.bids:
                    await submit(who, crew, bid["id"], section, 3)
    assert await scene.run(at(7, 8)) == 0


async def test_the_reminder_email(
    app: FastAPI,
    api: AsUser,
    crew: Crew,
    db_session: AsyncSession,
    outbox: Outbox,
    runtime: Runtime,
    transport: RecordingTransport,
    settings: Settings,
) -> None:
    """With the real clock (the send-time check reads it): due the day after tomorrow."""
    scene = Scene(
        app, settings.model_copy(update={"timezone": "UTC", "digest_hour": 0}), db_session, crew
    )
    now = utcnow()
    due = datetime.combine(now.date() + timedelta(days=2), datetime.min.time(), now.tzinfo)
    due += timedelta(hours=17)
    await scene.build(api, due=due, assigned={crew.tech1: now - timedelta(days=2)})
    assert await scene.run(now) == 1

    for email in await outbox.emails():
        if email.status is EmailStatus.QUEUED:
            await delivery.send_email(runtime, email.id)
    message = only([m for m in transport.messages if "Reminder" in str(m["Subject"])])
    subject = str(message["Subject"])
    assert subject.startswith(
        f'[{crew.key}] Reminder: bid assessments for "Data platform build" are due '
    )
    text = message.get_body(("plain",))
    assert text is not None
    body = text.get_content()
    assert "you still have 2 assessments to submit" in body
    assert f"/ideas/{crew.key}?tab=bids" in body
    for secret in ("Northwind", "Tessellate", "1000", "1,000"):
        assert secret not in body
