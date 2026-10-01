"""The moderation queue, approve and reject (contract-phase4 section 3.6): project and
platform admins see ideas held for moderation oldest first; approving makes one
visible at the top of New, rejecting deletes it with its submitter's details and
emails; both are audited with ids only, notify nobody and answer 409
``not_awaiting_moderation`` the second time."""

from __future__ import annotations

from datetime import timedelta

import httpx
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.activity import AuditLog
from app.models.base import utcnow
from app.models.enums import HoldReason, ProjectVisibility
from app.models.idea import Idea
from app.models.notification import Notification, OutboundEmail
from app.models.project import Project
from app.models.public import PublicSubmission
from tests.factories import make_idea
from tests.moderation.conftest import (
    PUBLIC,
    AsUser,
    Team,
    assert_problem,
    make_public_idea,
    ok,
    send,
)

pytestmark = pytest.mark.usefixtures("form")


async def held(
    db: AsyncSession,
    settings: Settings,
    team: Team,
    title: str,
    *,
    hours_ago: float = 1,
    reason: HoldReason = HoldReason.MODERATION,
    email: str | None = None,
) -> tuple[str, Idea]:
    token, idea = await make_public_idea(
        db, settings, team, title=title, held_for=reason, email=email
    )
    await db.execute(
        update(Idea)
        .where(Idea.id == idea.id)
        .values(created_at=utcnow() - timedelta(hours=hours_ago))
    )
    await db.commit()
    return token, idea


async def audit_of(db: AsyncSession, action: str) -> list[AuditLog]:
    return list(await db.scalars(select(AuditLog).where(AuditLog.action == action)))


# --- The queue ---------------------------------------------------------------------------
async def test_admins_see_the_queue_oldest_first(
    api: AsUser, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    await held(db_session, settings, team, "Second", hours_ago=2)
    await held(db_session, settings, team, "First", hours_ago=3)
    await held(db_session, settings, team, "Unconfirmed", reason=HoldReason.EMAIL_VERIFICATION)
    await make_idea(db_session, team.project, title="Visible")
    await make_public_idea(db_session, settings, team, title="Approved earlier")

    for user in (team.admin, team.platform):
        page = ok(await (await api(user)).get(f"/projects/{team.slug}/moderation"))
        assert [item["title"] for item in page["items"]] == ["First", "Second"]
        assert page["total"] == 2
        assert page["next_cursor"] is None
        first = page["items"][0]
        assert first["key"].startswith("CUST-")
        assert first["status"] == "new"
        assert first["summary"] == "As sent."
        assert first["submission"]["held_for"] == "moderation"
        assert first["submission"]["permissions"] == {"can_moderate": True, "can_erase": True}
        assert first["submission"]["contact"] is not None  # admins see the contact


async def test_the_queue_pages_by_cursor(
    api: AsUser, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    for n in range(5):
        await held(db_session, settings, team, f"Idea {n}", hours_ago=10 - n)
    admin = await api(team.admin)

    titles: list[str] = []
    cursor = None
    while True:
        params = {"limit": "2"} if cursor is None else {"limit": "2", "cursor": cursor}
        page = ok(await admin.get(f"/projects/{team.slug}/moderation", **params))
        assert page["total"] == 5
        titles += [item["title"] for item in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break

    assert titles == [f"Idea {n}" for n in range(5)]
    broken = await admin.get(f"/projects/{team.slug}/moderation", cursor="eyJ4IjoxfQ")
    assert_problem(broken, 400, "invalid_cursor")


async def test_only_admins_see_the_queue(
    client: httpx.AsyncClient, api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    path = f"/projects/{team.slug}/moderation"
    for user in (team.member, team.viewer):
        assert_problem(await (await api(user)).get(path), 403, "forbidden")
    assert_problem(await (await api(team.outsider)).get(path), 404, "not_found")  # private
    await db_session.execute(
        update(Project)
        .where(Project.id == team.project.id)
        .values(visibility=ProjectVisibility.INTERNAL)
    )
    await db_session.commit()
    assert_problem(await (await api(team.outsider)).get(path), 403, "forbidden")
    assert_problem(await client.get(f"/api/v1{path}"), 401, "unauthorized")


async def test_an_archived_project_still_shows_its_queue(
    api: AsUser, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    _, idea = await held(db_session, settings, team, "Waiting")
    await db_session.execute(
        update(Project).where(Project.id == team.project.id).values(archived_at=utcnow())
    )
    await db_session.commit()
    admin = await api(team.admin)

    assert ok(await admin.get(f"/projects/{team.slug}/moderation"))["total"] == 1
    assert_problem(
        await admin.post(f"/ideas/{idea.id}/submission/approve"), 409, "project_archived"
    )
    assert_problem(await admin.post(f"/ideas/{idea.id}/submission/reject"), 409, "project_archived")


# --- Approve -----------------------------------------------------------------------------
async def test_approving_shows_the_idea_at_the_top_of_new(
    api: AsUser, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    await make_idea(db_session, team.project, title="Recent internal idea")
    _, idea = await held(db_session, settings, team, "From the public", hours_ago=48)
    member = await api(team.member)
    assert ok(await member.get(f"/projects/{team.slug}/ideas"))["total"] == 1

    approved = ok(await (await api(team.admin)).post(f"/ideas/{idea.id}/submission/approve"))

    assert approved["held_for"] is None
    assert approved["permissions"]["can_moderate"] is False
    listed = ok(await member.get(f"/projects/{team.slug}/ideas", sort="-updated"))
    assert listed["total"] == 2
    assert listed["items"][0]["title"] == "From the public"
    detail = ok(await member.get(f"/ideas/{idea.id}"))
    assert detail["permissions"]["can_comment"] is True
    board = ok(await member.get(f"/projects/{team.slug}/board"))
    new = next(column for column in board["columns"] if column["status"] == "new")
    assert new["items"][0]["title"] == "From the public"
    assert ok(await (await api(team.admin)).get(f"/projects/{team.slug}/moderation"))["total"] == 0
    [entry] = await audit_of(db_session, "submission.approve")
    assert entry.actor_id == team.admin.id
    assert (entry.target_type, entry.target_id) == ("idea", idea.id)
    assert entry.details["rule"] == "idea.moderate"
    # Nobody is notified and nothing is emailed.
    assert await db_session.scalar(select(func.count()).select_from(Notification)) == 0
    assert await db_session.scalar(select(func.count()).select_from(OutboundEmail)) == 0


async def test_a_second_decision_is_409(
    api: AsUser, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    _, idea = await held(db_session, settings, team, "Twice")
    admin = await api(team.admin)
    ok(await admin.post(f"/ideas/{idea.id}/submission/approve"))

    for decision in ("approve", "reject"):
        response = await admin.post(f"/ideas/{idea.id}/submission/{decision}")
        assert_problem(response, 409, "not_awaiting_moderation")
    assert len(await audit_of(db_session, "submission.approve")) == 1


async def test_only_admins_decide(
    api: AsUser, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    _, waiting = await held(db_session, settings, team, "Waiting")
    _, visible = await make_public_idea(db_session, settings, team, title="Visible")
    internal = await make_idea(db_session, team.project, title="Internal")
    unconfirmed = (
        await held(db_session, settings, team, "Unconfirmed", reason=HoldReason.EMAIL_VERIFICATION)
    )[1]

    for user in (team.member, team.viewer, team.outsider):
        client = await api(user)
        for idea in (waiting, visible):
            for decision in ("approve", "reject"):
                response = await client.post(f"/ideas/{idea.id}/submission/{decision}")
                assert_problem(response, 404, "not_found")
    admin = await api(team.admin)
    for idea in (internal, unconfirmed):  # not a public idea / invisible to everyone
        for decision in ("approve", "reject"):
            response = await admin.post(f"/ideas/{idea.id}/submission/{decision}")
            assert_problem(response, 404, "not_found")
    decisions = select(func.count()).where(AuditLog.action.like("submission.%"))
    assert await db_session.scalar(decisions) == 0


# --- Reject ------------------------------------------------------------------------------
async def test_rejecting_deletes_the_idea_its_details_and_emails(
    api: AsUser,
    team: Team,
    db_session: AsyncSession,
    visitor: object,
    anon: httpx.AsyncClient,
) -> None:
    receipt = ok(
        await send(anon, team.slug, title="Spam", name="Spammer", email="spam@example.org"), 201
    )
    idea = await db_session.scalar(select(Idea).where(Idea.title == "Spam"))
    assert idea is not None
    key = f"CUST-{idea.number}"
    assert await db_session.scalar(select(func.count()).select_from(OutboundEmail)) == 1

    response = await (await api(team.platform)).post(f"/ideas/{key}/submission/reject")

    assert response.status_code == 204
    assert await db_session.scalar(select(func.count()).select_from(Idea)) == 0
    assert await db_session.scalar(select(func.count()).select_from(PublicSubmission)) == 0
    assert await db_session.scalar(select(func.count()).select_from(OutboundEmail)) == 0
    [entry] = await audit_of(db_session, "submission.reject")
    assert entry.actor_id == team.platform.id
    assert entry.target_id == idea.id
    assert entry.details["key"] == key
    assert entry.details["rule"] == "idea.moderate"
    assert "Spam" not in str(entry.details)
    assert "spam@example.org" not in str(entry.details)
    # The tracking link is gone too.
    tracked = await anon.post(f"{PUBLIC}/track", json={"token": receipt["tracking_token"]})
    assert_problem(tracked, 404, "not_found")
    assert_problem(
        await (await api(team.platform)).post(f"/ideas/{key}/submission/reject"), 404, "not_found"
    )
