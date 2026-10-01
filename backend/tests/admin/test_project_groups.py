"""Project roles via groups (contract-phase2 section 3.7): group grants (list, add,
update, remove with c11), everyone with access and why, and member counts that
include group-derived access."""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ProjectRole, ProjectVisibility
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
from tests.factories import make_project, make_user


# --- list_project_group_grants ----------------------------------------------------------------
async def test_grants_are_listed_to_anyone_who_can_view(
    api: AsUser, people: People, db_session: AsyncSession
) -> None:
    viewers = await make_group(db_session, "viewers", description="Read-only")
    admins = await make_group(db_session, "Zeta admins")
    builders = await make_group(db_session, "Builders")
    await add_to_group(db_session, builders, people.carol)
    await add_to_group(db_session, builders, people.retired)
    await grant(db_session, people.project, viewers, ProjectRole.VIEWER)
    await grant(db_session, people.project, admins, ProjectRole.ADMIN)
    await grant(db_session, people.project, builders, ProjectRole.MEMBER)
    bob = await api(people.bob)  # a direct member
    outsider = await api(await make_user(db_session, "Otto Outsider"))

    grants = ok(await bob.get(f"/projects/{people.slug}/groups"))

    assert [(g["group"]["name"], g["role"]) for g in grants] == [
        ("Zeta admins", "admin"),
        ("Builders", "member"),
        ("viewers", "viewer"),
    ]
    assert grants[1]["group"]["member_count"] == 1  # deactivated members don't count
    assert grants[2]["group"]["description"] == "Read-only"
    assert grants[0]["granted_at"]
    assert_problem(await outsider.get(f"/projects/{people.slug}/groups"), 404, "not_found")
    assert_problem(await bob.get("/projects/nope/groups"), 404, "not_found")


# --- add / update / remove ---------------------------------------------------------------------
async def test_grant_a_group_a_role(api: AsUser, people: People, db_session: AsyncSession) -> None:
    group = await make_group(db_session, "Tools team")
    await add_to_group(db_session, group, people.carol, manual=False, synced=True)
    carol = await api(people.carol)
    assert_problem(await carol.get(f"/projects/{people.slug}"), 404, "not_found")
    lead = await api(people.lead)

    added = ok(await lead.post(f"/projects/{people.slug}/groups", {"group_id": str(group.id)}), 201)

    assert added["role"] == "member"  # the default
    assert added["group"] == {
        "id": str(group.id),
        "name": "Tools team",
        "description": "",
        "member_count": 1,
    }
    project = ok(await carol.get(f"/projects/{people.slug}"))
    assert project["my_role"] == "member"
    listed = ok(await carol.get("/projects"))
    assert people.slug in {item["slug"] for item in listed}
    [entry] = await audit_entries(db_session, "project.group_grant_add")
    assert (entry.target_type, entry.target_id) == ("group", group.id)
    assert entry.project_id == people.project.id
    assert entry.details["role"] == "member"
    assert entry.details["rule"] == "project.manage_members"

    again = await lead.post(f"/projects/{people.slug}/groups", {"group_id": str(group.id)})
    assert_problem(again, 409, "already_granted")
    unknown = await lead.post(f"/projects/{people.slug}/groups", {"group_id": str(uuid4())})
    assert_problem(unknown, 422, "group_not_found")


async def test_only_project_admins_manage_grants(
    api: AsUser, people: People, db_session: AsyncSession
) -> None:
    group = await make_group(db_session, "Tools team")
    await grant(db_session, people.project, group, ProjectRole.VIEWER)
    bob = await api(people.bob)  # member
    outsider = await api(people.carol)  # can't see the private project
    platform = await api(people.admin)  # acts as project admin everywhere
    base = f"/projects/{people.slug}/groups"
    body = {"group_id": str(group.id), "role": "admin"}

    assert_problem(await bob.post(base, body), 403, "forbidden")
    assert_problem(await bob.patch(f"{base}/{group.id}", {"role": "admin"}), 403, "forbidden")
    assert_problem(await bob.delete(f"{base}/{group.id}"), 403, "forbidden")
    assert_problem(await outsider.post(base, body), 404, "not_found")
    assert_problem(await outsider.delete(f"{base}/{group.id}"), 404, "not_found")
    ok(await platform.patch(f"{base}/{group.id}", {"role": "member"}))


async def test_change_and_remove_a_grant(
    api: AsUser, people: People, db_session: AsyncSession
) -> None:
    group = await make_group(db_session, "Tools team")
    await add_to_group(db_session, group, people.carol)
    await grant(db_session, people.project, group, ProjectRole.VIEWER)
    lead = await api(people.lead)
    carol = await api(people.carol)
    path = f"/projects/{people.slug}/groups/{group.id}"

    promoted = ok(await lead.patch(path, {"role": "admin"}))
    ok(await lead.patch(path, {"role": "admin"}))  # unchanged: not audited
    assert promoted["role"] == "admin"
    assert ok(await carol.get(f"/projects/{people.slug}"))["my_role"] == "admin"

    ok(await lead.delete(path), 204)

    assert_problem(await carol.get(f"/projects/{people.slug}"), 404, "not_found")
    assert_problem(await lead.delete(path), 404, "not_found")
    assert_problem(await lead.patch(path, {"role": "member"}), 404, "not_found")
    other = await make_group(db_session, "Other")
    assert_problem(
        await lead.patch(f"/projects/{people.slug}/groups/{other.id}", {"role": "member"}),
        404,
        "not_found",
    )
    [updated] = await audit_entries(db_session, "project.group_grant_update")
    assert (updated.details["from_role"], updated.details["role"]) == ("viewer", "admin")
    [removed] = await audit_entries(db_session, "project.group_grant_remove")
    assert removed.details["from_role"] == "admin"
    assert removed.target_id == group.id


async def test_c11_counts_group_admins(
    api: AsUser, people: People, db_session: AsyncSession
) -> None:
    """The last admin can come through a group: demoting or removing that grant is
    409 last_admin; a group admin lets the last *direct* admin go; deactivated admins
    don't count."""
    group = await make_group(db_session, "Tools admins")
    await add_to_group(db_session, group, people.carol)
    await grant(db_session, people.project, group, ProjectRole.ADMIN)
    platform = await api(people.admin)
    lead = await api(people.lead)
    grant_path = f"/projects/{people.slug}/groups/{group.id}"

    # The lead (the only direct admin) can step down: carol is an admin through the group.
    ok(await lead.patch(f"/projects/{people.slug}/members/{people.lead.id}", {"role": "member"}))

    assert_problem(await platform.patch(grant_path, {"role": "member"}), 409, "last_admin")
    assert_problem(await platform.delete(grant_path), 409, "last_admin")

    # A second group admin who is deactivated doesn't count.
    await add_to_group(db_session, group, people.retired)
    assert_problem(await platform.delete(grant_path), 409, "last_admin")
    # A second, active group admin does.
    await add_to_group(db_session, group, people.bob)
    ok(await platform.patch(f"/projects/{people.slug}/members/{people.bob.id}", {"role": "admin"}))
    ok(await platform.delete(grant_path), 204)


# --- list_project_access and member_count ---------------------------------------------------------
async def test_everyone_with_access_and_why(
    api: AsUser, people: People, db_session: AsyncSession
) -> None:
    builders = await make_group(db_session, "Builders")
    admins = await make_group(db_session, "admins")
    await add_to_group(db_session, builders, people.bob)
    await add_to_group(db_session, builders, people.carol, manual=False, synced=True)
    await add_to_group(db_session, builders, people.retired)
    await add_to_group(db_session, admins, people.carol)
    await grant(db_session, people.project, builders, ProjectRole.VIEWER)
    await grant(db_session, people.project, admins, ProjectRole.ADMIN)
    bob = await api(people.bob)
    access = f"/projects/{people.slug}/access"

    page = ok(await bob.get(access))

    rows = {item["user"]["display_name"]: item for item in page["items"]}
    assert list(rows) == ["Bob Brown", "Carol Chen", "Lena Lead"]  # not the deactivated one
    assert rows["Bob Brown"]["role"] == "member"
    assert [(s["kind"], s["role"]) for s in rows["Bob Brown"]["sources"]] == [
        ("direct", "member"),
        ("group", "viewer"),
    ]
    assert rows["Carol Chen"]["role"] == "admin"
    assert [(s["group"]["name"], s["role"]) for s in rows["Carol Chen"]["sources"]] == [
        ("admins", "admin"),
        ("Builders", "viewer"),
    ]
    assert rows["Carol Chen"]["email"] == people.carol.email
    assert rows["Lena Lead"]["sources"] == [{"kind": "direct", "role": "admin", "group": None}]
    assert page["next_cursor"] is None

    admins_only = ok(await bob.get(access, role="admin"))
    assert [item["user"]["display_name"] for item in admins_only["items"]] == [
        "Carol Chen",
        "Lena Lead",
    ]
    searched = ok(await bob.get(access, q="CHEN"))
    assert [item["user"]["id"] for item in searched["items"]] == [str(people.carol.id)]
    first = ok(await bob.get(access, limit=2))
    rest = ok(await bob.get(access, limit=2, cursor=first["next_cursor"]))
    assert [item["user"]["display_name"] for item in first["items"] + rest["items"]] == list(rows)

    outsider = await api(await make_user(db_session, "Otto Outsider"))
    assert_problem(await outsider.get(access), 404, "not_found")
    assert_problem(await bob.get(access, cursor="x"), 400, "invalid_cursor")


async def test_member_count_includes_group_access(
    api: AsUser, people: People, db_session: AsyncSession
) -> None:
    """member_count counts active users with an effective role, direct or through a
    group (the people list_project_access lists), each once."""
    group = await make_group(db_session, "Everyone")
    for user in (people.bob, people.carol, people.retired):
        await add_to_group(db_session, group, user)
    await grant(db_session, people.project, group, ProjectRole.VIEWER)
    internal = await make_project(
        db_session, slug="open", key="OPEN", visibility=ProjectVisibility.INTERNAL
    )
    await grant(db_session, internal, group, ProjectRole.MEMBER)
    bob = await api(people.bob)

    projects = {item["slug"]: item for item in ok(await bob.get("/projects"))}
    detail = ok(await bob.get(f"/projects/{people.slug}"))

    # TOOLS: lead (direct), bob (direct and group), carol (group); not the retired one.
    assert projects[people.slug]["member_count"] == 3
    assert detail["member_count"] == 3
    assert projects["open"]["member_count"] == 2
    # list_project_members stays direct-only.
    direct = ok(await bob.get(f"/projects/{people.slug}/members"))
    assert {member["user"]["display_name"] for member in direct} == {"Lena Lead", "Bob Brown"}
