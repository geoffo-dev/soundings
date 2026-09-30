"""Status transitions (contract section 3.3) and the owner: assign, release and
volunteer (section 3.4)."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import ActivityEvent, AuditLog
from app.models.enums import IdeaStatus, ProjectRole, Resolution
from app.models.idea import Idea, IdeaWatcher
from tests.factories import add_member, make_idea, make_project, make_user
from tests.ideas.conftest import AsUser, Team, assert_problem, ok


async def feed(db: AsyncSession, idea: Idea) -> list[tuple[str, dict[str, Any]]]:
    rows = await db.execute(
        select(ActivityEvent.type, ActivityEvent.payload)
        .where(ActivityEvent.idea_id == idea.id)
        .order_by(ActivityEvent.created_at, ActivityEvent.id)
    )
    return [(type_, payload) for type_, payload in rows]


def status_event(
    from_: tuple[str, str | None], to: tuple[str, str | None]
) -> tuple[str, dict[str, Any]]:
    return (
        "status_changed",
        {
            "from_status": from_[0],
            "from_resolution": from_[1],
            "to_status": to[0],
            "to_resolution": to[1],
        },
    )


def owner_event(
    before: Any, after: Any, *, volunteered: bool = False
) -> tuple[str, dict[str, Any]]:
    return (
        "owner_changed",
        {
            "from_owner_id": str(before.id) if before else None,
            "to_owner_id": str(after.id) if after else None,
            "volunteered": volunteered,
        },
    )


async def watchers(db: AsyncSession, idea: Idea) -> set[Any]:
    return set(await db.scalars(select(IdeaWatcher.user_id).where(IdeaWatcher.idea_id == idea.id)))


# --- Status ----------------------------------------------------------------------------------
async def test_any_status_to_any_status(api: AsUser, team: Team, db_session: AsyncSession) -> None:
    idea = await make_idea(db_session, team.project, owner=team.owner)
    olive = await api(team.owner)

    moved = ok(await olive.post(f"/ideas/{idea.id}/status", {"status": "proposal"}))
    closed = ok(
        await olive.post(f"/ideas/{idea.id}/status", {"status": "closed", "resolution": "accepted"})
    )
    reclosed = ok(
        await olive.post(f"/ideas/{idea.id}/status", {"status": "closed", "resolution": "parked"})
    )
    reopened = ok(await olive.post(f"/ideas/{idea.id}/status", {"status": "new"}))

    assert (moved["status"], moved["status_label"]) == ("proposal", "Proposal")
    assert (closed["status"], closed["resolution"], closed["status_label"]) == (
        "closed",
        "accepted",
        "Accepted",
    )
    assert closed["evaluation_open"] is False
    assert reclosed["resolution"] == "parked"
    assert (reopened["status"], reopened["resolution"]) == ("new", None)  # cleared
    assert await feed(db_session, idea) == [
        status_event(("new", None), ("proposal", None)),
        status_event(("proposal", None), ("closed", "accepted")),
        status_event(("closed", "accepted"), ("closed", "parked")),
        status_event(("closed", "parked"), ("new", None)),
    ]
    audited = await db_session.scalars(
        select(AuditLog.action).where(AuditLog.action == "idea.status_change")
    )
    assert len(list(audited)) == 4


async def test_same_status_is_a_no_op(api: AsUser, team: Team, db_session: AsyncSession) -> None:
    idea = await make_idea(
        db_session, team.project, status=IdeaStatus.CLOSED, resolution=Resolution.PARKED
    )
    ada = await api(team.admin)
    before = ok(await ada.get(f"/ideas/{idea.id}"))

    after = ok(
        await ada.post(f"/ideas/{idea.id}/status", {"status": "closed", "resolution": "parked"})
    )

    assert after == before
    assert await feed(db_session, idea) == []


async def test_moving_to_evaluating_has_no_side_effects(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea = await make_idea(db_session, team.project)
    ada = await api(team.admin)

    evaluating = ok(await ada.post(f"/ideas/{idea.id}/status", {"status": "evaluating"}))
    back = ok(await ada.post(f"/ideas/{idea.id}/status", {"status": "new"}))

    assert evaluating["evaluation_due_at"] is None
    assert (back["status"], back["evaluation_due_at"], back["owner"]) == ("new", None, None)


async def test_status_resolution_rules(api: AsUser, team: Team, db_session: AsyncSession) -> None:
    idea = await make_idea(db_session, team.project)
    ada = await api(team.admin)

    for body in (
        {"status": "closed"},
        {"status": "new", "resolution": "accepted"},
        {"status": "done"},
    ):
        assert_problem(await ada.post(f"/ideas/{idea.id}/status", body), 422, "validation_error")


async def test_who_may_change_status(api: AsUser, team: Team, db_session: AsyncSession) -> None:
    idea = await make_idea(db_session, team.project, owner=team.owner, submitted_by=team.member)
    body = {"status": "shortlisted"}
    path = f"/ideas/{idea.id}/status"

    assert_problem(await (await api(team.member)).post(path, body), 403, "forbidden")
    assert_problem(await (await api(team.viewer)).post(path, body), 403, "forbidden")
    assert_problem(await (await api(team.outsider)).post(path, body), 404, "not_found")
    ok(await (await api(team.platform)).post(path, body))
    ok(await (await api(team.admin)).post(path, {"status": "new"}))
    # A demoted owner's overlay grants nothing.
    await add_member_role(db_session, team, team.owner, ProjectRole.VIEWER)
    assert_problem(await (await api(team.owner)).post(path, body), 403, "forbidden")


async def add_member_role(db: AsyncSession, team: Team, user: Any, role: ProjectRole) -> None:
    from app.models.project import ProjectMember

    member = await db.get(ProjectMember, (team.project.id, user.id))
    assert member is not None
    member.role = role
    await db.commit()


async def test_summary_permissions_follow_the_owner(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    await make_idea(db_session, team.project, owner=team.owner, title="Mine")
    await make_idea(db_session, team.project, title="Not mine")
    olive = await api(team.owner)

    page = ok(await olive.get(f"/projects/{team.slug}/ideas", sort="title"))

    assert [(i["title"], i["permissions"]) for i in page["items"]] == [
        ("Mine", {"can_change_status": True}),
        ("Not mine", {"can_change_status": False}),
    ]


# --- Owner -----------------------------------------------------------------------------------
async def test_admin_assigns_changes_and_clears_the_owner(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea = await make_idea(db_session, team.project)
    ada = await api(team.admin)

    assigned = ok(await ada.put(f"/ideas/{idea.id}/owner", {"user_id": str(team.owner.id)}))
    same = ok(await ada.put(f"/ideas/{idea.id}/owner", {"user_id": str(team.owner.id)}))
    changed = ok(await ada.put(f"/ideas/{idea.id}/owner", {"user_id": str(team.member.id)}))
    cleared = ok(await ada.put(f"/ideas/{idea.id}/owner", {"user_id": None}))

    assert assigned["owner"]["id"] == str(team.owner.id)
    assert same == assigned
    assert changed["owner"]["id"] == str(team.member.id)
    assert cleared["owner"] is None
    assert await feed(db_session, idea) == [
        owner_event(None, team.owner),
        owner_event(team.owner, team.member),
        owner_event(team.member, None),
    ]
    assert await watchers(db_session, idea) == {team.owner.id, team.member.id}
    audited = await db_session.scalars(
        select(AuditLog.target_id).where(AuditLog.action == "idea.owner_change")
    )
    assert list(audited) == [idea.id] * 3


async def test_owner_eligibility(api: AsUser, team: Team, db_session: AsyncSession) -> None:
    idea = await make_idea(db_session, team.project)
    inactive = await make_user(db_session, "Ina Active", active=False)
    await add_member(db_session, team.project, inactive, ProjectRole.MEMBER)
    ada = await api(team.admin)

    for user_id in (team.viewer.id, team.outsider.id, team.platform.id, inactive.id):
        response = await ada.put(f"/ideas/{idea.id}/owner", {"user_id": str(user_id)})
        assert_problem(response, 422, "assignee_not_eligible")
    ok(await ada.put(f"/ideas/{idea.id}/owner", {"user_id": str(team.admin.id)}))


async def test_owner_steps_down_but_cannot_hand_over(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea = await make_idea(db_session, team.project, owner=team.owner)
    olive = await api(team.owner)

    detail = ok(await olive.get(f"/ideas/{idea.id}"))
    assert detail["permissions"]["can_release_owner"] is True
    assert detail["permissions"]["can_assign_owner"] is False
    response = await olive.put(f"/ideas/{idea.id}/owner", {"user_id": str(team.member.id)})
    assert_problem(response, 403, "forbidden")
    released = ok(await olive.put(f"/ideas/{idea.id}/owner", {"user_id": None}))

    assert released["owner"] is None
    assert released["permissions"]["can_volunteer"] is True  # the Undo for "step down"
    assert (await feed(db_session, idea))[-1][1]["to_owner_id"] is None


async def test_members_cannot_assign_owners(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea = await make_idea(db_session, team.project, owner=team.owner)

    for user in (team.member, team.viewer):
        for user_id in (None, str(user.id)):
            response = await (await api(user)).put(f"/ideas/{idea.id}/owner", {"user_id": user_id})
            assert_problem(response, 403, "forbidden")
    assert_problem(
        await (await api(team.outsider)).put(f"/ideas/{idea.id}/owner", {"user_id": None}),
        404,
        "not_found",
    )
    assert_problem(
        await (await api(team.admin)).put(f"/ideas/{idea.id}/owner", {}), 422, "validation_error"
    )


async def test_member_volunteers(api: AsUser, team: Team, db_session: AsyncSession) -> None:
    idea = await make_idea(db_session, team.project)
    max_ = await api(team.member)

    owned = ok(await max_.post(f"/ideas/{idea.id}/volunteer"))

    assert owned["owner"]["id"] == str(team.member.id)
    assert owned["permissions"]["can_volunteer"] is False
    assert owned["permissions"]["can_release_owner"] is True
    assert await feed(db_session, idea) == [owner_event(None, team.member, volunteered=True)]
    assert team.member.id in await watchers(db_session, idea)
    # The Undo: step down again.
    assert ok(await max_.put(f"/ideas/{idea.id}/owner", {"user_id": None}))["owner"] is None


@pytest.mark.parametrize(
    ("setup", "status", "code"),
    [
        ("owned", 409, "idea_has_owner"),
        ("closed", 409, "idea_closed"),
        ("volunteering_off", 403, "volunteering_disabled"),
    ],
)
async def test_volunteer_conditions(
    api: AsUser, team: Team, db_session: AsyncSession, setup: str, status: int, code: str
) -> None:
    idea = await make_idea(
        db_session,
        team.project,
        owner=team.owner if setup == "owned" else None,
        status=IdeaStatus.CLOSED if setup == "closed" else IdeaStatus.NEW,
    )
    if setup == "volunteering_off":
        team.project.allow_volunteer_owners = False
        db_session.add(team.project)
        await db_session.commit()

    assert_problem(await (await api(team.member)).post(f"/ideas/{idea.id}/volunteer"), status, code)


async def test_admins_volunteer_even_when_volunteering_is_off(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    project = await make_project(
        db_session,
        allow_volunteer_owners=False,
        members={team.admin: ProjectRole.ADMIN, team.viewer: ProjectRole.VIEWER},
    )
    idea = await make_idea(db_session, project)

    assert_problem(
        await (await api(team.viewer)).post(f"/ideas/{idea.id}/volunteer"), 403, "forbidden"
    )
    owned = ok(await (await api(team.admin)).post(f"/ideas/{idea.id}/volunteer"))

    assert owned["owner"]["id"] == str(team.admin.id)
