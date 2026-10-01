"""Admin settings -> Users (contract-phase2 section 3.4): list and filters, pre-create
with external IDs, detail with provenance, update (c17, c18, system accounts,
deactivation ends sessions), external IDs, unlinking an identity and ending sessions.
Every write is audited without emails, names or external-ID values."""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import AuthMethod, ProjectRole
from app.models.user import BREAK_GLASS_EMAIL, User, UserExternalId, UserIdentity
from tests.admin.conftest import (
    API,
    ISSUER,
    AsUser,
    People,
    add_external_id,
    add_to_group,
    assert_problem,
    audit_entries,
    grant,
    link_identity,
    make_group,
    make_session,
    ok,
    session_count,
)
from tests.factories import make_project, make_user


async def make_break_glass(db: AsyncSession) -> User:
    user = User(
        id=uuid4(),
        email=BREAK_GLASS_EMAIL,
        display_name="Break-glass admin",
        is_platform_admin=True,
        is_break_glass=True,
    )
    db.add(user)
    await db.commit()
    return user


# --- list_admin_users -------------------------------------------------------------------------
async def test_list_shows_every_account_by_name_with_flags(
    api: AsUser, people: People, db_session: AsyncSession
) -> None:
    agent = await make_user(db_session, "agent Smith", service_account=True)
    break_glass = await make_break_glass(db_session)
    await link_identity(db_session, people.bob, "k-bob")
    admin = await api(people.admin)

    page = ok(await admin.get("/admin/users"))

    names = [item["display_name"] for item in page["items"]]
    assert names == sorted(names, key=str.lower)
    assert len(names) == 8
    by_id = {item["id"]: item for item in page["items"]}
    assert by_id[str(agent.id)]["is_service_account"] is True
    assert by_id[str(break_glass.id)]["is_break_glass"] is True
    assert by_id[str(people.bob.id)]["has_identity"] is True
    assert by_id[str(people.carol.id)]["has_identity"] is False
    assert by_id[str(people.retired.id)]["is_active"] is False
    assert by_id[str(people.admin.id)]["is_platform_admin"] is True
    assert set(by_id[str(people.bob.id)]) == {
        "id",
        "display_name",
        "avatar_url",
        "initials",
        "email",
        "is_platform_admin",
        "is_active",
        "is_service_account",
        "is_break_glass",
        "has_identity",
        "last_seen_at",
        "created_at",
    }
    assert page["next_cursor"] is None


async def test_list_filters_combine(api: AsUser, people: People, db_session: AsyncSession) -> None:
    await link_identity(db_session, people.bob, "k-bob")
    admin = await api(people.admin)

    async def ids(**params: Any) -> set[str]:
        return {item["id"] for item in ok(await admin.get("/admin/users", **params))["items"]}

    assert await ids(q="CHEN") == {str(people.carol.id)}
    assert await ids(q=people.bob.email.upper()[:6]) >= {str(people.bob.id)}
    assert await ids(q="%") == set()  # LIKE wildcards are literal
    assert await ids(active="false") == {str(people.retired.id)}
    assert await ids(platform_admin="true") == {str(people.admin.id), str(people.other_admin.id)}
    assert await ids(has_identity="true") == {str(people.bob.id)}
    assert str(people.bob.id) not in await ids(has_identity="false")
    assert await ids(has_identity="false", active="true", platform_admin="false") == {
        str(people.lead.id),
        str(people.carol.id),
    }


async def test_list_pages_with_a_cursor(api: AsUser, people: People) -> None:
    admin = await api(people.admin)

    seen: list[str] = []
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        page = ok(await admin.get("/admin/users", **params))
        seen += [item["id"] for item in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break

    everyone = ok(await admin.get("/admin/users"))["items"]
    assert seen == [item["id"] for item in everyone]
    assert_problem(await admin.get("/admin/users", cursor="nope"), 400, "invalid_cursor")


# --- create_admin_user ------------------------------------------------------------------------
async def test_pre_create_a_user_with_external_ids(
    api: AsUser, people: People, db_session: AsyncSession
) -> None:
    admin = await api(people.admin)

    created = ok(
        await admin.post(
            "/admin/users",
            {
                "email": " nia.lee@example.com ",
                "display_name": "Nia Lee",
                "is_platform_admin": True,
                "external_ids": [
                    {"kind": "employee_no", "value": "E2001"},
                    {"kind": "gitlab", "value": "nlee"},
                ],
            },
        ),
        201,
    )

    assert created["email"] == "nia.lee@example.com"
    assert created["is_active"] is True
    assert created["is_platform_admin"] is True
    assert created["has_identity"] is False
    assert created["identities"] == []
    assert created["external_ids"] == [
        {"kind": "employee_no", "value": "E2001"},
        {"kind": "gitlab", "value": "nlee"},
    ]
    assert created["groups"] == []
    assert created["project_roles"] == []
    assert created["active_session_count"] == 0
    [entry] = await audit_entries(db_session, "user.create")
    assert entry.actor_id == people.admin.id
    assert entry.target_type == "user"
    assert str(entry.target_id) == created["id"]
    assert entry.details == {
        "rule": "platform.manage_users",
        "source": "admin",
        "is_platform_admin": True,
        "external_id_kinds": ["employee_no", "gitlab"],
        "auth": "session",
        "auth_method": "dev_login",
    }
    assert "nia" not in json.dumps(entry.details).lower()
    assert "E2001" not in json.dumps(entry.details)


async def test_pre_create_conflicts(api: AsUser, people: People, db_session: AsyncSession) -> None:
    await add_external_id(db_session, people.bob, "employee_no", "E1002")
    admin = await api(people.admin)
    body = {"email": "new@example.com", "display_name": "New Person"}

    taken = await admin.post("/admin/users", body | {"email": people.carol.email.upper()})
    assert_problem(taken, 409, "email_taken")
    clash = await admin.post(
        "/admin/users", body | {"external_ids": [{"kind": "employee_no", "value": "e1002"}]}
    )
    assert_problem(clash, 409, "external_id_taken")
    reserved = await admin.post("/admin/users", body | {"email": "someone@soundings.invalid"})
    assert_problem(reserved, 422, "validation_error")
    # The same value under another kind is someone else's business.
    other_kind = await admin.post(
        "/admin/users", body | {"external_ids": [{"kind": "gitlab", "value": "E1002"}]}
    )
    ok(other_kind, 201)
    assert len(await audit_entries(db_session, "user.create")) == 1


# --- get_admin_user ---------------------------------------------------------------------------
async def test_detail_explains_where_access_comes_from(
    api: AsUser, people: People, db_session: AsyncSession
) -> None:
    identity = await link_identity(db_session, people.bob, "k-bob")
    await add_external_id(db_session, people.bob, "gitlab", "bobb")
    await add_external_id(db_session, people.bob, "employee_no", "E1002")
    engineers = await make_group(db_session, "engineers")
    admins = await make_group(db_session, "Tools admins")
    await add_to_group(db_session, engineers, people.bob, manual=True, synced=True)
    await add_to_group(db_session, admins, people.bob, manual=False, synced=True)
    await grant(db_session, people.project, admins, ProjectRole.ADMIN)
    await grant(db_session, people.project, engineers, ProjectRole.VIEWER)
    green = await make_project(db_session, name="Green", slug="green", key="GREEN")
    await grant(db_session, green, engineers, ProjectRole.MEMBER)
    await make_session(db_session, people.bob, AuthMethod.SSO)  # SSO is off: not live
    await make_session(db_session, people.bob, AuthMethod.DEV_LOGIN)
    admin = await api(people.admin)

    detail = ok(await admin.get(f"/admin/users/{people.bob.id}"))

    assert detail["has_identity"] is True
    assert detail["identities"] == [
        {
            "id": str(identity.id),
            "issuer": ISSUER,
            "subject": "k-bob",
            "linked_at": detail["identities"][0]["linked_at"],
            "last_login_at": None,
        }
    ]
    assert [item["kind"] for item in detail["external_ids"]] == ["employee_no", "gitlab"]
    assert detail["groups"] == [
        {"group": {"id": str(engineers.id), "name": "engineers"}, "manual": True, "synced": True},
        {"group": {"id": str(admins.id), "name": "Tools admins"}, "manual": False, "synced": True},
    ]
    green_role, tools_role = detail["project_roles"]
    assert green_role["project"]["key"] == "GREEN"
    assert green_role["role"] == "member"
    assert tools_role["project"]["key"] == "TOOLS"
    assert tools_role["role"] == "admin"  # the highest source wins
    assert [
        (s["kind"], s["role"], (s["group"] or {}).get("name")) for s in tools_role["sources"]
    ] == [
        ("direct", "member", None),
        ("group", "viewer", "engineers"),
        ("group", "admin", "Tools admins"),
    ]
    assert detail["active_session_count"] == 1


async def test_detail_of_an_unknown_user_is_404(api: AsUser, people: People) -> None:
    admin = await api(people.admin)
    assert_problem(await admin.get(f"/admin/users/{uuid4()}"), 404, "not_found")


# --- update_admin_user ------------------------------------------------------------------------
async def test_update_name_and_email(api: AsUser, people: People, db_session: AsyncSession) -> None:
    admin = await api(people.admin)

    updated = ok(
        await admin.patch(
            f"/admin/users/{people.carol.id}",
            {"display_name": "Carol Chen-Wu", "email": "carol.wu@example.com", "is_active": None},
        )
    )
    unchanged = ok(await admin.patch(f"/admin/users/{people.carol.id}", {}))
    case_only = ok(
        await admin.patch(f"/admin/users/{people.carol.id}", {"email": "Carol.Wu@example.com"})
    )

    assert updated["display_name"] == "Carol Chen-Wu"
    assert updated["email"] == "carol.wu@example.com"
    assert unchanged["email"] == "carol.wu@example.com"
    assert case_only["email"] == "Carol.Wu@example.com"
    entries = await audit_entries(db_session, "user.update")
    assert [entry.details["fields"] for entry in entries] == [["display_name", "email"], ["email"]]
    assert "is_active" not in entries[0].details
    assert_problem(
        await admin.patch(f"/admin/users/{people.carol.id}", {"email": people.bob.email.upper()}),
        409,
        "email_taken",
    )
    assert_problem(
        await admin.patch(f"/admin/users/{people.carol.id}", {"email": "x@host.invalid"}),
        422,
        "validation_error",
    )
    assert_problem(await admin.patch(f"/admin/users/{uuid4()}", {}), 404, "not_found")


async def test_you_cannot_change_your_own_access(api: AsUser, people: People) -> None:
    admin = await api(people.admin)
    me = f"/admin/users/{people.admin.id}"

    assert_problem(await admin.patch(me, {"is_active": False}), 403, "cannot_change_self")
    assert_problem(await admin.patch(me, {"is_platform_admin": False}), 403, "cannot_change_self")
    # Only when the value would change; other fields are fine.
    same = ok(await admin.patch(me, {"is_active": True, "is_platform_admin": True}))
    renamed = ok(await admin.patch(me, {"display_name": "Alice A."}))
    assert same["is_platform_admin"] is True
    assert renamed["display_name"] == "Alice A."


async def test_deactivating_ends_sessions_and_blocks_access(
    api: AsUser, people: People, db_session: AsyncSession
) -> None:
    carol = await api(people.carol)
    await make_session(db_session, people.carol, AuthMethod.SSO)
    admin = await api(people.admin)
    ok(await carol.get("/auth/me"))

    updated = ok(await admin.patch(f"/admin/users/{people.carol.id}", {"is_active": False}))

    assert updated["is_active"] is False
    assert updated["active_session_count"] == 0
    assert await session_count(db_session, people.carol.id) == 0
    assert_problem(await carol.get("/auth/me"), 401, "unauthorized")
    [entry] = await audit_entries(db_session, "user.update")
    assert entry.details["fields"] == ["is_active"]
    assert entry.details["is_active"] is False
    assert entry.details["sessions_ended"] == 2

    reactivated = ok(await admin.patch(f"/admin/users/{people.carol.id}", {"is_active": True}))
    assert reactivated["is_active"] is True


async def test_platform_admin_flag(api: AsUser, people: People, db_session: AsyncSession) -> None:
    admin = await api(people.admin)

    promoted = ok(await admin.patch(f"/admin/users/{people.bob.id}", {"is_platform_admin": True}))
    demoted = ok(
        await admin.patch(f"/admin/users/{people.other_admin.id}", {"is_platform_admin": False})
    )

    assert promoted["is_platform_admin"] is True
    assert demoted["is_platform_admin"] is False
    details = [entry.details for entry in await audit_entries(db_session, "user.update")]
    assert [(d["fields"], d["is_platform_admin"]) for d in details] == [
        (["is_platform_admin"], True),
        (["is_platform_admin"], False),
    ]


@pytest.mark.settings(
    break_glass_enabled=True, break_glass_username="admin", break_glass_password="s3cret-s3cret!"
)
async def test_the_last_platform_admin_stays_one(
    app: FastAPI, people: People, db_session: AsyncSession
) -> None:
    """c18: only reachable from a break-glass session (it doesn't count as the
    remaining admin; any other admin acting would remain one themselves)."""
    break_glass = await make_break_glass(db_session)
    started = await make_session(db_session, break_glass, AuthMethod.BREAK_GLASS)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        http.cookies.set("soundings_session", started.token)
        http.headers["X-CSRF-Token"] = started.csrf_token

        first = await http.patch(
            f"{API}/admin/users/{people.other_admin.id}", json={"is_active": False}
        )
        last = await http.patch(
            f"{API}/admin/users/{people.admin.id}", json={"is_platform_admin": False}
        )
        last_deactivated = await http.patch(
            f"{API}/admin/users/{people.admin.id}", json={"is_active": False}
        )
        harmless = await http.patch(
            f"{API}/admin/users/{people.admin.id}", json={"display_name": "Alice"}
        )

    ok(first)
    assert_problem(last, 409, "last_platform_admin")
    assert_problem(last_deactivated, 409, "last_platform_admin")
    ok(harmless)
    entries = await audit_entries(db_session, "user.update")
    assert [entry.details["auth_method"] for entry in entries] == ["break_glass", "break_glass"]
    assert all(entry.actor_id == break_glass.id for entry in entries)


async def test_system_accounts_keep_email_and_admin_flag(
    api: AsUser, people: People, db_session: AsyncSession
) -> None:
    agent = await make_user(db_session, "Agent", service_account=True)
    break_glass = await make_break_glass(db_session)
    admin = await api(people.admin)

    for account in (agent, break_glass):
        path = f"/admin/users/{account.id}"
        assert_problem(
            await admin.patch(path, {"email": "agent@example.com"}), 409, "system_account"
        )
        flag = not account.is_platform_admin
        assert_problem(await admin.patch(path, {"is_platform_admin": flag}), 409, "system_account")
        renamed = ok(await admin.patch(path, {"display_name": "Renamed", "is_active": False}))
        assert (renamed["display_name"], renamed["is_active"]) == ("Renamed", False)
    # Re-sending the current values is not a change.
    ok(await admin.patch(f"/admin/users/{break_glass.id}", {"is_platform_admin": True}))


# --- replace_user_external_ids -----------------------------------------------------------------
async def test_replace_external_ids(api: AsUser, people: People, db_session: AsyncSession) -> None:
    await add_external_id(db_session, people.carol, "employee_no", "E1003")
    await add_external_id(db_session, people.carol, "gitlab", "carol")
    await add_external_id(db_session, people.bob, "employee_no", "E1002")
    admin = await api(people.admin)
    path = f"/admin/users/{people.carol.id}/external-ids"

    replaced = ok(
        await admin.put(
            path,
            {
                "external_ids": [
                    {"kind": "employee_no", "value": "E1003"},
                    {"kind": "github", "value": "cchen"},
                ]
            },
        )
    )
    taken = await admin.put(path, {"external_ids": [{"kind": "employee_no", "value": "e1002"}]})
    own_value = ok(
        await admin.put(path, {"external_ids": [{"kind": "employee_no", "value": "e1003"}]})
    )
    same_again = ok(
        await admin.put(path, {"external_ids": [{"kind": "employee_no", "value": "e1003"}]})
    )
    cleared = ok(await admin.put(path, {"external_ids": []}))

    assert replaced["external_ids"] == [
        {"kind": "employee_no", "value": "E1003"},
        {"kind": "github", "value": "cchen"},
    ]
    assert_problem(taken, 409, "external_id_taken")
    assert own_value["external_ids"] == [{"kind": "employee_no", "value": "e1003"}]
    assert same_again == own_value
    assert cleared["external_ids"] == []
    entries = await audit_entries(db_session, "user.external_ids_replace")
    assert [entry.details["kinds"] for entry in entries] == [
        ["employee_no", "github"],
        ["employee_no"],
        [],
    ]
    assert not any("E100" in json.dumps(entry.details) for entry in entries)
    await db_session.commit()
    assert (
        await db_session.scalar(
            select(UserExternalId.value).where(UserExternalId.user_id == people.bob.id)
        )
        == "E1002"
    )


async def test_system_accounts_have_no_external_ids(
    api: AsUser, people: People, db_session: AsyncSession
) -> None:
    break_glass = await make_break_glass(db_session)
    agent = await make_user(db_session, "Agent", service_account=True)
    admin = await api(people.admin)
    body = {"external_ids": [{"kind": "employee_no", "value": "E9"}]}

    for account in (break_glass, agent):
        assert_problem(
            await admin.put(f"/admin/users/{account.id}/external-ids", body), 409, "system_account"
        )
    assert_problem(await admin.put(f"/admin/users/{uuid4()}/external-ids", body), 404, "not_found")


# --- unlink_user_identity / end_user_sessions ---------------------------------------------------
async def test_unlinking_an_identity_ends_sso_sessions(
    api: AsUser, people: People, db_session: AsyncSession
) -> None:
    identity = await link_identity(db_session, people.bob, "k-bob")
    other = await link_identity(db_session, people.carol, "k-carol")
    await make_session(db_session, people.bob, AuthMethod.SSO)
    await make_session(db_session, people.bob, AuthMethod.SSO)
    await make_session(db_session, people.bob, AuthMethod.DEV_LOGIN)
    admin = await api(people.admin)

    wrong_user = await admin.delete(f"/admin/users/{people.bob.id}/identities/{other.id}")
    response = await admin.delete(f"/admin/users/{people.bob.id}/identities/{identity.id}")
    again = await admin.delete(f"/admin/users/{people.bob.id}/identities/{identity.id}")

    assert_problem(wrong_user, 404, "not_found")
    ok(response, 204)
    assert_problem(again, 404, "not_found")
    assert await session_count(db_session, people.bob.id) == 1  # the dev-login one
    assert await db_session.get(UserIdentity, other.id) is not None
    [entry] = await audit_entries(db_session, "user.identity_unlink")
    assert entry.details == {
        "rule": "platform.manage_users",
        "identity_id": str(identity.id),
        "issuer": ISSUER,
        "sessions_ended": 2,
        "auth": "session",
        "auth_method": "dev_login",
    }


async def test_end_sessions_signs_a_user_out_everywhere(
    api: AsUser, people: People, db_session: AsyncSession
) -> None:
    bob = await api(people.bob)
    await make_session(db_session, people.bob, AuthMethod.SSO)
    admin = await api(people.admin)

    ok(await admin.delete(f"/admin/users/{people.bob.id}/sessions"), 204)
    ok(await admin.delete(f"/admin/users/{people.bob.id}/sessions"), 204)  # idempotent
    assert_problem(await admin.delete(f"/admin/users/{uuid4()}/sessions"), 404, "not_found")

    assert_problem(await bob.get("/auth/me"), 401, "unauthorized")
    assert await session_count(db_session, people.bob.id) == 0
    entries = await audit_entries(db_session, "user.sessions_end")
    assert [entry.details["count"] for entry in entries] == [2, 0]
    # Your own sessions too, if it is you.
    ok(await admin.delete(f"/admin/users/{people.admin.id}/sessions"), 204)
    assert_problem(await admin.get("/auth/me"), 401, "unauthorized")


# --- The break-glass admin stays out of people pickers and project roles ----------------------
async def test_break_glass_is_never_picked(
    api: AsUser, people: People, db_session: AsyncSession
) -> None:
    break_glass = await make_break_glass(db_session)
    admin = await api(people.admin)

    found = ok(await admin.get("/users", q="break"))
    added = await admin.post(
        f"/projects/{people.slug}/members", {"user_id": str(break_glass.id), "role": "member"}
    )
    dev_users = ok(await admin.get("/auth/dev/users"))

    assert found["items"] == []
    assert_problem(added, 422, "user_not_found")
    assert str(break_glass.id) not in {user["id"] for user in dev_users}
