"""Project roles through groups (contract-phase2 section 3.7, role matrix section 1):
the effective role is the highest of the direct role and every group grant (manual or
synced membership), and every check reads it: the policy's loaders, the SQL filters,
c11 and the permission flags. Removing the membership or the grant removes the
access on the next request."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest
from fastapi import FastAPI
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import (
    Rule,
    admin_count,
    can,
    effective_role_of,
    effective_roles_of,
    load_project,
    other_platform_admins,
    visible_projects,
)
from app.domain.principal import Principal
from app.models.enums import ProjectRole, ProjectVisibility
from app.models.group import GroupMembership, ProjectGroupGrant
from app.models.project import Project
from app.models.user import User
from tests.conftest import Login
from tests.factories import make_project, make_user
from tests.identity.helpers import add_to_group, grant, make_group

ADMIN, MEMBER, VIEWER = ProjectRole.ADMIN, ProjectRole.MEMBER, ProjectRole.VIEWER


@dataclass
class Sources:
    direct: ProjectRole | None = None
    groups: list[tuple[ProjectRole | None, str]] = field(default_factory=list)
    """``(granted role or None for no grant, "manual" | "synced" | "both" | "none")``."""


CASES: dict[str, tuple[Sources, ProjectRole | None]] = {
    "nothing": (Sources(), None),
    "direct only": (Sources(direct=MEMBER), MEMBER),
    "group only (manual)": (Sources(groups=[(VIEWER, "manual")]), VIEWER),
    "group only (synced)": (Sources(groups=[(MEMBER, "synced")]), MEMBER),
    "group only (both)": (Sources(groups=[(ADMIN, "both")]), ADMIN),
    "direct viewer, group admin": (Sources(direct=VIEWER, groups=[(ADMIN, "synced")]), ADMIN),
    "direct admin, group viewer": (Sources(direct=ADMIN, groups=[(VIEWER, "manual")]), ADMIN),
    "direct member, group member": (Sources(direct=MEMBER, groups=[(MEMBER, "synced")]), MEMBER),
    "several groups": (Sources(groups=[(VIEWER, "manual"), (MEMBER, "synced")]), MEMBER),
    "three groups": (
        Sources(groups=[(VIEWER, "synced"), (ADMIN, "manual"), (MEMBER, "synced")]),
        ADMIN,
    ),
    "grant but not a member": (Sources(groups=[(ADMIN, "none")]), None),
    "member of a group without a grant": (Sources(groups=[(None, "manual")]), None),
}

_FLAGS = {"manual": (True, False), "synced": (False, True), "both": (True, True)}


async def arrange(db: AsyncSession, user: User, project: Project, sources: Sources) -> None:
    if sources.direct is not None:
        from tests.factories import add_member

        await add_member(db, project, user, sources.direct)
    for n, (role, membership) in enumerate(sources.groups):
        group = await make_group(db, f"Group {n} {user.id.hex[:6]}")
        if role is not None:
            await grant(db, project, group, role)
        if membership != "none":
            manual, synced = _FLAGS[membership]
            await add_to_group(db, group, user, manual=manual, synced=synced)


@pytest.mark.parametrize("name", sorted(CASES))
async def test_effective_role(db_session: AsyncSession, name: str) -> None:
    sources, expected = CASES[name]
    user = await make_user(db_session)
    project = await make_project(db_session)
    await arrange(db_session, user, project, sources)
    principal = Principal(user=user)

    role = await effective_role_of(db_session, user.id, project.id)
    roles = await effective_roles_of(db_session, project.id, [user.id])
    resource = None
    if expected is not None:  # otherwise load_project is 404 (private project)
        _, resource = await load_project(db_session, principal, project.slug, rule=None)
    visible = await db_session.scalar(
        Project.__table__.select()
        .with_only_columns(Project.id)
        .where(Project.id == project.id, visible_projects(principal))
    )

    assert role is expected
    assert roles == {user.id: expected}
    assert (visible is not None) is (expected is not None)  # a private project
    if resource is not None:
        assert resource.role is expected
        assert can(principal, Rule.PROJECT_MANAGE_MEMBERS, resource) is (expected is ADMIN)
        assert can(principal, Rule.IDEA_CREATE, resource) is (expected in (ADMIN, MEMBER))


async def test_removing_the_membership_or_the_grant_removes_access(
    db_session: AsyncSession,
) -> None:
    carol = await make_user(db_session, "Carol")
    dave = await make_user(db_session, "Dave")
    project = await make_project(db_session)
    tools = await make_group(db_session, "Tools")
    await grant(db_session, project, tools, MEMBER)
    await add_to_group(db_session, tools, carol, manual=False, synced=True)
    await add_to_group(db_session, tools, dave, manual=True)

    await db_session.execute(delete(GroupMembership).where(GroupMembership.user_id == carol.id))
    await db_session.commit()
    carol_after = await effective_role_of(db_session, carol.id, project.id)
    dave_before = await effective_role_of(db_session, dave.id, project.id)
    await db_session.execute(delete(ProjectGroupGrant))
    await db_session.commit()
    dave_after = await effective_role_of(db_session, dave.id, project.id)

    assert (carol_after, dave_before, dave_after) == (None, MEMBER, None)


# --- c11 counts group admins who are active people ----------------------------------------------
@pytest.mark.parametrize(
    ("admins", "expected"),
    [
        ({"direct": "active"}, 1),
        ({"group": "active"}, 1),
        ({"direct": "active", "group": "active"}, 2),
        ({"group": "deactivated"}, 0),
        ({"direct": "deactivated"}, 0),
        ({"group": "service"}, 0),
        ({"direct": "service", "group": "active"}, 1),
    ],
)
async def test_admin_count(db_session: AsyncSession, admins: dict[str, str], expected: int) -> None:
    project = await make_project(db_session)
    group = await make_group(db_session, "Admins")
    await grant(db_session, project, group, ADMIN)
    for source, state in admins.items():
        user = await make_user(
            db_session, active=state != "deactivated", service_account=state == "service"
        )
        if source == "direct":
            from tests.factories import add_member

            await add_member(db_session, project, user, ADMIN)
        else:
            await add_to_group(db_session, group, user)
    viewer = await make_user(db_session)
    await add_to_group(db_session, await make_group(db_session, "Viewers"), viewer)

    assert await admin_count(db_session, project.id) == expected


# --- c18: the remaining platform admins ------------------------------------------------------
async def test_other_platform_admins(db_session: AsyncSession) -> None:
    ada = await make_user(db_session, platform_admin=True)
    bob = await make_user(db_session, platform_admin=True)
    await make_user(db_session, platform_admin=True, active=False)
    await make_user(db_session)
    break_glass = await make_user(db_session, platform_admin=True)
    break_glass.is_break_glass = True
    await db_session.commit()

    assert await other_platform_admins(db_session, ada.id) == 1
    assert await other_platform_admins(db_session, break_glass.id) == 2
    await db_session.execute(update(User).where(User.id == bob.id).values(is_active=False))
    assert await other_platform_admins(db_session, ada.id) == 0


async def test_concurrent_demotions_cannot_both_succeed(
    app: FastAPI, db_session: AsyncSession
) -> None:
    """Two admins demote each other at once: the second waits for the first's lock,
    then counts the first change and gets 0 (409 last_platform_admin)."""
    ada = await make_user(db_session, platform_admin=True)
    bob = await make_user(db_session, platform_admin=True)
    sessionmaker = app.state.sessionmaker

    async with sessionmaker() as first, sessionmaker() as second:
        ada_demotes_bob = await other_platform_admins(first, bob.id)
        await first.execute(update(User).where(User.id == bob.id).values(is_platform_admin=False))
        waiting = asyncio.create_task(other_platform_admins(second, ada.id))
        await asyncio.sleep(0.3)
        assert not waiting.done()  # blocked on the first transaction's lock
        await first.commit()
        bob_demotes_ada = await asyncio.wait_for(waiting, timeout=10)
        await second.rollback()

    assert (ada_demotes_bob, bob_demotes_ada) == (1, 0)


# --- Through the API: a group grant opens a private project; losing it closes it ----------------
async def test_group_grant_through_the_api(login: Login, db_session: AsyncSession) -> None:
    carol = await make_user(db_session, "Carol")
    project = await make_project(db_session, visibility=ProjectVisibility.PRIVATE)
    leads = await make_group(db_session, "Leads")
    await grant(db_session, project, leads, ADMIN)
    await add_to_group(db_session, leads, carol, manual=False, synced=True)
    http = await login(carol)

    seen = await http.get(f"/api/v1/projects/{project.slug}")
    listed = await http.get("/api/v1/projects")
    await db_session.execute(delete(GroupMembership).where(GroupMembership.user_id == carol.id))
    await db_session.commit()
    gone = await http.get(f"/api/v1/projects/{project.slug}")
    unlisted = await http.get("/api/v1/projects")

    assert seen.status_code == 200
    assert seen.json()["permissions"]["can_manage"] is True  # admin through the group
    assert project.slug in [item["slug"] for item in listed.json()]
    assert gone.status_code == 404
    assert project.slug not in [item["slug"] for item in unlisted.json()]


@pytest.mark.parametrize(
    ("group_admin", "status"),
    [("active", 200), ("deactivated", 409), ("service", 409), (None, 409)],
)
async def test_c11_counts_active_group_admins_for_direct_member_changes(
    login: Login, db_session: AsyncSession, group_admin: str | None, status: int
) -> None:
    """Demoting the last *direct* admin is fine while a group grants admin to an active
    person; deactivated users and service accounts don't count."""
    from tests.factories import add_member

    alice = await make_user(db_session, "Alice")
    project = await make_project(db_session, members={alice: ADMIN})
    if group_admin is not None:
        leads = await make_group(db_session, "Leads")
        await grant(db_session, project, leads, ADMIN)
        bob = await make_user(
            db_session,
            "Bob",
            active=group_admin != "deactivated",
            service_account=group_admin == "service",
        )
        await add_to_group(db_session, leads, bob)
    carol = await make_user(db_session, "Carol")
    await add_member(db_session, project, carol, MEMBER)
    http = await login(alice)

    response = await http.patch(
        f"/api/v1/projects/{project.slug}/members/{alice.id}", json={"role": "member"}
    )

    assert response.status_code == status, response.text
    if status == 409:
        assert response.json()["code"] == "last_admin"
