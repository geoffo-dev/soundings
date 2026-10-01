"""The API contract (Phases 1 and 2): every route exists with its operation_id and,
until it is implemented, answers 501 problem+json to a *valid* request.

When you implement an endpoint, delete its row from ``STUBS`` (the operation stays
in ``CONTRACT``). ``CONTRACT`` changes only with the lead (it is the frontend's API).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute

from app.api.deps import get_current_user
from app.api.v1 import (
    activity,
    admin_audit,
    admin_groups,
    admin_sso,
    admin_users,
    auth,
    auth_sso,
    evaluations,
    groups,
    ideas,
    project_groups,
    projects,
    search,
    users,
    work,
)
from app.api.v1.principal import get_principal
from app.config import BACKEND_DIR
from app.models.user import User
from app.openapi import export_openapi

IDEA = "0b7c7d1e-7a55-4a4f-9b8b-0d7d3a9d1c11"
USER = "5f0e8a52-3c1d-4b8e-9a6f-2d7c4e1b9a03"
GROUP = "8c2d6f14-9e3b-4a7d-b1c5-6e0f2a8d4b17"
IDENTITY = "1a4b7c0d-2e5f-4a8b-9c3d-6e9f0a1b2c3d"

# (method, path template, operation_id)
CONTRACT: list[tuple[str, str, str]] = [
    ("GET", "/api/v1/auth/me", "get_me"),
    ("GET", "/api/v1/auth/dev/users", "list_dev_users"),
    ("POST", "/api/v1/auth/dev/login", "dev_login"),
    ("POST", "/api/v1/auth/logout", "logout"),
    ("GET", "/api/v1/users", "search_users"),
    ("GET", "/api/v1/projects", "list_projects"),
    ("POST", "/api/v1/projects", "create_project"),
    ("GET", "/api/v1/projects/{slug}", "get_project"),
    ("PATCH", "/api/v1/projects/{slug}", "update_project"),
    ("GET", "/api/v1/projects/{slug}/members", "list_project_members"),
    ("POST", "/api/v1/projects/{slug}/members", "add_project_member"),
    ("PATCH", "/api/v1/projects/{slug}/members/{user_id}", "update_project_member"),
    ("DELETE", "/api/v1/projects/{slug}/members/{user_id}", "remove_project_member"),
    ("PUT", "/api/v1/projects/{slug}/rubric", "replace_rubric"),
    ("GET", "/api/v1/projects/{slug}/tags", "list_project_tags"),
    ("GET", "/api/v1/projects/{slug}/ideas", "list_ideas"),
    ("POST", "/api/v1/projects/{slug}/ideas", "create_idea"),
    ("GET", "/api/v1/projects/{slug}/board", "get_board"),
    ("GET", "/api/v1/ideas/{idea}", "get_idea"),
    ("PATCH", "/api/v1/ideas/{idea}", "update_idea"),
    ("DELETE", "/api/v1/ideas/{idea}", "delete_idea"),
    ("POST", "/api/v1/ideas/{idea}/status", "change_idea_status"),
    ("PUT", "/api/v1/ideas/{idea}/owner", "set_idea_owner"),
    ("POST", "/api/v1/ideas/{idea}/volunteer", "volunteer_as_owner"),
    ("POST", "/api/v1/ideas/{idea}/evaluators", "add_evaluators"),
    ("DELETE", "/api/v1/ideas/{idea}/evaluators/{user_id}", "remove_evaluator"),
    ("PUT", "/api/v1/ideas/{idea}/evaluation/due-date", "set_evaluation_due_date"),
    ("POST", "/api/v1/ideas/{idea}/evaluation/close", "close_evaluation"),
    ("POST", "/api/v1/ideas/{idea}/evaluation/reopen", "reopen_evaluation"),
    ("GET", "/api/v1/ideas/{idea}/evaluations", "list_evaluations"),
    ("GET", "/api/v1/ideas/{idea}/evaluations/me", "get_my_evaluation"),
    ("PUT", "/api/v1/ideas/{idea}/evaluations/me", "save_my_evaluation"),
    ("PUT", "/api/v1/ideas/{idea}/vote", "vote_idea"),
    ("DELETE", "/api/v1/ideas/{idea}/vote", "unvote_idea"),
    ("PUT", "/api/v1/ideas/{idea}/watch", "watch_idea"),
    ("DELETE", "/api/v1/ideas/{idea}/watch", "unwatch_idea"),
    ("GET", "/api/v1/ideas/{idea}/activity", "list_idea_activity"),
    ("POST", "/api/v1/ideas/{idea}/comments", "create_comment"),
    ("PATCH", "/api/v1/comments/{comment_id}", "update_comment"),
    ("DELETE", "/api/v1/comments/{comment_id}", "delete_comment"),
    ("GET", "/api/v1/me/work", "get_my_work"),
    ("GET", "/api/v1/me/owned-ideas", "list_my_owned_ideas"),
    ("GET", "/api/v1/search", "global_search"),
    # --- Phase 2: sign-in and access (docs/api/contract-phase2.md) -------------------
    ("GET", "/api/v1/auth/config", "get_auth_config"),
    ("GET", "/api/v1/auth/login", "sso_login"),
    ("GET", "/api/v1/auth/callback", "sso_callback"),
    ("POST", "/api/v1/auth/break-glass", "break_glass_login"),
    ("POST", "/api/v1/auth/logout/redirect", "logout_redirect"),
    ("GET", "/api/v1/admin/users", "list_admin_users"),
    ("POST", "/api/v1/admin/users", "create_admin_user"),
    ("GET", "/api/v1/admin/users/{user_id}", "get_admin_user"),
    ("PATCH", "/api/v1/admin/users/{user_id}", "update_admin_user"),
    ("PUT", "/api/v1/admin/users/{user_id}/external-ids", "replace_user_external_ids"),
    ("DELETE", "/api/v1/admin/users/{user_id}/identities/{identity_id}", "unlink_user_identity"),
    ("DELETE", "/api/v1/admin/users/{user_id}/sessions", "end_user_sessions"),
    ("GET", "/api/v1/admin/groups", "list_admin_groups"),
    ("POST", "/api/v1/admin/groups", "create_group"),
    ("POST", "/api/v1/admin/groups/test-mapping", "test_group_mapping"),
    ("GET", "/api/v1/admin/groups/{group_id}", "get_group"),
    ("PATCH", "/api/v1/admin/groups/{group_id}", "update_group"),
    ("DELETE", "/api/v1/admin/groups/{group_id}", "delete_group"),
    ("PUT", "/api/v1/admin/groups/{group_id}/mapping", "replace_group_mapping"),
    ("GET", "/api/v1/admin/groups/{group_id}/members", "list_group_members"),
    ("POST", "/api/v1/admin/groups/{group_id}/members", "add_group_member"),
    ("DELETE", "/api/v1/admin/groups/{group_id}/members/{user_id}", "remove_group_member"),
    ("GET", "/api/v1/groups", "search_groups"),
    ("GET", "/api/v1/projects/{slug}/groups", "list_project_group_grants"),
    ("POST", "/api/v1/projects/{slug}/groups", "add_project_group_grant"),
    ("PATCH", "/api/v1/projects/{slug}/groups/{group_id}", "update_project_group_grant"),
    ("DELETE", "/api/v1/projects/{slug}/groups/{group_id}", "remove_project_group_grant"),
    ("GET", "/api/v1/projects/{slug}/access", "list_project_access"),
    ("GET", "/api/v1/admin/audit", "list_audit_entries"),
    ("GET", "/api/v1/admin/sso", "get_sso_config"),
]

# operation_id -> a valid request (url with query string, JSON body or None) for the
# Phase 2 admin, group and access operations (implemented; tests/admin covers them).
PHASE2_REQUESTS: dict[str, tuple[str, dict[str, Any] | None]] = {
    "list_admin_users": (
        "/api/v1/admin/users?q=ada&active=true&platform_admin=false&has_identity=false",
        None,
    ),
    "create_admin_user": (
        "/api/v1/admin/users",
        {
            "email": "ada@example.com",
            "display_name": "Ada Lovelace",
            "external_ids": [{"kind": "employee_no", "value": "E1001"}],
        },
    ),
    "get_admin_user": (f"/api/v1/admin/users/{USER}", None),
    "update_admin_user": (f"/api/v1/admin/users/{USER}", {"is_active": False}),
    "replace_user_external_ids": (
        f"/api/v1/admin/users/{USER}/external-ids",
        {"external_ids": [{"kind": "gitlab", "value": "ada"}]},
    ),
    "unlink_user_identity": (f"/api/v1/admin/users/{USER}/identities/{IDENTITY}", None),
    "end_user_sessions": (f"/api/v1/admin/users/{USER}/sessions", None),
    "list_admin_groups": ("/api/v1/admin/groups?q=inno&limit=10", None),
    "create_group": (
        "/api/v1/admin/groups",
        {"name": "Innovation admins", "idp_values": ["/innovation/admins"]},
    ),
    "test_group_mapping": (
        "/api/v1/admin/groups/test-mapping",
        {"claims": {"sub": "x", "groups": ["/innovation/admins", 7]}, "user_id": USER},
    ),
    "get_group": (f"/api/v1/admin/groups/{GROUP}", None),
    "update_group": (f"/api/v1/admin/groups/{GROUP}", {"description": "Leads"}),
    "delete_group": (f"/api/v1/admin/groups/{GROUP}", None),
    "replace_group_mapping": (
        f"/api/v1/admin/groups/{GROUP}/mapping",
        {"sync_mode": "additive", "idp_values": []},
    ),
    "list_group_members": (f"/api/v1/admin/groups/{GROUP}/members?q=ada&limit=10", None),
    "add_group_member": (f"/api/v1/admin/groups/{GROUP}/members", {"user_id": USER}),
    "remove_group_member": (f"/api/v1/admin/groups/{GROUP}/members/{USER}", None),
    "search_groups": ("/api/v1/groups?q=inno&limit=5", None),
    "list_project_group_grants": ("/api/v1/projects/cust/groups", None),
    "add_project_group_grant": (
        "/api/v1/projects/cust/groups",
        {"group_id": GROUP, "role": "admin"},
    ),
    "update_project_group_grant": (f"/api/v1/projects/cust/groups/{GROUP}", {"role": "viewer"}),
    "remove_project_group_grant": (f"/api/v1/projects/cust/groups/{GROUP}", None),
    "list_project_access": ("/api/v1/projects/cust/access?q=ada&role=admin", None),
    "list_audit_entries": (
        f"/api/v1/admin/audit?actor_id={USER}&action=session.sign_in&action=group.create"
        "&target_type=group&project_id=" + IDEA + "&since=2026-10-01T00:00:00Z"
        "&until=2026-10-02T00:00:00%2B01:00",
        None,
    ),
    "get_sso_config": ("/api/v1/admin/sso", None),
}

# operation_id -> a valid request for every operation still answered with 501. Every
# Phase 1 and Phase 2 operation is implemented and tested (tests/api, tests/ideas,
# tests/identity, tests/admin). Add a row per stub; delete it when you implement it.
STUBS: dict[str, tuple[str, dict[str, Any] | None]] = {}

PUBLIC_OPERATIONS = frozenset(
    {
        "list_dev_users",
        "dev_login",
        "logout",
        "get_auth_config",
        "sso_login",
        "sso_callback",
        "break_glass_login",
        "logout_redirect",
    }
)
"""Operations that need no session (sign-in and sign-out)."""

_METHODS = {operation_id: method for method, _, operation_id in CONTRACT}


def _feature_routes() -> list[APIRoute]:
    return [
        route
        for module in (
            activity,
            admin_audit,
            admin_groups,
            admin_sso,
            admin_users,
            auth,
            auth_sso,
            evaluations,
            groups,
            ideas,
            project_groups,
            projects,
            search,
            users,
            work,
        )
        for route in module.router.routes
        if isinstance(route, APIRoute)
    ]


@pytest.fixture
def signed_in(app: FastAPI) -> Iterator[None]:
    """Stand-in user so requests get past authentication to the stub itself."""

    def fake_user() -> User:
        return User(id=uuid4(), email="ada@example.com", display_name="Ada Lovelace")

    app.dependency_overrides[get_current_user] = fake_user
    yield
    app.dependency_overrides.pop(get_current_user, None)


async def test_routes_match_the_contract(client: httpx.AsyncClient) -> None:
    document = (await client.get("/api/v1/openapi.json")).json()
    operations = {
        (method.upper(), path, operation["operationId"])
        for path, item in document["paths"].items()
        if path.startswith("/api/v1/")
        for method, operation in item.items()
    }

    assert operations == set(CONTRACT)


def test_operation_ids_are_explicit_and_match_function_names() -> None:
    routes = _feature_routes()

    assert len(routes) == len(CONTRACT)
    for route in routes:
        assert route.operation_id == route.name, route.path


def test_every_stub_has_a_contract_entry() -> None:
    assert set(STUBS) <= set(_METHODS)
    assert set(PHASE2_REQUESTS) <= set(_METHODS)


async def test_openapi_lists_every_operation(client: httpx.AsyncClient) -> None:
    document = (await client.get("/api/v1/openapi.json")).json()

    for method, path, operation_id in CONTRACT:
        operation = document["paths"][path][method.lower()]
        assert operation["operationId"] == operation_id
        assert operation["summary"], operation_id
        assert operation["tags"], operation_id
        assert "default" in operation["responses"], operation_id


@pytest.mark.usefixtures("signed_in")
@pytest.mark.parametrize("operation_id", sorted(STUBS))
async def test_stub_returns_501_problem(client: httpx.AsyncClient, operation_id: str) -> None:
    url, body = STUBS[operation_id]

    response = await client.request(_METHODS[operation_id], url, json=body)

    assert response.status_code == 501, response.text
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "not_implemented"


async def test_authentication_dependency_is_wired(client: httpx.AsyncClient) -> None:
    # Without the override the session lookup answers before the stub.
    response = await client.get("/api/v1/me/work")

    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


async def test_invalid_request_is_rejected_before_the_stub(
    client: httpx.AsyncClient, signed_in: None
) -> None:
    response = await client.post(
        f"/api/v1/ideas/{IDEA}/status",
        json={"status": "closed"},  # no resolution
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_frontend_contract_is_up_to_date(app: FastAPI) -> None:
    """frontend/src/api/generated/openapi.json must match the code.

    Regenerate: make -C backend openapi OPENAPI_OUT=../frontend/src/api/generated/openapi.json
    && npm --prefix frontend run gen:api
    """
    exported = BACKEND_DIR.parent / "frontend" / "src" / "api" / "generated" / "openapi.json"
    if not exported.exists():
        pytest.skip("frontend checkout not present")

    assert json.loads(Path(exported).read_text()) == json.loads(export_openapi(app))


async def test_no_two_paths_share_a_template(client: httpx.AsyncClient) -> None:
    """OpenAPI 3.1: templated paths that differ only in parameter names must not exist."""
    document = (await client.get("/api/v1/openapi.json")).json()
    shapes = [re.sub(r"\{[^}]+\}", "{}", path) for path in document["paths"]]

    assert len(shapes) == len(set(shapes))


def test_every_idea_route_names_the_idea_the_same_way() -> None:
    idea_paths = {path for _, path, _ in CONTRACT if path.startswith("/api/v1/ideas/")}

    assert idea_paths
    assert all(path.startswith("/api/v1/ideas/{idea}") for path in idea_paths)


def test_signed_in_routes_take_the_principal() -> None:
    for route in _feature_routes():
        calls = {dependency.call for dependency in route.dependant.dependencies}
        assert (get_principal in calls) == (route.name not in PUBLIC_OPERATIONS), route.name


async def test_public_stubs_need_no_session(client: httpx.AsyncClient) -> None:
    """Sign-in routes answer without a session (here: 501, not 401)."""
    for operation_id in sorted(PUBLIC_OPERATIONS & set(STUBS)):
        url, body = STUBS[operation_id]
        response = await client.request(_METHODS[operation_id], url, json=body)
        assert response.status_code == 501, (operation_id, response.text)


async def test_admin_routes_need_a_session(client: httpx.AsyncClient) -> None:
    requests = PHASE2_REQUESTS | STUBS
    for operation_id in sorted(set(requests) - PUBLIC_OPERATIONS):
        url, body = requests[operation_id]
        response = await client.request(_METHODS[operation_id], url, json=body)
        assert response.status_code == 401, (operation_id, response.text)


def test_redirect_routes_document_their_location() -> None:
    redirects = {"sso_login": 302, "sso_callback": 302, "logout_redirect": 303}
    for route in _feature_routes():
        if route.name in redirects:
            assert route.status_code == redirects[route.name], route.name
            assert "Location" in route.responses[route.status_code]["headers"], route.name


@pytest.mark.usefixtures("signed_in")
@pytest.mark.parametrize(
    ("operation_id", "body"),
    [
        ("create_group", {"name": "x", "idp_values": [" / "]}),
        ("create_group", {"name": "x", "idp_values": ["v"] * 51}),
        ("create_admin_user", {"email": "not-an-email", "display_name": "A"}),
        (
            "create_admin_user",
            {
                "email": "a@example.com",
                "display_name": "A",
                "external_ids": [
                    {"kind": "gitlab", "value": "a"},
                    {"kind": "gitlab", "value": "b"},
                ],
            },
        ),
        ("replace_user_external_ids", {"external_ids": [{"kind": "Employee No", "value": "1"}]}),
        ("test_group_mapping", {"claims": ["not", "an", "object"]}),
        ("add_project_group_grant", {"group_id": GROUP, "role": "owner"}),
    ],
)
async def test_invalid_phase2_bodies_are_rejected_before_the_endpoint(
    client: httpx.AsyncClient, operation_id: str, body: dict[str, Any]
) -> None:
    url, _ = PHASE2_REQUESTS[operation_id]

    response = await client.request(_METHODS[operation_id], url, json=body)

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "validation_error"


@pytest.mark.usefixtures("signed_in")
@pytest.mark.parametrize("ref", ["CUST12", "cust-0", "12", "not a key", "0b7c7d1e-7a55"])
async def test_malformed_idea_reference_is_rejected(client: httpx.AsyncClient, ref: str) -> None:
    response = await client.get(f"/api/v1/ideas/{ref}")

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
