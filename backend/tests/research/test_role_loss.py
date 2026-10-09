"""Phase 8b, the product owner's answer to review S1 (b) (contract-phase8b section 17):
losing one's role in a **private** project ends one's research assignments there
(audited ``left_project``, answers and the due date kept, no feed event or notification).

Every path that can take a role away: removing a direct member, removing a group grant,
removing someone from a group, deleting a group, and the sign-in group sync. Changing a
role keeps one (nothing ends); a group still giving a role keeps it; an internal project
ends nothing; an outsider an admin named (no role before) is untouched; deactivation has
its own reason (``deactivated``, tests/research/test_assignment.py).
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.group_sync import sync_groups
from app.config import Settings
from app.models.enums import GroupSyncMode, ProjectRole, ProjectVisibility, ResearchStep
from app.models.idea import Idea
from app.models.project import Project
from app.models.research import ResearchAnswer
from app.models.user import User
from tests.factories import make_idea
from tests.identity.helpers import ISSUER, add_to_group, grant, make_group
from tests.research.conftest import (
    AsUser,
    Team,
    answer,
    assign,
    feed_types,
    key_of,
    ok,
    researcher_audit,
    set_step,
)

DUE = "2026-12-11T17:00:00+00:00"


@pytest.fixture
def settings_overrides() -> dict[str, Any]:
    return {"oidc_issuer": ISSUER, "oidc_groups_claim": "groups"}


async def _assigned(api: AsUser, team: Team, db: AsyncSession, researcher: User) -> Idea:
    items = await set_step(db, team.project, ResearchStep.BEFORE_EVALUATION)
    idea = await make_idea(db, team.project, owner=team.owner)
    ok(await assign(await api(team.admin), key_of(team.project, idea), researcher, DUE))
    await answer(db, idea, items[0], researcher)
    return idea


async def _researcher(db: AsyncSession, idea: Idea) -> Any:
    row = await db.get(Idea, idea.id, populate_existing=True)
    assert row is not None
    return row.researcher_id


async def _assert_ended(db: AsyncSession, idea: Idea, actor: User | None) -> None:
    row = await db.get(Idea, idea.id, populate_existing=True)
    assert row is not None
    assert row.researcher_id is None
    assert row.research_assigned_at is None
    assert row.research_due_at is not None
    entry = (await researcher_audit(db, idea))[-1]
    assert entry.details["reason"] == "left_project"
    assert entry.actor_id == (actor.id if actor else None)
    assert (await feed_types(db, idea)).count("researcher_changed") == 1  # the assignment
    assert await _answers(db, idea) == 1  # kept


async def _answers(db: AsyncSession, idea: Idea) -> int:
    return int(await db.scalar(select(func.count()).where(ResearchAnswer.idea_id == idea.id)) or 0)


async def test_removing_a_direct_member_ends_their_assignments(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea = await _assigned(api, team, db_session, team.member)
    admin = await api(team.admin)

    response = await admin.delete(f"/projects/{team.slug}/members/{team.member.id}")

    assert response.status_code == 204, response.text
    await _assert_ended(db_session, idea, team.admin)


async def test_changing_a_role_keeps_it(api: AsUser, team: Team, db_session: AsyncSession) -> None:
    idea = await _assigned(api, team, db_session, team.member)

    ok(
        await (await api(team.admin)).patch(
            f"/projects/{team.slug}/members/{team.member.id}", {"role": "viewer"}
        )
    )

    assert await _researcher(db_session, idea) == team.member.id


async def test_a_group_still_giving_a_role_keeps_it(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    group = await make_group(db_session, "Support")
    await add_to_group(db_session, group, team.member)
    await grant(db_session, team.project, group, ProjectRole.VIEWER)
    idea = await _assigned(api, team, db_session, team.member)

    response = await (await api(team.admin)).delete(
        f"/projects/{team.slug}/members/{team.member.id}"
    )

    assert response.status_code == 204
    assert await _researcher(db_session, idea) == team.member.id


async def test_an_internal_project_ends_nothing(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    await db_session.execute(
        update(Project)
        .where(Project.id == team.project.id)
        .values(visibility=ProjectVisibility.INTERNAL)
    )
    await db_session.commit()
    idea = await _assigned(api, team, db_session, team.member)

    response = await (await api(team.admin)).delete(
        f"/projects/{team.slug}/members/{team.member.id}"
    )

    assert response.status_code == 204
    assert await _researcher(db_session, idea) == team.member.id


async def test_an_outsider_an_admin_named_is_untouched(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea = await _assigned(api, team, db_session, team.outsider)

    response = await (await api(team.admin)).delete(
        f"/projects/{team.slug}/members/{team.member.id}"
    )

    assert response.status_code == 204
    assert await _researcher(db_session, idea) == team.outsider.id


async def test_removing_a_group_grant(api: AsUser, team: Team, db_session: AsyncSession) -> None:
    group = await make_group(db_session, "Contractors")
    researcher = team.outsider
    await add_to_group(db_session, group, researcher)
    await grant(db_session, team.project, group, ProjectRole.MEMBER)
    idea = await _assigned(api, team, db_session, researcher)
    other = await make_idea(db_session, team.project, owner=team.owner)
    ok(await assign(await api(team.admin), key_of(team.project, other), team.member))

    response = await (await api(team.admin)).delete(f"/projects/{team.slug}/groups/{group.id}")

    assert response.status_code == 204, response.text
    await _assert_ended(db_session, idea, team.admin)
    assert await _researcher(db_session, other) == team.member.id  # still a member


async def test_removing_someone_from_a_group(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    group = await make_group(db_session, "Contractors")
    await add_to_group(db_session, group, team.outsider)
    await grant(db_session, team.project, group, ProjectRole.MEMBER)
    idea = await _assigned(api, team, db_session, team.outsider)

    response = await (await api(team.platform)).delete(
        f"/admin/groups/{group.id}/members/{team.outsider.id}"
    )

    assert response.status_code == 204, response.text
    await _assert_ended(db_session, idea, team.platform)


async def test_deleting_a_group(api: AsUser, team: Team, db_session: AsyncSession) -> None:
    group = await make_group(db_session, "Contractors")
    await add_to_group(db_session, group, team.outsider)
    await grant(db_session, team.project, group, ProjectRole.MEMBER)
    idea = await _assigned(api, team, db_session, team.outsider)

    response = await (await api(team.platform)).delete(f"/admin/groups/{group.id}")

    assert response.status_code == 204, response.text
    await _assert_ended(db_session, idea, team.platform)


async def test_the_sign_in_group_sync(
    api: AsUser, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    group = await make_group(
        db_session, "Contractors", idp_values=["contractors"], sync_mode=GroupSyncMode.MANAGED
    )
    await add_to_group(db_session, group, team.outsider, manual=False, synced=True)
    await grant(db_session, team.project, group, ProjectRole.MEMBER)
    idea = await _assigned(api, team, db_session, team.outsider)
    user = await db_session.get(User, team.outsider.id)
    assert user is not None

    await sync_groups(db_session, user, {"sub": "k-1", "groups": ["other"]}, settings)
    await db_session.commit()

    row = await db_session.get(Idea, idea.id, populate_existing=True)
    assert row is not None
    assert row.researcher_id is None
    entry = (await researcher_audit(db_session, idea))[-1]
    assert entry.details["reason"] == "left_project"
    assert entry.actor_id == team.outsider.id  # a sign-in sync's actor is the user


async def test_the_sync_keeping_the_group_ends_nothing(
    api: AsUser, team: Team, db_session: AsyncSession, settings: Settings
) -> None:
    group = await make_group(db_session, "Contractors", idp_values=["contractors"])
    await add_to_group(db_session, group, team.outsider, manual=False, synced=True)
    await grant(db_session, team.project, group, ProjectRole.MEMBER)
    idea = await _assigned(api, team, db_session, team.outsider)
    user = await db_session.get(User, team.outsider.id)
    assert user is not None

    await sync_groups(db_session, user, {"sub": "k-1", "groups": ["contractors"]}, settings)
    await db_session.commit()

    assert await _researcher(db_session, idea) == team.outsider.id
