"""Projects API (contract sections 2 "Projects" and 3.1): happy paths and every
documented error code."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import AuditLog
from app.models.enums import EvaluatorState, ProjectRole, ProjectVisibility
from app.models.idea import Idea
from app.models.project import Project, ProjectMember, RubricCriterion
from tests.conftest import Login
from tests.factories import (
    add_evaluator,
    add_member,
    criteria,
    make_idea,
    make_project,
    make_user,
)

API = "/api/v1/projects"


def assert_problem(response: httpx.Response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == code


async def audit_actions(db: AsyncSession) -> list[str]:
    return list(await db.scalars(select(AuditLog.action).order_by(AuditLog.created_at)))


# --- list_projects --------------------------------------------------------------------------
async def test_list_projects_shows_member_and_internal_projects(
    login: Login, db_session: AsyncSession
) -> None:
    ada = await make_user(db_session, "Ada")
    other = await make_user(db_session, "Other")
    mine = await make_project(db_session, name="Beta", members={ada: ProjectRole.MEMBER})
    await make_project(
        db_session,
        name="alpha",
        visibility=ProjectVisibility.INTERNAL,
        members={other: ProjectRole.ADMIN},
    )
    await make_project(db_session, name="Secret", members={other: ProjectRole.ADMIN})
    await make_project(db_session, name="Old", members={ada: ProjectRole.MEMBER}, archived=True)
    await make_idea(db_session, mine)
    await make_idea(db_session, mine)
    http = await login(ada)

    response = await http.get(API)

    assert response.status_code == 200
    body = response.json()
    assert [project["name"] for project in body] == ["alpha", "Beta"]  # by name, any case
    beta = body[1]
    assert beta["my_role"] == "member"
    assert beta["idea_count"] == 2
    assert beta["member_count"] == 1
    assert beta["archived_at"] is None
    assert beta["permissions"] == {"can_manage": False, "can_create_ideas": True}
    assert body[0]["my_role"] is None
    assert body[0]["permissions"] == {"can_manage": False, "can_create_ideas": False}
    with_archived = await http.get(API, params={"include_archived": "true"})
    assert [project["name"] for project in with_archived.json()] == ["alpha", "Beta", "Old"]
    assert with_archived.json()[2]["permissions"]["can_create_ideas"] is False


async def test_platform_admins_see_every_project(login: Login, db_session: AsyncSession) -> None:
    root = await make_user(db_session, platform_admin=True)
    owner = await make_user(db_session)
    await make_project(db_session, name="Secret", members={owner: ProjectRole.ADMIN})
    http = await login(root)

    [project] = (await http.get(API)).json()

    assert project["name"] == "Secret"
    assert project["my_role"] is None
    assert project["permissions"] == {"can_manage": True, "can_create_ideas": True}


async def test_list_projects_needs_a_session(client: httpx.AsyncClient) -> None:
    assert_problem(await client.get(API), 401, "unauthorized")


# --- create_project -------------------------------------------------------------------------
async def test_create_project(login: Login, db_session: AsyncSession) -> None:
    root = await make_user(db_session, "Root", platform_admin=True)
    http = await login(root)

    response = await http.post(
        API,
        json={
            "name": "Customer Innovation",
            "slug": "customer-innovation",
            "key": "CUST",
            "description": "  Ideas from customers.  ",
            "visibility": "internal",
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["slug"] == "customer-innovation"
    assert body["key"] == "CUST"
    assert body["description"] == "Ideas from customers."
    assert body["visibility"] == "internal"
    assert body["my_role"] == "admin"  # the creator is the first admin
    assert body["member_count"] == 1
    assert body["idea_count"] == 0
    assert body["allow_volunteer_owners"] is True
    assert body["default_evaluation_days"] == 7
    assert body["status_labels"]["shortlisted"] == "Shortlisted"
    assert [c["name"] for c in body["rubric"]] == [
        "Value",
        "Feasibility",
        "Effort",
        "Strategic fit",
        "Risk",
    ]
    assert [c["inverted"] for c in body["rubric"]] == [False, False, True, False, True]
    assert body["rubric"][0]["guidance"]["1"]
    assert body["permissions"] == {"can_manage": True, "can_create_ideas": True}
    project = await db_session.scalar(select(Project).where(Project.slug == "customer-innovation"))
    assert project is not None
    assert project.next_idea_number == 1
    assert await audit_actions(db_session) == ["session.sign_in", "project.create"]


async def test_create_project_with_another_admin(login: Login, db_session: AsyncSession) -> None:
    root = await make_user(db_session, platform_admin=True)
    lead = await make_user(db_session, "Lead")
    http = await login(root)

    response = await http.post(
        API, json={"name": "Ops", "slug": "ops", "key": "OPS", "admin_user_id": str(lead.id)}
    )

    assert response.status_code == 201
    assert response.json()["my_role"] is None  # the platform admin is not a member
    members = (await http.get(f"{API}/ops/members")).json()
    assert [(m["user"]["id"], m["role"]) for m in members] == [(str(lead.id), "admin")]


async def test_only_platform_admins_create_projects(
    login: Login, client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    ada = await make_user(db_session)
    await make_project(db_session, members={ada: ProjectRole.ADMIN})
    http = await login(ada)
    body = {"name": "X", "slug": "x-project", "key": "XP"}

    assert_problem(await http.post(API, json=body), 403, "forbidden")
    assert_problem(await client.post(API, json=body), 401, "unauthorized")


async def test_create_project_conflicts(login: Login, db_session: AsyncSession) -> None:
    root = await make_user(db_session, platform_admin=True)
    await make_project(db_session, slug="taken", key="TAKEN")
    http = await login(root)

    slug = await http.post(API, json={"name": "A", "slug": "taken", "key": "FREE"})
    key = await http.post(API, json={"name": "A", "slug": "free", "key": "TAKEN"})

    assert_problem(slug, 409, "slug_taken")
    assert_problem(key, 409, "key_taken")


@pytest.mark.parametrize("admin", ["unknown", "inactive", "service_account"])
async def test_create_project_with_an_unusable_admin(
    login: Login, db_session: AsyncSession, admin: str
) -> None:
    root = await make_user(db_session, platform_admin=True)
    user = await make_user(
        db_session, active=admin != "inactive", service_account=admin == "service_account"
    )
    admin_id = str(uuid4()) if admin == "unknown" else str(user.id)
    http = await login(root)

    response = await http.post(
        API, json={"name": "A", "slug": "a-b", "key": "AB", "admin_user_id": admin_id}
    )

    assert_problem(response, 422, "user_not_found")


@pytest.mark.parametrize(
    "body",
    [
        {"name": "A", "slug": "Bad Slug", "key": "AB"},
        {"name": "A", "slug": "ab", "key": "ab"},
        {"name": "A", "slug": "ab", "key": "TOOLONGX"},
        {"name": "", "slug": "ab", "key": "AB"},
        {"name": "A", "slug": "ab", "key": "AB", "visibility": "public"},
        {"name": "A", "slug": "ab", "key": "AB", "unknown": 1},
    ],
)
async def test_create_project_validation(
    login: Login, db_session: AsyncSession, body: dict[str, Any]
) -> None:
    http = await login(await make_user(db_session, platform_admin=True))

    assert_problem(await http.post(API, json=body), 422, "validation_error")


# --- get_project ----------------------------------------------------------------------------
async def test_get_project(login: Login, db_session: AsyncSession) -> None:
    ada = await make_user(db_session)
    project = await make_project(db_session, slug="cust", members={ada: ProjectRole.VIEWER})
    project.status_labels = {"shortlisted": "Short list", "accepted": "Go"}
    await db_session.commit()
    http = await login(ada)

    response = await http.get(f"{API}/cust")

    assert response.status_code == 200
    body = response.json()
    assert body["status_labels"] == {
        "new": "New",
        "evaluating": "Evaluating",
        "shortlisted": "Short list",
        "proposal": "Proposal",
        "closed": "Closed",
        "accepted": "Go",
        "rejected": "Rejected",
        "parked": "Parked",
    }
    assert [c["position"] for c in body["rubric"]] == [0, 1, 2, 3, 4]
    assert body["my_role"] == "viewer"
    assert body["permissions"] == {"can_manage": False, "can_create_ideas": False}
    assert set(body) >= {"created_at", "allow_volunteer_owners", "default_evaluation_days"}


async def test_get_project_visibility(login: Login, db_session: AsyncSession) -> None:
    outsider = await make_user(db_session)
    await make_project(db_session, slug="open", visibility=ProjectVisibility.INTERNAL)
    await make_project(db_session, slug="closed")
    http = await login(outsider)

    internal = await http.get(f"{API}/open")
    private = await http.get(f"{API}/closed")
    missing = await http.get(f"{API}/nothing-here")

    assert internal.status_code == 200
    assert internal.json()["my_role"] is None
    # A private project you can't see and one that doesn't exist look the same.
    assert_problem(private, 404, "not_found")
    assert_problem(missing, 404, "not_found")
    assert private.json()["detail"] == missing.json()["detail"]


async def test_malformed_slug_is_422(login: Login, db_session: AsyncSession) -> None:
    http = await login(await make_user(db_session))

    assert_problem(await http.get(f"{API}/Not_A_Slug"), 422, "validation_error")


# --- update_project -------------------------------------------------------------------------
async def test_update_project_settings(login: Login, db_session: AsyncSession) -> None:
    admin = await make_user(db_session)
    await make_project(db_session, slug="cust", name="Old", members={admin: ProjectRole.ADMIN})
    http = await login(admin)

    response = await http.patch(
        f"{API}/cust",
        json={
            "name": " New name ",
            "description": None,  # null = unchanged
            "visibility": "internal",
            "allow_volunteer_owners": False,
            "default_evaluation_days": 14,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == "New name"
    assert body["visibility"] == "internal"
    assert body["allow_volunteer_owners"] is False
    assert body["default_evaluation_days"] == 14
    entry = await db_session.scalar(select(AuditLog).where(AuditLog.action == "project.update"))
    assert entry is not None
    assert entry.details["fields"] == [
        "name",
        "visibility",
        "allow_volunteer_owners",
        "default_evaluation_days",
    ]


async def test_rename_and_reset_status_labels(login: Login, db_session: AsyncSession) -> None:
    admin = await make_user(db_session)
    project = await make_project(db_session, slug="cust", members={admin: ProjectRole.ADMIN})
    http = await login(admin)

    first = await http.patch(
        f"{API}/cust", json={"status_labels": {"shortlisted": "Short list", "parked": "Later"}}
    )
    second = await http.patch(
        f"{API}/cust",
        json={"status_labels": {"shortlisted": None, "parked": "Parked", "new": "Inbox"}},
    )

    assert first.json()["status_labels"]["shortlisted"] == "Short list"
    assert first.json()["status_labels"]["parked"] == "Later"
    labels = second.json()["status_labels"]
    assert (labels["shortlisted"], labels["parked"], labels["new"]) == (
        "Shortlisted",
        "Parked",
        "Inbox",
    )
    await db_session.refresh(project)
    assert project.status_labels == {"new": "Inbox"}  # overrides only


async def test_archive_and_restore(login: Login, db_session: AsyncSession) -> None:
    admin = await make_user(db_session)
    await make_project(db_session, slug="cust", members={admin: ProjectRole.ADMIN})
    http = await login(admin)

    archived = await http.patch(f"{API}/cust", json={"archived": True})
    listed = await http.get(API)
    restored = await http.patch(f"{API}/cust", json={"archived": False})

    assert archived.json()["archived_at"] is not None
    assert archived.json()["permissions"] == {"can_manage": True, "can_create_ideas": False}
    assert listed.json() == []
    assert restored.json()["archived_at"] is None
    assert restored.json()["permissions"]["can_create_ideas"] is True


async def test_update_project_errors(
    login: Login, client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    member = await make_user(db_session)
    outsider = await make_user(db_session)
    await make_project(db_session, slug="cust", members={member: ProjectRole.MEMBER})
    as_member = await login(member)
    as_outsider = await login(outsider)

    assert_problem(await as_member.patch(f"{API}/cust", json={"name": "X"}), 403, "forbidden")
    assert_problem(
        await as_member.patch(f"{API}/cust", json={"status_labels": {"new": "X"}}), 403, "forbidden"
    )
    assert_problem(await as_outsider.patch(f"{API}/cust", json={"name": "X"}), 404, "not_found")
    assert_problem(await client.patch(f"{API}/cust", json={"name": "X"}), 401, "unauthorized")
    admin = await make_user(db_session)
    project = await db_session.scalar(select(Project).where(Project.slug == "cust"))
    assert project is not None
    await add_member(db_session, project, admin, ProjectRole.ADMIN)
    as_admin = await login(admin)
    for body in (
        {"slug": "new-slug"},  # immutable
        {"key": "NEW"},
        {"default_evaluation_days": 0},
        {"status_labels": {"new": ""}},
        {"status_labels": {"unknown": "X"}},
    ):
        assert_problem(await as_admin.patch(f"{API}/cust", json=body), 422, "validation_error")


# --- Members --------------------------------------------------------------------------------
async def test_list_members(login: Login, db_session: AsyncSession) -> None:
    zoe = await make_user(db_session, "Zoe Admin")
    amy = await make_user(db_session, "amy member")
    bob = await make_user(db_session, "Bob Viewer")
    project = await make_project(
        db_session,
        slug="cust",
        members={amy: ProjectRole.MEMBER, zoe: ProjectRole.ADMIN, bob: ProjectRole.VIEWER},
    )
    assert project
    http = await login(bob)

    response = await http.get(f"{API}/cust/members")

    assert response.status_code == 200
    body = response.json()
    assert [(m["user"]["display_name"], m["role"]) for m in body] == [
        ("Zoe Admin", "admin"),
        ("amy member", "member"),
        ("Bob Viewer", "viewer"),
    ]
    assert body[1]["email"] == amy.email
    assert body[1]["user"] == {
        "id": str(amy.id),
        "display_name": "amy member",
        "avatar_url": None,
        "initials": "AM",
    }
    assert body[1]["joined_at"]


async def test_members_of_a_hidden_project_are_404(login: Login, db_session: AsyncSession) -> None:
    await make_project(db_session, slug="cust")
    http = await login(await make_user(db_session))

    assert_problem(await http.get(f"{API}/cust/members"), 404, "not_found")


async def test_add_member(login: Login, db_session: AsyncSession) -> None:
    admin = await make_user(db_session)
    newcomer = await make_user(db_session, "New Comer")
    await make_project(db_session, slug="cust", members={admin: ProjectRole.ADMIN})
    http = await login(admin)

    response = await http.post(
        f"{API}/cust/members", json={"user_id": str(newcomer.id), "role": "viewer"}
    )
    default_role = await http.post(
        f"{API}/cust/members", json={"user_id": str((await make_user(db_session)).id)}
    )

    assert response.status_code == 201
    assert response.json()["role"] == "viewer"
    assert response.json()["email"] == newcomer.email
    assert default_role.json()["role"] == "member"
    assert await audit_actions(db_session) == [
        "session.sign_in",
        "project.member_add",
        "project.member_add",
    ]


async def test_add_member_errors(login: Login, db_session: AsyncSession) -> None:
    admin = await make_user(db_session)
    member = await make_user(db_session)
    inactive = await make_user(db_session, active=False)
    await make_project(
        db_session, slug="cust", members={admin: ProjectRole.ADMIN, member: ProjectRole.MEMBER}
    )
    as_admin = await login(admin)
    as_member = await login(member)
    url = f"{API}/cust/members"

    assert_problem(
        await as_admin.post(url, json={"user_id": str(member.id)}), 409, "already_member"
    )
    assert_problem(await as_admin.post(url, json={"user_id": str(uuid4())}), 422, "user_not_found")
    assert_problem(
        await as_admin.post(url, json={"user_id": str(inactive.id)}), 422, "user_not_found"
    )
    assert_problem(await as_member.post(url, json={"user_id": str(inactive.id)}), 403, "forbidden")
    assert_problem(
        await as_admin.post(url, json={"user_id": str(member.id), "role": "owner"}),
        422,
        "validation_error",
    )


async def test_service_accounts_can_be_members(login: Login, db_session: AsyncSession) -> None:
    admin = await make_user(db_session)
    agent = await make_user(db_session, "Research Agent", service_account=True)
    await make_project(db_session, slug="cust", members={admin: ProjectRole.ADMIN})
    http = await login(admin)

    response = await http.post(f"{API}/cust/members", json={"user_id": str(agent.id)})

    assert response.status_code == 201


async def test_platform_admin_manages_members_without_a_role(
    login: Login, db_session: AsyncSession
) -> None:
    root = await make_user(db_session, platform_admin=True)
    admin = await make_user(db_session)
    await make_project(db_session, slug="cust", members={admin: ProjectRole.ADMIN})
    http = await login(root)

    response = await http.post(f"{API}/cust/members", json={"user_id": str(root.id)})

    assert response.status_code == 201


async def test_change_member_role(login: Login, db_session: AsyncSession) -> None:
    admin = await make_user(db_session)
    member = await make_user(db_session)
    await make_project(
        db_session, slug="cust", members={admin: ProjectRole.ADMIN, member: ProjectRole.MEMBER}
    )
    http = await login(admin)
    url = f"{API}/cust/members/{member.id}"

    promoted = await http.patch(url, json={"role": "admin"})
    unchanged = await http.patch(url, json={"role": "admin"})
    self_demoted = await http.patch(f"{API}/cust/members/{admin.id}", json={"role": "member"})

    assert promoted.status_code == 200
    assert promoted.json()["role"] == "admin"
    assert unchanged.json()["role"] == "admin"
    assert self_demoted.json()["role"] == "member"  # another admin is left
    entries = list(
        await db_session.scalars(select(AuditLog).where(AuditLog.action == "project.member_update"))
    )
    assert [(e.details["from_role"], e.details["role"]) for e in entries] == [
        ("member", "admin"),
        ("admin", "member"),
    ]


async def test_the_last_admin_stays(login: Login, db_session: AsyncSession) -> None:
    admin = await make_user(db_session)
    member = await make_user(db_session)
    project = await make_project(
        db_session, slug="cust", members={admin: ProjectRole.ADMIN, member: ProjectRole.MEMBER}
    )
    http = await login(admin)

    demote = await http.patch(f"{API}/cust/members/{admin.id}", json={"role": "viewer"})
    remove = await http.delete(f"{API}/cust/members/{admin.id}")

    assert_problem(demote, 409, "last_admin")
    assert_problem(remove, 409, "last_admin")
    role = await db_session.scalar(
        select(ProjectMember.role).where(
            ProjectMember.project_id == project.id, ProjectMember.user_id == admin.id
        )
    )
    assert role is ProjectRole.ADMIN  # rolled back


async def test_member_changes_on_non_members_are_404(
    login: Login, db_session: AsyncSession
) -> None:
    admin = await make_user(db_session)
    stranger = await make_user(db_session)
    await make_project(db_session, slug="cust", members={admin: ProjectRole.ADMIN})
    http = await login(admin)

    assert_problem(
        await http.patch(f"{API}/cust/members/{stranger.id}", json={"role": "admin"}),
        404,
        "not_found",
    )
    assert_problem(await http.delete(f"{API}/cust/members/{stranger.id}"), 404, "not_found")


async def test_member_changes_need_manage_members(login: Login, db_session: AsyncSession) -> None:
    admin = await make_user(db_session)
    member = await make_user(db_session)
    await make_project(
        db_session, slug="cust", members={admin: ProjectRole.ADMIN, member: ProjectRole.MEMBER}
    )
    http = await login(member)

    assert_problem(
        await http.patch(f"{API}/cust/members/{admin.id}", json={"role": "viewer"}),
        403,
        "forbidden",
    )
    assert_problem(await http.delete(f"{API}/cust/members/{admin.id}"), 403, "forbidden")


async def test_remove_member_keeps_assignments(login: Login, db_session: AsyncSession) -> None:
    admin = await make_user(db_session)
    owner = await make_user(db_session)
    project = await make_project(
        db_session, slug="cust", members={admin: ProjectRole.ADMIN, owner: ProjectRole.MEMBER}
    )
    idea = await make_idea(db_session, project, owner=owner)
    http = await login(admin)

    response = await http.delete(f"{API}/cust/members/{owner.id}")

    assert response.status_code == 204
    kept = await db_session.scalar(
        select(Idea.owner_id).where(Idea.id == idea.id).execution_options(populate_existing=True)
    )
    assert kept == owner.id
    members = (await http.get(f"{API}/cust/members")).json()
    assert [m["user"]["id"] for m in members] == [str(admin.id)]
    assert "project.member_remove" in await audit_actions(db_session)


# --- Rubric ---------------------------------------------------------------------------------
def criterion_in(criterion: RubricCriterion, **changes: Any) -> dict[str, Any]:
    return {
        "id": str(criterion.id),
        "name": criterion.name,
        "description": criterion.description,
        "weight": float(criterion.weight),
        "inverted": criterion.inverted,
        "guidance": criterion.guidance,
    } | changes


async def test_replace_rubric(login: Login, db_session: AsyncSession) -> None:
    admin = await make_user(db_session)
    project = await make_project(db_session, slug="cust", members={admin: ProjectRole.ADMIN})
    value, feasibility, effort, fit, risk = await criteria(db_session, project)
    http = await login(admin)

    response = await http.put(
        f"{API}/cust/rubric",
        json={
            "criteria": [
                criterion_in(effort, weight=1.25),
                criterion_in(value, name="Customer value", guidance={"5": "Huge"}),
                {"name": "Reach", "description": "How many people.", "inverted": False},
                criterion_in(fit),
            ]
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()["criteria"]
    assert [(c["name"], c["position"]) for c in body] == [
        ("Effort", 0),
        ("Customer value", 1),
        ("Reach", 2),
        ("Strategic fit", 3),
    ]
    assert body[0]["weight"] == 1.25
    assert body[0]["inverted"] is True
    assert body[1]["id"] == str(value.id)
    assert body[1]["guidance"] == {"5": "Huge"}
    assert body[2]["weight"] == 1.0
    # Unscored criteria that were left out are deleted.
    remaining = set(
        await db_session.scalars(
            select(RubricCriterion.id).where(RubricCriterion.project_id == project.id)
        )
    )
    assert feasibility.id not in remaining
    assert risk.id not in remaining
    assert [c["name"] for c in (await http.get(f"{API}/cust")).json()["rubric"]] == [
        "Effort",
        "Customer value",
        "Reach",
        "Strategic fit",
    ]
    assert "project.rubric_replace" in await audit_actions(db_session)


async def test_criteria_can_swap_names(login: Login, db_session: AsyncSession) -> None:
    admin = await make_user(db_session)
    project = await make_project(db_session, slug="cust", members={admin: ProjectRole.ADMIN})
    value, feasibility, effort, *_ = await criteria(db_session, project)
    http = await login(admin)

    response = await http.put(
        f"{API}/cust/rubric",
        json={
            "criteria": [
                criterion_in(value, name="Feasibility"),
                criterion_in(feasibility, name="value"),
                criterion_in(effort),
                {"name": "Value add"},
            ]
        },
    )

    assert response.status_code == 200, response.text
    assert [c["name"] for c in response.json()["criteria"]] == [
        "Feasibility",
        "value",
        "Effort",
        "Value add",
    ]


async def test_scored_criteria_are_archived_and_aggregates_recomputed(
    login: Login, db_session: AsyncSession
) -> None:
    """The contract's worked example (section 3.8): Value weight 2, Effort weight 1
    inverted; A: 4/2, B: 5/4, C: 2/3 -> 3.4 with n = 3 and high disagreement."""
    admin = await make_user(db_session)
    a, b, c = [await make_user(db_session) for _ in range(3)]
    project = await make_project(
        db_session,
        slug="cust",
        members={admin: ProjectRole.ADMIN} | dict.fromkeys((a, b, c), ProjectRole.MEMBER),
    )
    value, _feasibility, effort, fit, risk = await criteria(db_session, project)
    idea = await make_idea(db_session, project)
    for user, scores in [
        (a, {"Value": 4, "Effort": 2, "Risk": 1}),
        (b, {"Value": 5, "Effort": 4, "Risk": 1}),
        (c, {"Value": 2, "Effort": 3, "Risk": 5}),
    ]:
        await add_evaluator(db_session, idea, user, state=EvaluatorState.SUBMITTED, scores=scores)
    http = await login(admin)

    response = await http.put(
        f"{API}/cust/rubric",
        json={
            "criteria": [
                criterion_in(value, weight=2),
                criterion_in(effort, weight=1),
                criterion_in(fit),
            ]
        },
    )

    assert response.status_code == 200, response.text
    await db_session.refresh(idea)
    assert (idea.aggregate_score, idea.aggregate_count, idea.high_disagreement) == (
        Decimal("3.4"),
        3,
        True,
    )
    await db_session.refresh(risk)
    assert risk.archived_at is not None  # scored: archived, not deleted


async def test_replace_rubric_errors(login: Login, db_session: AsyncSession) -> None:
    admin = await make_user(db_session)
    member = await make_user(db_session)
    project = await make_project(
        db_session, slug="cust", members={admin: ProjectRole.ADMIN, member: ProjectRole.MEMBER}
    )
    other = await make_project(db_session, slug="other")
    value, feasibility, effort, *_ = await criteria(db_session, project)
    [foreign, *_] = await criteria(db_session, other)
    as_admin = await login(admin)
    as_member = await login(member)
    url = f"{API}/cust/rubric"
    three = [criterion_in(value), criterion_in(feasibility), criterion_in(effort)]

    assert_problem(await as_member.put(url, json={"criteria": three}), 403, "forbidden")
    assert_problem(
        await as_admin.put(
            url, json={"criteria": [*three[:2], criterion_in(foreign, name="Foreign")]}
        ),
        422,
        "unknown_criterion",
    )
    for criteria_body in (
        three[:2],  # fewer than 3
        [*three, {"name": "D"}, {"name": "E"}, {"name": "F"}, {"name": "G"}],  # more than 6
        [*three[:2], {"name": "VALUE"}],  # names are unique, case-insensitively
        [*three[:2], {"name": "Weightless", "weight": 0}],
        [*three[:2], {"name": "Heavy", "weight": 10.01}],
        [*three[:2], {"name": "Precise", "weight": 1.234}],
        [*three[:2], {"name": "Hints", "guidance": {"6": "Too high"}}],
    ):
        assert_problem(
            await as_admin.put(url, json={"criteria": criteria_body}), 422, "validation_error"
        )


async def test_archived_criterion_ids_are_unknown(login: Login, db_session: AsyncSession) -> None:
    admin = await make_user(db_session)
    evaluator = await make_user(db_session)
    project = await make_project(
        db_session, slug="cust", members={admin: ProjectRole.ADMIN, evaluator: ProjectRole.MEMBER}
    )
    value, feasibility, effort, fit, _risk = await criteria(db_session, project)
    idea = await make_idea(db_session, project)
    await add_evaluator(
        db_session, idea, evaluator, state=EvaluatorState.SUBMITTED, scores={"Strategic fit": 3}
    )
    http = await login(admin)
    url = f"{API}/cust/rubric"
    await http.put(url, json={"criteria": [criterion_in(c) for c in (value, feasibility, effort)]})

    response = await http.put(
        url, json={"criteria": [criterion_in(c) for c in (value, feasibility, fit)]}
    )

    assert_problem(response, 422, "unknown_criterion")


# --- Tags -----------------------------------------------------------------------------------
async def test_list_project_tags(login: Login, db_session: AsyncSession) -> None:
    ada = await make_user(db_session)
    project = await make_project(db_session, slug="cust", members={ada: ProjectRole.VIEWER})
    await make_idea(db_session, project, tags=["ux", "Pricing"])
    await make_idea(db_session, project, tags=["ux"])
    other = await make_project(db_session, slug="other", members={ada: ProjectRole.MEMBER})
    await make_idea(db_session, other, tags=["elsewhere"])
    http = await login(ada)

    response = await http.get(f"{API}/cust/tags")

    assert response.status_code == 200
    assert [(t["name"], t["idea_count"]) for t in response.json()] == [("Pricing", 1), ("ux", 2)]


async def test_tags_of_a_hidden_project_are_404(login: Login, db_session: AsyncSession) -> None:
    await make_project(db_session, slug="cust")
    http = await login(await make_user(db_session))

    assert_problem(await http.get(f"{API}/cust/tags"), 404, "not_found")


async def test_unused_tags_are_not_listed(login: Login, db_session: AsyncSession) -> None:
    ada = await make_user(db_session)
    project = await make_project(db_session, slug="cust", members={ada: ProjectRole.MEMBER})
    idea = await make_idea(db_session, project, tags=["typo"])
    await db_session.delete(await db_session.get(Idea, idea.id))
    await db_session.commit()
    http = await login(ada)

    assert (await http.get(f"{API}/cust/tags")).json() == []
