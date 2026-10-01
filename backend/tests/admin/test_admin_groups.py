"""Admin settings -> Groups (contract-phase2 sections 3.5-3.7, 3.12): CRUD, mapping,
manual members with provenance, delete semantics, the mapping test and the group
picker. Every write is audited."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import GroupSyncMode, ProjectRole
from app.models.group import GroupMembership
from tests.admin.conftest import (
    AsUser,
    People,
    add_to_group,
    assert_problem,
    audit_entries,
    grant,
    make_group,
    ok,
)
from tests.admin.test_admin_users import make_break_glass
from tests.factories import make_project, make_user


async def membership(db: AsyncSession, group_id: Any, user_id: Any) -> GroupMembership | None:
    await db.commit()  # end the transaction (objects stay loaded): see the API's writes
    return await db.scalar(
        select(GroupMembership).where(
            GroupMembership.group_id == group_id, GroupMembership.user_id == user_id
        )
    )


# --- create / get / update -------------------------------------------------------------------
async def test_create_a_mapped_group(api: AsUser, people: People, db_session: AsyncSession) -> None:
    admin = await api(people.admin)

    created = ok(
        await admin.post(
            "/admin/groups",
            {
                "name": "Innovation admins",
                "description": "Run the innovation board.",
                "idp_values": ["/Innovation/Admins", "innovation/admins/", " ops "],
            },
        ),
        201,
    )

    assert created["name"] == "Innovation admins"
    assert created["sync_mode"] == "managed"
    assert created["idp_values"] == ["innovation/admins", "ops"]
    assert created["member_count"] == created["manual_member_count"] == 0
    assert created["synced_member_count"] == created["project_count"] == 0
    assert created["project_grants"] == []
    [entry] = await audit_entries(db_session, "group.create")
    assert entry.target_type == "group"
    assert str(entry.target_id) == created["id"]
    assert entry.details["idp_values"] == ["innovation/admins", "ops"]
    assert entry.details["sync_mode"] == "managed"
    assert entry.details["rule"] == "platform.manage_groups"

    taken = await admin.post("/admin/groups", {"name": "INNOVATION ADMINS"})
    assert_problem(taken, 409, "group_name_taken")
    empty = await admin.post("/admin/groups", {"name": "x", "idp_values": ["//"]})
    assert_problem(empty, 422, "validation_error")


async def test_group_detail_counts_active_members_by_provenance(
    api: AsUser, people: People, db_session: AsyncSession
) -> None:
    group = await make_group(db_session, "Tools team", idp_values=["/tools/members"])
    await add_to_group(db_session, group, people.bob, manual=True)
    await add_to_group(db_session, group, people.carol, manual=False, synced=True)
    await add_to_group(db_session, group, people.lead, manual=True, synced=True)
    await add_to_group(db_session, group, people.retired, manual=True, synced=True)
    green = await make_project(db_session, name="Green", slug="green", key="GREEN")
    await grant(db_session, people.project, group, ProjectRole.MEMBER)
    await grant(db_session, green, group, ProjectRole.VIEWER)
    admin = await api(people.admin)

    detail = ok(await admin.get(f"/admin/groups/{group.id}"))

    assert (
        detail["member_count"],
        detail["manual_member_count"],
        detail["synced_member_count"],
    ) == (
        3,
        2,
        2,
    )
    assert detail["project_count"] == 2
    assert [(g["project"]["key"], g["role"]) for g in detail["project_grants"]] == [
        ("GREEN", "viewer"),
        ("TOOLS", "member"),
    ]
    assert detail["idp_values"] == ["tools/members"]
    assert_problem(await admin.get(f"/admin/groups/{uuid4()}"), 404, "not_found")


async def test_list_groups_by_name_with_paging(
    api: AsUser, people: People, db_session: AsyncSession
) -> None:
    for name in ("beta", "Alpha", "gamma", "Delta"):
        await make_group(db_session, name, idp_values=[f"/{name}"])
    admin = await api(people.admin)

    first = ok(await admin.get("/admin/groups", limit=3))
    rest = ok(await admin.get("/admin/groups", limit=3, cursor=first["next_cursor"]))
    found = ok(await admin.get("/admin/groups", q="ELT"))

    assert [g["name"] for g in first["items"]] == ["Alpha", "beta", "Delta"]
    assert [g["name"] for g in rest["items"]] == ["gamma"]
    assert rest["next_cursor"] is None
    assert [g["name"] for g in found["items"]] == ["Delta"]
    assert found["items"][0]["idp_values"] == ["delta"]
    assert_problem(await admin.get("/admin/groups", cursor="x"), 400, "invalid_cursor")


async def test_rename_and_describe(api: AsUser, people: People, db_session: AsyncSession) -> None:
    group = await make_group(db_session, "Ops")
    await make_group(db_session, "Leads")
    admin = await api(people.admin)

    renamed = ok(await admin.patch(f"/admin/groups/{group.id}", {"name": "Operations"}))
    described = ok(await admin.patch(f"/admin/groups/{group.id}", {"description": "On call"}))
    ok(await admin.patch(f"/admin/groups/{group.id}", {"name": "Operations"}))  # no change
    clash = await admin.patch(f"/admin/groups/{group.id}", {"name": "leads"})

    assert renamed["name"] == "Operations"
    assert described["description"] == "On call"
    assert_problem(clash, 409, "group_name_taken")
    assert_problem(await admin.patch(f"/admin/groups/{uuid4()}", {}), 404, "not_found")
    entries = await audit_entries(db_session, "group.update")
    assert [entry.details["fields"] for entry in entries] == [["name"], ["description"]]


# --- mapping --------------------------------------------------------------------------------------
async def test_replace_the_mapping(api: AsUser, people: People, db_session: AsyncSession) -> None:
    group = await make_group(db_session, "Viewers", idp_values=["/viewers"])
    await add_to_group(db_session, group, people.bob, manual=False, synced=True)
    admin = await api(people.admin)
    path = f"/admin/groups/{group.id}/mapping"

    replaced = ok(
        await admin.put(path, {"sync_mode": "additive", "idp_values": ["/Viewers", "/guests"]})
    )
    same = ok(await admin.put(path, {"sync_mode": "additive", "idp_values": ["guests", "viewers"]}))
    emptied = ok(await admin.put(path, {"sync_mode": "additive", "idp_values": []}))

    assert replaced["sync_mode"] == "additive"
    assert replaced["idp_values"] == ["guests", "viewers"]
    assert same["idp_values"] == ["guests", "viewers"]
    assert emptied["idp_values"] == []
    # Memberships don't change now: the mapping applies at each user's next sign-in.
    assert await membership(db_session, group.id, people.bob.id) is not None
    entries = await audit_entries(db_session, "group.mapping_replace")
    assert [
        (e.details["from_sync_mode"], e.details["sync_mode"], e.details["from_idp_values"])
        for e in entries
    ] == [("managed", "additive", ["viewers"]), ("additive", "additive", ["guests", "viewers"])]
    assert entries[1].details["idp_values"] == []
    assert_problem(
        await admin.put(
            f"/admin/groups/{uuid4()}/mapping", {"sync_mode": "managed", "idp_values": []}
        ),
        404,
        "not_found",
    )


# --- members --------------------------------------------------------------------------------------
async def test_members_with_provenance(
    api: AsUser, people: People, db_session: AsyncSession
) -> None:
    group = await make_group(db_session, "Tools team")
    await add_to_group(db_session, group, people.carol, manual=False, synced=True)
    await add_to_group(db_session, group, people.retired, manual=True)
    admin = await api(people.admin)
    members = f"/admin/groups/{group.id}/members"

    added = ok(await admin.post(members, {"user_id": str(people.bob.id)}), 201)
    also_manual = ok(await admin.post(members, {"user_id": str(people.carol.id)}), 201)
    again = await admin.post(members, {"user_id": str(people.bob.id)})
    listed = ok(await admin.get(members))
    searched = ok(await admin.get(members, q="CHEN"))
    paged = ok(await admin.get(members, limit=2))

    assert (added["manual"], added["synced"], added["is_active"]) == (True, False, True)
    assert added["email"] == people.bob.email
    assert (also_manual["manual"], also_manual["synced"]) == (True, True)
    assert_problem(again, 409, "already_member")
    assert [(m["user"]["display_name"], m["is_active"]) for m in listed["items"]] == [
        ("Bob Brown", True),
        ("Carol Chen", True),
        ("Rita Retired", False),
    ]
    assert [m["user"]["id"] for m in searched["items"]] == [str(people.carol.id)]
    assert len(paged["items"]) == 2
    rest = ok(await admin.get(members, limit=2, cursor=paged["next_cursor"]))
    assert [m["user"]["display_name"] for m in rest["items"]] == ["Rita Retired"]
    entries = await audit_entries(db_session, "group.member_add")
    assert [entry.details["user_id"] for entry in entries] == [
        str(people.bob.id),
        str(people.carol.id),
    ]
    assert all(entry.target_id == group.id for entry in entries)


async def test_who_can_be_a_member(api: AsUser, people: People, db_session: AsyncSession) -> None:
    group = await make_group(db_session, "Tools team")
    agent = await make_user(db_session, "Agent", service_account=True)
    break_glass = await make_break_glass(db_session)
    admin = await api(people.admin)
    members = f"/admin/groups/{group.id}/members"

    for user_id in (people.retired.id, agent.id, break_glass.id, uuid4()):
        response = await admin.post(members, {"user_id": str(user_id)})
        assert_problem(response, 422, "user_not_found")
    unknown_group = await admin.post(f"/admin/groups/{uuid4()}/members", {"user_id": str(uuid4())})
    assert_problem(unknown_group, 404, "not_found")  # 404 before the body's 422


async def test_remove_a_member_whatever_the_provenance(
    api: AsUser, people: People, db_session: AsyncSession
) -> None:
    group = await make_group(db_session, "Tools team", sync_mode=GroupSyncMode.ADDITIVE)
    await add_to_group(db_session, group, people.carol, manual=True, synced=True)
    await grant(db_session, people.project, group, ProjectRole.MEMBER)
    carol = await api(people.carol)
    ok(await carol.get(f"/projects/{people.slug}"))
    admin = await api(people.admin)

    removed = await admin.delete(f"/admin/groups/{group.id}/members/{people.carol.id}")
    again = await admin.delete(f"/admin/groups/{group.id}/members/{people.carol.id}")

    ok(removed, 204)
    assert_problem(again, 404, "not_found")
    assert await membership(db_session, group.id, people.carol.id) is None
    # Roles are evaluated live: the access through the group ends at once.
    assert_problem(await carol.get(f"/projects/{people.slug}"), 404, "not_found")
    [entry] = await audit_entries(db_session, "group.member_remove")
    assert entry.details["user_id"] == str(people.carol.id)
    assert (entry.details["manual"], entry.details["synced"]) == (True, True)
    assert_problem(
        await admin.delete(f"/admin/groups/{uuid4()}/members/{people.carol.id}"), 404, "not_found"
    )


async def test_removing_a_member_is_not_blocked_by_c11(
    api: AsUser, people: People, db_session: AsyncSession
) -> None:
    """Platform-level group changes can leave a project without an admin: platform
    admins can always repair a project."""
    group = await make_group(db_session, "Leads")
    await add_to_group(db_session, group, people.carol)
    project = await make_project(db_session, slug="solo", key="SOLO")
    await grant(db_session, project, group, ProjectRole.ADMIN)
    admin = await api(people.admin)

    ok(await admin.delete(f"/admin/groups/{group.id}/members/{people.carol.id}"), 204)


# --- delete ------------------------------------------------------------------------------------
async def test_delete_takes_memberships_mapping_and_grants_with_it(
    api: AsUser, people: People, db_session: AsyncSession
) -> None:
    group = await make_group(db_session, "Tools team", idp_values=["/tools/members"])
    await add_to_group(db_session, group, people.carol, manual=False, synced=True)
    await add_to_group(db_session, group, people.retired)
    await grant(db_session, people.project, group, ProjectRole.MEMBER)
    carol = await api(people.carol)
    ok(await carol.get(f"/projects/{people.slug}"))
    admin = await api(people.admin)

    ok(await admin.delete(f"/admin/groups/{group.id}"), 204)

    assert_problem(await admin.get(f"/admin/groups/{group.id}"), 404, "not_found")
    assert_problem(await admin.delete(f"/admin/groups/{group.id}"), 404, "not_found")
    assert_problem(await carol.get(f"/projects/{people.slug}"), 404, "not_found")
    assert await membership(db_session, group.id, people.carol.id) is None
    [entry] = await audit_entries(db_session, "group.delete")
    assert entry.details["member_count"] == 2
    assert entry.details["project_ids"] == [str(people.project.id)]


# --- test-mapping and the picker ---------------------------------------------------------------
@pytest.mark.settings(oidc_groups_claim="groups")
async def test_mapping_test_previews_a_sign_in(
    api: AsUser, people: People, db_session: AsyncSession
) -> None:
    tools = await make_group(db_session, "Tools team", idp_values=["/tools/members"])
    viewers = await make_group(
        db_session, "Viewers", idp_values=["/viewers"], sync_mode=GroupSyncMode.ADDITIVE
    )
    leads = await make_group(db_session, "Leads", idp_values=["/leads"])
    await add_to_group(db_session, viewers, people.carol, manual=False, synced=True)
    await add_to_group(db_session, leads, people.carol, manual=True, synced=True)
    await grant(db_session, people.project, tools, ProjectRole.MEMBER)
    admin = await api(people.admin)

    result = ok(
        await admin.post(
            "/admin/groups/test-mapping",
            {
                "claims": {"sub": "k-1", "groups": ["/Tools/Members", 7, "//", "/unknown"]},
                "user_id": str(people.carol.id),
            },
        )
    )
    anonymous = ok(
        await admin.post("/admin/groups/test-mapping", {"claims": {"groups": "/tools/members"}})
    )
    unknown = await admin.post(
        "/admin/groups/test-mapping", {"claims": {}, "user_id": str(uuid4())}
    )

    assert result["groups_claim"] == "groups"
    assert result["claim_found"] is True
    assert result["values"] == ["tools/members", "unknown"]
    assert result["ignored_count"] == 2
    assert [(g["group"]["name"], g["effect"], g["manual"]) for g in result["groups"]] == [
        ("Leads", "remove", True),
        ("Tools team", "add", False),
        ("Viewers", "keep", False),
    ]
    assert [r["project"]["key"] for r in result["project_roles"]] == ["TOOLS"]
    assert [(g["group"]["name"], g["effect"]) for g in anonymous["groups"]] == [
        ("Tools team", "add")
    ]
    assert_problem(unknown, 422, "user_not_found")
    # Read-only: nothing changed, nothing audited (the claims are never stored).
    assert await membership(db_session, tools.id, people.carol.id) is None
    actions = {entry.action for entry in await audit_entries(db_session)}
    assert actions <= {"session.sign_in"}


async def test_search_groups_for_any_signed_in_user(
    api: AsUser, people: People, db_session: AsyncSession
) -> None:
    tools = await make_group(db_session, "Tools team", description="Builders")
    await make_group(db_session, "Tools workshop")
    await make_group(db_session, "Viewers")
    await add_to_group(db_session, tools, people.bob)
    await add_to_group(db_session, tools, people.retired)
    bob = await api(people.bob)

    found = ok(await bob.get("/groups", q="TOOLS"))
    limited = ok(await bob.get("/groups", limit=1))

    assert found == [
        {
            "id": str(tools.id),
            "name": "Tools team",
            "description": "Builders",
            "member_count": 1,
        },
        {"id": found[1]["id"], "name": "Tools workshop", "description": "", "member_count": 0},
    ]
    assert [g["name"] for g in limited] == ["Tools team"]
