"""Every admin, group and project-access route: 401 without a session, 403
``csrf_failed`` for writes without the CSRF header, 403 ``forbidden`` for people who
are not platform admins (before anything about the resource: an unknown id is still
403), and the check order (a malformed body is 422 before that 403)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx
import pytest

from tests.admin.conftest import API, People, assert_problem
from tests.conftest import Login
from tests.test_contract_routes import CONTRACT

UNKNOWN = str(uuid4())

# operation_id -> (method, path, valid body); unknown ids on purpose.
ADMIN_ROUTES: dict[str, tuple[str, str, Any]] = {
    "list_admin_users": ("GET", "/admin/users", None),
    "create_admin_user": ("POST", "/admin/users", {"email": "n@example.com", "display_name": "N"}),
    "get_admin_user": ("GET", f"/admin/users/{UNKNOWN}", None),
    "update_admin_user": ("PATCH", f"/admin/users/{UNKNOWN}", {"is_active": False}),
    "replace_user_external_ids": (
        "PUT",
        f"/admin/users/{UNKNOWN}/external-ids",
        {"external_ids": []},
    ),
    "unlink_user_identity": ("DELETE", f"/admin/users/{UNKNOWN}/identities/{UNKNOWN}", None),
    "end_user_sessions": ("DELETE", f"/admin/users/{UNKNOWN}/sessions", None),
    "list_admin_groups": ("GET", "/admin/groups", None),
    "create_group": ("POST", "/admin/groups", {"name": "Leads"}),
    "test_group_mapping": ("POST", "/admin/groups/test-mapping", {"claims": {}}),
    "get_group": ("GET", f"/admin/groups/{UNKNOWN}", None),
    "update_group": ("PATCH", f"/admin/groups/{UNKNOWN}", {"name": "Leads"}),
    "delete_group": ("DELETE", f"/admin/groups/{UNKNOWN}", None),
    "replace_group_mapping": (
        "PUT",
        f"/admin/groups/{UNKNOWN}/mapping",
        {"sync_mode": "managed", "idp_values": []},
    ),
    "list_group_members": ("GET", f"/admin/groups/{UNKNOWN}/members", None),
    "add_group_member": ("POST", f"/admin/groups/{UNKNOWN}/members", {"user_id": UNKNOWN}),
    "remove_group_member": ("DELETE", f"/admin/groups/{UNKNOWN}/members/{UNKNOWN}", None),
    "list_audit_entries": ("GET", "/admin/audit", None),
    "get_sso_config": ("GET", "/admin/sso", None),
}
OTHER_ROUTES: dict[str, tuple[str, str, Any]] = {
    "search_groups": ("GET", "/groups", None),
    "list_project_group_grants": ("GET", "/projects/{slug}/groups", None),
    "add_project_group_grant": ("POST", "/projects/{slug}/groups", {"group_id": UNKNOWN}),
    "update_project_group_grant": (
        "PATCH",
        f"/projects/{{slug}}/groups/{UNKNOWN}",
        {"role": "admin"},
    ),
    "remove_project_group_grant": ("DELETE", f"/projects/{{slug}}/groups/{UNKNOWN}", None),
    "list_project_access": ("GET", "/projects/{slug}/access", None),
}
ROUTES = ADMIN_ROUTES | OTHER_ROUTES
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def test_every_route_of_the_area_is_covered() -> None:
    mine = {
        operation_id
        for _, path, operation_id in CONTRACT
        if (
            path.startswith(("/api/v1/admin/", "/api/v1/groups"))
            or path.endswith(("/groups", "/groups/{group_id}", "/access"))
        )
        # Phase 3 Admin -> Email (/admin/email...), Phase 4 Admin -> Branding
        # (/admin/branding...) and Phase 5 Admin -> API keys (/admin/api-keys...) get
        # their own guard tests.
        and not path.startswith(
            ("/api/v1/admin/email", "/api/v1/admin/branding", "/api/v1/admin/api-keys")
        )
    }
    assert mine == set(ROUTES)


def _url(template: str, people: People) -> str:
    return API + template.format(slug=people.slug)


@pytest.mark.parametrize("operation_id", sorted(ROUTES))
async def test_needs_a_session(
    client: httpx.AsyncClient, people: People, operation_id: str
) -> None:
    method, template, body = ROUTES[operation_id]
    response = await client.request(method, _url(template, people), json=body)
    assert_problem(response, 401, "unauthorized")


@pytest.mark.parametrize("operation_id", sorted(op for op, r in ROUTES.items() if r[0] in UNSAFE))
async def test_writes_need_the_csrf_header(login: Login, people: People, operation_id: str) -> None:
    method, template, body = ROUTES[operation_id]
    http = await login(people.admin)
    del http.headers["X-CSRF-Token"]

    response = await http.request(method, _url(template, people), json=body)

    assert_problem(response, 403, "csrf_failed")


@pytest.mark.parametrize("operation_id", sorted(ADMIN_ROUTES))
async def test_admin_routes_are_for_platform_admins_only(
    login: Login, people: People, operation_id: str
) -> None:
    """A project admin is not a platform admin: 403, even for an unknown id."""
    method, template, body = ADMIN_ROUTES[operation_id]
    http = await login(people.lead)

    response = await http.request(method, _url(template, people), json=body)

    assert_problem(response, 403, "forbidden")


async def test_shape_errors_come_before_forbidden(login: Login, people: People) -> None:
    http = await login(people.bob)

    response = await http.post(f"{API}/admin/groups", json={"name": ""})
    not_uuid = await http.get(f"{API}/admin/users/not-a-uuid")

    assert_problem(response, 422, "validation_error")
    assert_problem(not_uuid, 422, "validation_error")
