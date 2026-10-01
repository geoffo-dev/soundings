"""SSO against a real Keycloak 26 with the dev realm (contract-phase2 sections 3.2-3.6
and the acceptance scenario of 3.13): the full code flow with PKCE, matching by
identity, external ID and verified email, managed and additive group sync, and the
SPEC acceptance: a user in an IdP group gets the mapped project role; removed from the
group in Keycloak, the access is gone at the next sign-in; a manual membership stays.

Needs Docker (skipped otherwise, see ``tests/identity/keycloak.py``).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import effective_role_of
from app.models.enums import GroupSyncMode, ProjectRole, ProjectVisibility
from app.models.group import Group
from app.models.user import User, UserIdentity
from tests.factories import make_project, make_user
from tests.identity.helpers import (
    add_external_id,
    add_to_group,
    audit_entries,
    grant,
    make_group,
    memberships,
)
from tests.identity.keycloak import (
    CLIENT_ID,
    CLIENT_SECRET,
    TEST_ORIGIN,
    Browser,
    Keycloak,
    KeycloakAdmin,
    keycloak,
    query_of,
)

__all__ = ["keycloak"]  # the session fixture, re-exported for pytest

TOOLS = "/tools/members"


@pytest.fixture
def settings_overrides(keycloak: Keycloak) -> dict[str, Any]:
    return {
        "oidc_issuer": keycloak.issuer,
        "oidc_client_id": CLIENT_ID,
        "oidc_client_secret": CLIENT_SECRET,
        "oidc_groups_claim": "groups",
        "oidc_external_id_claim": "employee_no",
        "dev_login_enabled": False,
    }


@pytest.fixture
def browser() -> Iterator[Browser]:
    session = Browser()
    yield session
    session.close()


@pytest.fixture
def kc_admin(keycloak: Keycloak) -> Iterator[KeycloakAdmin]:
    admin = keycloak.admin()
    yield admin
    admin.close()


async def sign_in(
    client: httpx.AsyncClient, browser: Browser, username: str, next_path: str | None = None
) -> httpx.Response:
    started = await client.get(
        "/api/v1/auth/login", params={"next": next_path} if next_path else None
    )
    assert started.status_code == 302, started.text
    callback = browser.login(started.headers["location"], username)
    assert callback.startswith(f"{TEST_ORIGIN}/api/v1/auth/callback?"), callback
    return await client.get(callback)


async def sign_out(client: httpx.AsyncClient, browser: Browser, keycloak: Keycloak) -> None:
    """The SPA's Sign out: our 303 to Keycloak's end-session endpoint, which ends the
    Keycloak session (id_token_hint: no confirmation page) and comes back."""
    response = await client.post("/api/v1/auth/logout/redirect")
    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith(f"{keycloak.issuer}/protocol/openid-connect/logout?")
    assert set(query_of(location)) == {"client_id", "post_logout_redirect_uri", "id_token_hint"}
    back = browser.follow(location)
    assert back.status_code == 302, back.text
    assert back.headers["location"] == f"{TEST_ORIGIN}/login?signed_out=1"


async def signed_in_as(client: httpx.AsyncClient) -> str | None:
    me = await client.get("/api/v1/auth/me")
    return str(me.json()["display_name"]) if me.status_code == 200 else None


async def last_sign_in(db: AsyncSession) -> dict[str, Any]:
    entries = await audit_entries(db, "session.sign_in")
    return entries[-1].details


# --- The code flow and login matching -------------------------------------------------------
async def test_code_flow_links_by_verified_email_then_by_identity(
    client: httpx.AsyncClient, db_session: AsyncSession, browser: Browser, keycloak: Keycloak
) -> None:
    bob = await make_user(db_session, "Bob Brown", email="bob@example.com")

    first = await sign_in(client, browser, "bob", next_path="/ideas/CUST-3")

    assert first.status_code == 302
    assert first.headers["location"] == "/ideas/CUST-3"
    me = (await client.get("/api/v1/auth/me")).json()
    assert (me["id"], me["auth_method"]) == (str(bob.id), "sso")
    assert (await last_sign_in(db_session))["matched_by"] == "email"
    [identity] = list(await db_session.scalars(select(UserIdentity)))
    assert identity.issuer == keycloak.issuer
    assert identity.user_id == bob.id

    await sign_out(client, browser, keycloak)
    assert await signed_in_as(client) is None
    second = await sign_in(client, browser, "bob")  # Keycloak asks for the password again

    assert second.headers["location"] == "/"
    assert (await last_sign_in(db_session))["matched_by"] == "identity"


async def test_pre_created_user_links_by_external_id(
    client: httpx.AsyncClient, db_session: AsyncSession, browser: Browser
) -> None:
    carol = await make_user(db_session, "Carol Chen", email="carol.chen@corp.example")
    await add_external_id(db_session, carol, "employee_no", "e1003")  # case-insensitive

    await sign_in(client, browser, "carol")

    assert await signed_in_as(client) == "Carol Chen"
    assert (await last_sign_in(db_session))["matched_by"] == "external_id"


async def test_external_id_mismatch_needs_an_admin(
    client: httpx.AsyncClient, db_session: AsyncSession, browser: Browser
) -> None:
    alice = await make_user(db_session, "Alice", email="alice@example.com")
    await add_external_id(db_session, alice, "employee_no", "E9999")

    response = await sign_in(client, browser, "alice")

    assert response.headers["location"] == "/login?error=identity_conflict"
    [denied] = await audit_entries(db_session, "session.sign_in_denied")
    assert denied.details["reason"] == "external_id_mismatch"
    assert (denied.actor_id, denied.target_id) == (None, alice.id)


async def test_unknown_person_has_no_account(
    client: httpx.AsyncClient, db_session: AsyncSession, browser: Browser
) -> None:
    response = await sign_in(client, browser, "dave", next_path="/work")

    assert response.headers["location"] == "/login?error=no_account&next=%2Fwork"
    assert await signed_in_as(client) is None
    assert await db_session.scalar(select(User.id)) is None  # auto-create is off


@pytest.mark.settings(oidc_auto_create_users=True)
async def test_auto_create(
    client: httpx.AsyncClient, db_session: AsyncSession, browser: Browser
) -> None:
    await sign_in(client, browser, "erin")

    assert await signed_in_as(client) == "Erin Evans"
    assert (await last_sign_in(db_session))["matched_by"] == "created"


async def test_full_group_paths_match_mappings_typed_without_the_slash(
    client: httpx.AsyncClient, db_session: AsyncSession, browser: Browser
) -> None:
    erin = await make_user(db_session, "Erin", email="erin@example.com")
    viewers = await make_group(db_session, "Viewers", idp_values=["viewers"])
    leads = await make_group(db_session, "Innovation", idp_values=["/innovation"])

    await sign_in(client, browser, "erin")

    assert await memberships(db_session, erin) == {viewers.id: (False, True)}
    assert leads.id not in await memberships(db_session, erin)


# --- The acceptance scenario (SPEC section 13, contract section 3.13) -------------------------
async def arrange_acceptance(
    db: AsyncSession, mode: GroupSyncMode
) -> tuple[User, Any, Group, dict[str, Group]]:
    alice = await make_user(db, "Alice Anders", email="alice@example.com", platform_admin=True)
    carol = await make_user(db, "Carol Chen", email="carol@example.com")
    await add_external_id(db, carol, "employee_no", "E1003")
    project = await make_project(
        db,
        name="Acceptance",
        visibility=ProjectVisibility.PRIVATE,
        members={alice: ProjectRole.ADMIN},
    )
    cust = await make_project(db, name="Customer", visibility=ProjectVisibility.INTERNAL)
    names = {
        "/innovation/admins": "Innovation admins",
        "/innovation/members": "Innovation members",
        TOOLS: "Tools members",
        "/viewers": "Viewers",
    }
    groups = {
        path: await make_group(db, name, idp_values=[path], sync_mode=mode)
        for path, name in names.items()
    }
    await grant(db, cust, groups["/innovation/admins"], ProjectRole.ADMIN)
    await grant(db, cust, groups["/innovation/members"], ProjectRole.MEMBER)
    await grant(db, project, groups[TOOLS], ProjectRole.MEMBER)
    return carol, project, groups[TOOLS], groups


async def test_acceptance_removing_the_idp_group_removes_access_at_next_sign_in(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    browser: Browser,
    keycloak: Keycloak,
    kc_admin: KeycloakAdmin,
) -> None:
    carol, project, tools, groups = await arrange_acceptance(db_session, GroupSyncMode.MANAGED)
    assert TOOLS in kc_admin.groups_of("carol")

    # Carol signs in: linked by external ID, a synced member of the tools group, and a
    # member of the private project through it.
    await sign_in(client, browser, "carol")
    assert (await last_sign_in(db_session))["matched_by"] == "external_id"
    assert await memberships(db_session, carol) == {
        groups["/innovation/members"].id: (False, True),
        tools.id: (False, True),
    }
    assert await effective_role_of(db_session, carol.id, project.id) is ProjectRole.MEMBER
    assert (await client.get(f"/api/v1/projects/{project.slug}")).status_code == 200
    listed = (await client.get("/api/v1/projects")).json()
    assert project.slug in [item["slug"] for item in listed]

    kc_admin.remove_from_group("carol", TOOLS)
    try:
        # Her running session keeps the access until she signs in again.
        assert (await client.get(f"/api/v1/projects/{project.slug}")).status_code == 200

        await sign_out(client, browser, keycloak)
        await sign_in(client, browser, "carol")

        assert await signed_in_as(client) == "Carol Chen"
        assert (await last_sign_in(db_session))["matched_by"] == "identity"
        assert await memberships(db_session, carol) == {
            groups["/innovation/members"].id: (False, True)
        }
        synced = await audit_entries(db_session, "user.groups_sync")
        assert synced[-1].details["removed_group_ids"] == [str(tools.id)]
        assert synced[-1].details["claim_found"] is True
        assert (await client.get(f"/api/v1/projects/{project.slug}")).status_code == 404
        listed = (await client.get("/api/v1/projects")).json()
        assert project.slug not in [item["slug"] for item in listed]
    finally:
        kc_admin.add_to_group("carol", TOOLS)  # clean up for the next test


async def test_acceptance_additive_mapping_keeps_the_membership(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    browser: Browser,
    keycloak: Keycloak,
    kc_admin: KeycloakAdmin,
) -> None:
    carol, project, tools, _ = await arrange_acceptance(db_session, GroupSyncMode.ADDITIVE)
    await sign_in(client, browser, "carol")

    kc_admin.remove_from_group("carol", TOOLS)
    try:
        await sign_out(client, browser, keycloak)
        await sign_in(client, browser, "carol")

        assert (await memberships(db_session, carol))[tools.id] == (False, True)
        assert await effective_role_of(db_session, carol.id, project.id) is ProjectRole.MEMBER
    finally:
        kc_admin.add_to_group("carol", TOOLS)


async def test_acceptance_manual_membership_survives_sync(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    browser: Browser,
    keycloak: Keycloak,
    kc_admin: KeycloakAdmin,
) -> None:
    carol, project, tools, _ = await arrange_acceptance(db_session, GroupSyncMode.MANAGED)
    await add_to_group(db_session, tools, carol, manual=True, synced=False)
    await sign_in(client, browser, "carol")
    assert (await memberships(db_session, carol))[tools.id] == (True, True)

    kc_admin.remove_from_group("carol", TOOLS)
    try:
        await sign_out(client, browser, keycloak)
        await sign_in(client, browser, "carol")

        assert (await memberships(db_session, carol))[tools.id] == (True, False)
        assert await effective_role_of(db_session, carol.id, project.id) is ProjectRole.MEMBER
        assert (await client.get(f"/api/v1/projects/{project.slug}")).status_code == 200
    finally:
        kc_admin.add_to_group("carol", TOOLS)
