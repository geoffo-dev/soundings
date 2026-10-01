"""Phase 2 acceptance through the public HTTP API (QA; docs/test-plans/phase-2.md, AC2-API-*).

SPEC section 13, Phase 2: *Keycloak users get the right project access from their
groups; removing a group removes access at next sign-in (managed mapping).*

Identity's ``tests/identity/test_keycloak.py`` runs this scenario against a real
Keycloak, arranging groups and grants straight in the database; the e2e suite
(``e2e/tests/sso-acceptance.spec.ts``) clicks it through the browser. This module is the
contract-level version in between: **every arrangement and every check goes through the
admin API** a platform admin would use (external IDs, groups and mappings, group grants,
the access list, the mapping test, user detail, the audit viewer), with the sign-ins
answered by identity's fake OIDC provider (``tests/identity/fake_idp.py``), so it runs in
the normal backend check without Keycloak. It adds what the other two don't pin down:

* the audit trail of the whole story as the viewer returns it (actions, actors, targets,
  ``matched_by``, ``added``/``removed_group_ids``, ``claim_found``, ``auth_method``);
* ``list_project_access`` and ``AdminUser.project_roles`` naming the group as the source;
* a group-granted **admin** role that lets a member manage the project, and loses it;
* the mapping test's prediction checked against the next real sign-in;
* offboarding: deactivating ends the session at once and the next sign-in is refused.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.oidc import OidcProvider
from tests.conftest import Login
from tests.factories import make_user
from tests.identity.fake_idp import CLIENT_ID, CLIENT_SECRET, ISSUER, FakeIdp

API = "/api/v1"
TOOLS = "/tools/members"
INNOVATION = "/innovation/members"


@pytest.fixture
def settings_overrides() -> dict[str, Any]:
    return {
        "oidc_issuer": ISSUER,
        "oidc_client_id": CLIENT_ID,
        "oidc_client_secret": CLIENT_SECRET,
        "oidc_groups_claim": "groups",
        "oidc_external_id_claim": "employee_no",
        "dev_login_enabled": True,  # the admin works through the dev login, as in e2e
    }


@pytest.fixture
def idp(app: FastAPI) -> FakeIdp:
    fake = FakeIdp()
    app.state.oidc_provider = OidcProvider(app.state.settings, transport=fake.transport())
    return fake


def ok(response: httpx.Response, status: int = 200) -> Any:
    assert response.status_code == status, f"{response.request.url}: {response.text}"
    return response.json() if response.content else None


class Admin:
    """The platform admin's client (dev login session, CSRF header on writes)."""

    def __init__(self, http: httpx.AsyncClient) -> None:
        self.http = http

    async def get(self, path: str, **params: Any) -> Any:
        return ok(await self.http.get(API + path, params=params))

    async def send(self, method: str, path: str, body: Any = None, status: int = 200) -> Any:
        return ok(await self.http.request(method, API + path, json=body), status)

    async def audit(self, **filters: Any) -> list[dict[str, Any]]:
        page = await self.get("/admin/audit", limit=100, **filters)
        return list(page["items"])

    async def access(self, slug: str) -> dict[str, tuple[str, list[str]]]:
        """``{display name: (effective role, ["direct" | group name, ...])}``."""
        page = await self.get(f"/projects/{slug}/access", limit=100)
        return {
            entry["user"]["display_name"]: (
                entry["role"],
                [
                    "direct" if source["kind"] == "direct" else source["group"]["name"]
                    for source in entry["sources"]
                ],
            )
            for entry in page["items"]
        }


class Person:
    """Someone signing in with SSO in their own browser (cookie jar)."""

    def __init__(self, app: FastAPI, idp: FakeIdp, claims: dict[str, Any]) -> None:
        self.idp = idp
        self.claims = claims
        self.http = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://testserver",
        )

    async def sign_in(self, groups: list[str] | None, next_path: str = "/") -> str:
        """Signs in with these groups (None: no groups claim); returns where it lands."""
        claims = dict(self.claims)
        if groups is not None:
            claims["groups"] = groups
        started = await self.http.get(f"{API}/auth/login", params={"next": next_path})
        assert started.status_code == 302, started.text
        callback = await self.http.get(self.idp.authorize(started.headers["location"], claims))
        assert callback.status_code == 302, callback.text
        location = str(callback.headers["location"])
        if "soundings_csrf" in self.http.cookies:
            self.http.headers["X-CSRF-Token"] = self.http.cookies["soundings_csrf"]
        return location

    async def sign_out(self) -> None:
        response = await self.http.post(
            f"{API}/auth/logout/redirect",
            headers={"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"},
        )
        assert response.status_code == 303
        assert response.headers["location"].startswith(f"{ISSUER}/protocol/openid-connect/logout?")

    async def me(self) -> dict[str, Any] | None:
        response = await self.http.get(f"{API}/auth/me")
        return response.json() if response.status_code == 200 else None

    async def status_of(self, path: str) -> int:
        return (await self.http.get(API + path)).status_code

    async def project_slugs(self) -> list[str]:
        return [project["slug"] for project in ok(await self.http.get(f"{API}/projects"))]

    async def aclose(self) -> None:
        await self.http.aclose()


async def arrange(admin: Admin) -> dict[str, Any]:
    """The admin's side of contract §3.13 steps 0-1, all through the API."""
    acceptance = await admin.send(
        "POST",
        "/projects",
        {"name": "Acceptance", "slug": "acceptance", "key": "ACC", "visibility": "private"},
        201,
    )
    customer = await admin.send(
        "POST",
        "/projects",
        {"name": "Customer", "slug": "customer", "key": "CUS", "visibility": "internal"},
        201,
    )
    groups = {}
    for name, value, mode in (
        ("Innovation members", INNOVATION, "managed"),
        ("Tools members", TOOLS, "managed"),
        ("Leads", "/leads", "managed"),
    ):
        groups[name] = await admin.send(
            "POST", "/admin/groups", {"name": name, "sync_mode": mode, "idp_values": [value]}, 201
        )
    grants = (
        ("customer", "Innovation members", "member"),
        ("acceptance", "Tools members", "member"),
        ("acceptance", "Leads", "admin"),
    )
    for slug, group, role in grants:
        body = {"group_id": groups[group]["id"], "role": role}
        await admin.send("POST", f"/projects/{slug}/groups", body, 201)
    assert acceptance["my_role"] == "admin"  # Alice created it: its first admin
    return {"acceptance": acceptance, "customer": customer, "groups": groups}


async def test_managed_group_gives_and_takes_project_access_at_sign_in(
    app: FastAPI, db_session: AsyncSession, login: Login, idp: FakeIdp
) -> None:
    alice = await make_user(
        db_session, "Alice Anders", email="alice@example.com", platform_admin=True
    )
    carol = await make_user(db_session, "Carol Chen", email="carol@example.com")
    admin = Admin(await login(alice))
    state = await arrange(admin)
    tools = state["groups"]["Tools members"]
    innovation = state["groups"]["Innovation members"]

    # AC2-API-01: the admin gives Carol her employee number.
    await admin.send(
        "PUT",
        f"/admin/users/{carol.id}/external-ids",
        {"external_ids": [{"kind": "employee_no", "value": "E1003"}]},
    )

    # AC2-API-02: Carol signs in; her IdP groups make her a member of the private project.
    person = Person(
        app,
        idp,
        {
            "sub": "kc-carol",
            "employee_no": "E1003",
            "email": "carol@example.com",
            "email_verified": True,
            "name": "Carol from the IdP",
        },
    )
    try:
        assert (
            await person.sign_in([INNOVATION, TOOLS], next_path="/p/acceptance") == "/p/acceptance"
        )
        me = await person.me()
        assert me is not None
        assert (me["id"], me["display_name"], me["auth_method"]) == (
            str(carol.id),
            "Carol Chen",
            "sso",
        )
        assert await person.status_of("/projects/acceptance") == 200
        assert "acceptance" in await person.project_slugs()

        access = await admin.access("acceptance")
        assert access == {
            "Alice Anders": ("admin", ["direct"]),
            "Carol Chen": ("member", ["Tools members"]),
        }
        detail = await admin.get(f"/admin/users/{carol.id}")
        assert [(i["issuer"], i["subject"]) for i in detail["identities"]] == [(ISSUER, "kc-carol")]
        assert {(g["group"]["name"], g["manual"], g["synced"]) for g in detail["groups"]} == {
            ("Innovation members", False, True),
            ("Tools members", False, True),
        }
        roles = {r["project"]["slug"]: (r["role"], r["sources"]) for r in detail["project_roles"]}
        assert roles["acceptance"][0] == "member"
        assert [s["group"]["name"] for s in roles["acceptance"][1]] == ["Tools members"]

        # The audit trail of that sign-in, as the viewer returns it.
        [link] = await admin.audit(action="user.identity_link", target_id=str(carol.id))
        assert link["details"]["matched_by"] == "external_id"
        assert link["details"]["issuer"] == ISSUER
        [sign_in] = await admin.audit(action="session.sign_in", actor_id=str(carol.id))
        assert sign_in["details"]["method"] == "sso"
        assert sign_in["details"]["matched_by"] == "external_id"
        [sync] = await admin.audit(action="user.groups_sync", target_id=str(carol.id))
        assert sorted(sync["details"]["added_group_ids"]) == sorted([tools["id"], innovation["id"]])
        assert sync["details"]["removed_group_ids"] == []
        assert sync["details"]["claim_found"] is True
        assert sync["target_label"] == "Carol Chen"
        # No email, name or claim set in any entry about her.
        assert "carol@example.com" not in str(await admin.audit(target_id=str(carol.id)))
        assert "Carol from the IdP" not in str(await admin.audit(target_id=str(carol.id)))

        # AC2-API-03: the mapping test predicts the next sign-in without changing anything.
        predicted = await admin.send(
            "POST",
            "/admin/groups/test-mapping",
            {"claims": {"groups": [INNOVATION]}, "user_id": str(carol.id)},
        )
        effects = {g["group"]["name"]: g["effect"] for g in predicted["groups"]}
        assert effects == {"Innovation members": "keep", "Tools members": "remove"}
        assert "acceptance" not in [r["project"]["slug"] for r in predicted["project_roles"]]
        assert (await admin.access("acceptance"))["Carol Chen"] == ("member", ["Tools members"])

        # AC2-API-04: removed from the IdP group. Her running session keeps the access…
        assert await person.status_of("/projects/acceptance") == 200
        await person.sign_out()
        assert await person.me() is None
        # …until her next sign-in, which removes the synced membership and the access.
        assert await person.sign_in([INNOVATION]) == "/"
        assert await person.status_of("/projects/acceptance") == 404
        assert "acceptance" not in await person.project_slugs()
        assert "Carol Chen" not in await admin.access("acceptance")
        assert await person.status_of("/projects/customer") == 200  # still in Innovation
        syncs = await admin.audit(action="user.groups_sync", target_id=str(carol.id))
        assert syncs[0]["details"]["removed_group_ids"] == [tools["id"]]
        assert syncs[0]["details"]["added_group_ids"] == []
        members = await admin.get(f"/admin/groups/{tools['id']}/members")
        assert members["items"] == []
        # The prediction held: what the mapping test said is what happened.
        after = {
            g["group"]["name"] for g in (await admin.get(f"/admin/users/{carol.id}"))["groups"]
        }
        assert after == {"Innovation members"}

        # AC2-API-05: no groups claim at all (in no IdP group) removes the rest, fail closed.
        await person.sign_out()
        await person.sign_in(None)
        assert (await admin.get(f"/admin/users/{carol.id}"))["groups"] == []
        [last, *_] = await admin.audit(action="user.groups_sync", target_id=str(carol.id))
        assert last["details"]["claim_found"] is False
        assert last["details"]["removed_group_ids"] == [innovation["id"]]

        # AC2-API-06: offboarding = deactivate: the session ends now, sign-in is refused.
        await admin.send("PATCH", f"/admin/users/{carol.id}", {"is_active": False})
        assert await person.me() is None
        assert await person.sign_in([INNOVATION, TOOLS]) == "/login?error=account_disabled"
        [denied, *_] = await admin.audit(action="session.sign_in_denied")
        assert denied["actor_id"] is None
        assert (denied["target_id"], denied["details"]["reason"]) == (
            str(carol.id),
            "account_disabled",
        )
    finally:
        await person.aclose()


async def test_additive_and_manual_memberships_and_a_group_granted_admin_role(
    app: FastAPI, db_session: AsyncSession, login: Login, idp: FakeIdp
) -> None:
    alice = await make_user(
        db_session, "Alice Anders", email="alice@example.com", platform_admin=True
    )
    dave = await make_user(db_session, "Dave Davies", email="dave@example.com")
    erin = await make_user(db_session, "Erin Evans", email="erin@example.com")
    admin = Admin(await login(alice))
    state = await arrange(admin)
    tools = state["groups"]["Tools members"]
    leads = state["groups"]["Leads"]

    # AC2-API-07: an additive mapping (changed through the API) keeps the membership.
    await admin.send(
        "PUT",
        f"/admin/groups/{tools['id']}/mapping",
        {"sync_mode": "additive", "idp_values": [TOOLS]},
    )
    claims = {"sub": "kc-erin", "email": "erin@example.com", "email_verified": True}
    erin_browser = Person(app, idp, claims)
    # AC2-API-08: a manual member (added through the API) of a managed group stays.
    await admin.send("POST", f"/admin/groups/{leads['id']}/members", {"user_id": str(dave.id)}, 201)
    dave_browser = Person(
        app, idp, {"sub": "kc-dave", "email": "dave@example.com", "email_verified": True}
    )
    try:
        await erin_browser.sign_in([TOOLS])  # linked by verified email
        assert await erin_browser.status_of("/projects/acceptance") == 200
        await erin_browser.sign_out()
        await erin_browser.sign_in([])
        assert await erin_browser.status_of("/projects/acceptance") == 200
        assert (await admin.access("acceptance"))["Erin Evans"] == ("member", ["Tools members"])
        member = (await admin.get(f"/admin/groups/{tools['id']}/members"))["items"]
        assert [(m["user"]["id"], m["manual"], m["synced"]) for m in member] == [
            (str(erin.id), False, True)
        ]
        # Removing it takes an admin; the next sign-in with the value brings it back.
        await admin.send("DELETE", f"/admin/groups/{tools['id']}/members/{erin.id}", status=204)
        assert await erin_browser.status_of("/projects/acceptance") == 404
        await erin_browser.sign_out()
        await erin_browser.sign_in([TOOLS])
        assert await erin_browser.status_of("/projects/acceptance") == 200

        # AC2-API-09: Dave, a manual member of Leads (admin of the project), signs in with
        # the Leads value too, then without it: he stays a manual member and an admin.
        await dave_browser.sign_in(["/leads"])
        groups = (await admin.get(f"/admin/users/{dave.id}"))["groups"]
        assert [(g["group"]["name"], g["manual"], g["synced"]) for g in groups] == [
            ("Leads", True, True)
        ]
        await dave_browser.sign_out()
        await dave_browser.sign_in([])
        groups = (await admin.get(f"/admin/users/{dave.id}"))["groups"]
        assert [(g["group"]["name"], g["manual"], g["synced"]) for g in groups] == [
            ("Leads", True, False)
        ]
        assert (await admin.access("acceptance"))["Dave Davies"] == ("admin", ["Leads"])

        # AC2-API-10: the group-granted admin role is a real one: Dave manages members…
        add_erin = {"user_id": str(erin.id), "role": "viewer"}
        response = await dave_browser.http.post(f"{API}/projects/acceptance/members", json=add_erin)
        assert response.status_code == 201, response.text
        # …until an admin takes him out of the group: roles are evaluated live.
        await admin.send("DELETE", f"/admin/groups/{leads['id']}/members/{dave.id}", status=204)
        response = await dave_browser.http.delete(f"{API}/projects/acceptance/members/{erin.id}")
        assert response.status_code == 404  # private project, no role left: not even visible
        entries = await admin.audit(action="group.member_remove", target_id=leads["id"])
        details = entries[0]["details"]
        assert details["auth_method"] == "dev_login"
        assert (details["user_id"], details["manual"], details["synced"]) == (
            str(dave.id),
            True,
            False,
        )
    finally:
        await erin_browser.aclose()
        await dave_browser.aclose()
