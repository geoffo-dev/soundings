"""The Phase 1 API contract: every route exists with its operation_id and, until it is
implemented, answers 501 problem+json to a *valid* request.

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
from app.api.v1 import activity, auth, evaluations, ideas, projects, search, users, work
from app.api.v1.principal import get_principal
from app.config import BACKEND_DIR
from app.models.user import User
from app.openapi import export_openapi

IDEA = "0b7c7d1e-7a55-4a4f-9b8b-0d7d3a9d1c11"
USER = "5f0e8c1a-2b3c-4d5e-8f90-a1b2c3d4e5f6"
COMMENT = "9d8c7b6a-5f4e-4d3c-8b2a-190817161514"
CRITERION = "1a2b3c4d-5e6f-4a1b-9c2d-3e4f5a6b7c8d"

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
]

# operation_id -> a valid request (url with query string, JSON body or None).
STUBS: dict[str, tuple[str, dict[str, Any] | None]] = {
    "get_me": ("/api/v1/auth/me", None),
    "list_dev_users": ("/api/v1/auth/dev/users", None),
    "dev_login": ("/api/v1/auth/dev/login", {"user_id": USER}),
    "logout": ("/api/v1/auth/logout", None),
    "search_users": ("/api/v1/users?q=ada&project=customer-innovation&limit=10", None),
    "list_projects": ("/api/v1/projects?include_archived=true", None),
    "create_project": (
        "/api/v1/projects",
        {"name": "Customer Innovation", "slug": "customer-innovation", "key": "CUST"},
    ),
    "get_project": ("/api/v1/projects/customer-innovation", None),
    "update_project": (
        "/api/v1/projects/customer-innovation",
        {"allow_volunteer_owners": False, "status_labels": {"shortlisted": "Short list"}},
    ),
    "list_project_members": ("/api/v1/projects/customer-innovation/members", None),
    "add_project_member": (
        "/api/v1/projects/customer-innovation/members",
        {"user_id": USER, "role": "member"},
    ),
    "update_project_member": (
        f"/api/v1/projects/customer-innovation/members/{USER}",
        {"role": "admin"},
    ),
    "remove_project_member": (f"/api/v1/projects/customer-innovation/members/{USER}", None),
    "replace_rubric": (
        "/api/v1/projects/customer-innovation/rubric",
        {
            "criteria": [
                {"id": CRITERION, "name": "Value", "guidance": {"1": "None", "5": "Huge"}},
                {"name": "Effort", "weight": 1.25, "inverted": True},
                {"name": "Fit", "description": "Strategic fit."},
            ]
        },
    ),
    "list_project_tags": ("/api/v1/projects/customer-innovation/tags", None),
    "list_ideas": (
        "/api/v1/projects/customer-innovation/ideas?status=new&status=evaluating&owner=me"
        "&tag=ux&needs_evaluators=true&q=pricing&sort=-score&limit=25&resolution=parked",
        None,
    ),
    "create_idea": (
        "/api/v1/projects/customer-innovation/ideas",
        {"title": "Self-service refunds", "summary": "Let customers refund.", "tags": ["UX"]},
    ),
    "get_board": (f"/api/v1/projects/customer-innovation/board?owner={USER}&limit=20", None),
    "get_idea": ("/api/v1/ideas/CUST-12", None),
    # Every idea route takes the UUID or the key.
    "update_idea": ("/api/v1/ideas/cust-12", {"title": "Refunds in one click"}),
    "delete_idea": (f"/api/v1/ideas/{IDEA}", None),
    "change_idea_status": (
        f"/api/v1/ideas/{IDEA}/status",
        {"status": "closed", "resolution": "parked"},
    ),
    "set_idea_owner": (f"/api/v1/ideas/{IDEA}/owner", {"user_id": None}),
    "volunteer_as_owner": (f"/api/v1/ideas/{IDEA}/volunteer", None),
    "add_evaluators": (
        f"/api/v1/ideas/{IDEA}/evaluators",
        {"user_ids": [USER], "due_at": "2026-10-07T17:00:00Z"},
    ),
    "remove_evaluator": (f"/api/v1/ideas/{IDEA}/evaluators/{USER}", None),
    "set_evaluation_due_date": (f"/api/v1/ideas/{IDEA}/evaluation/due-date", {"due_at": None}),
    "close_evaluation": (f"/api/v1/ideas/{IDEA}/evaluation/close", None),
    "reopen_evaluation": (f"/api/v1/ideas/{IDEA}/evaluation/reopen", None),
    "list_evaluations": (f"/api/v1/ideas/{IDEA}/evaluations", None),
    "get_my_evaluation": (f"/api/v1/ideas/{IDEA}/evaluations/me", None),
    "save_my_evaluation": (
        f"/api/v1/ideas/{IDEA}/evaluations/me",
        {
            "scores": [{"criterion_id": CRITERION, "score": 4, "comment": "Clear demand."}],
            "recommendation": "go",
            "submit": False,
        },
    ),
    "vote_idea": ("/api/v1/ideas/CUST-12/vote", None),
    "unvote_idea": (f"/api/v1/ideas/{IDEA}/vote", None),
    "watch_idea": (f"/api/v1/ideas/{IDEA}/watch", None),
    "unwatch_idea": (f"/api/v1/ideas/{IDEA}/watch", None),
    "list_idea_activity": ("/api/v1/ideas/CUST-12/activity?limit=20", None),
    "create_comment": (f"/api/v1/ideas/{IDEA}/comments", {"body_md": "Love it."}),
    "update_comment": (f"/api/v1/comments/{COMMENT}", {"body_md": "Love it!"}),
    "delete_comment": (f"/api/v1/comments/{COMMENT}", None),
    "get_my_work": ("/api/v1/me/work", None),
    "list_my_owned_ideas": ("/api/v1/me/owned-ideas?status=closed&limit=50", None),
    "global_search": ("/api/v1/search?q=CUST-12&limit=5", None),
}

_METHODS = {operation_id: method for method, _, operation_id in CONTRACT}


def _feature_routes() -> list[APIRoute]:
    return [
        route
        for module in (activity, auth, evaluations, ideas, projects, search, users, work)
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
    # Without the override the (unimplemented) session lookup itself answers.
    response = await client.get("/api/v1/me/work")

    assert response.status_code == 501
    assert response.json()["detail"] == "Sessions are not implemented yet."


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
    public = {"list_dev_users", "dev_login", "logout"}
    for route in _feature_routes():
        calls = {dependency.call for dependency in route.dependant.dependencies}
        assert (get_principal in calls) == (route.name not in public), route.name


@pytest.mark.usefixtures("signed_in")
@pytest.mark.parametrize("ref", ["CUST12", "cust-0", "12", "not a key", "0b7c7d1e-7a55"])
async def test_malformed_idea_reference_is_rejected(client: httpx.AsyncClient, ref: str) -> None:
    response = await client.get(f"/api/v1/ideas/{ref}")

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
