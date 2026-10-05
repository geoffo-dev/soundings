"""The key routes' guards (contract-phase5 sections 1 and 2): 401 without a session,
403 ``csrf_failed`` for writes without the CSRF header, and the order of checks (401 →
422 shape → 403 → 404, for people and admins)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx
import pytest

from tests.api_keys.helpers import API, World, problem
from tests.conftest import Login

ROUTES: dict[str, tuple[str, str, Any]] = {
    "list_my_api_keys": ("GET", "/me/api-keys", None),
    "create_my_api_key": ("POST", "/me/api-keys", {"name": "Script", "scopes": ["read"]}),
    "revoke_my_api_key": ("DELETE", f"/me/api-keys/{uuid4()}", None),
    "list_admin_api_keys": ("GET", "/admin/api-keys", None),
    "revoke_admin_api_key": ("DELETE", f"/admin/api-keys/{uuid4()}", None),
}
WRITES = sorted(op for op, (method, _, _) in ROUTES.items() if method != "GET")


def test_every_key_route_is_covered() -> None:
    from tests.test_contract_routes import CONTRACT

    assert {op for _, path, op in CONTRACT if "/api-keys" in path} == set(ROUTES)


@pytest.mark.parametrize("operation_id", sorted(ROUTES))
async def test_needs_a_session(client: httpx.AsyncClient, operation_id: str) -> None:
    method, path, body = ROUTES[operation_id]

    problem(await client.request(method, API + path, json=body), 401, "unauthorized")


@pytest.mark.parametrize("operation_id", WRITES)
async def test_writes_need_the_csrf_header(login: Login, world: World, operation_id: str) -> None:
    method, path, body = ROUTES[operation_id]
    http = await login(world.platform)
    del http.headers["X-CSRF-Token"]

    problem(await http.request(method, API + path, json=body), 403, "csrf_failed")


async def test_shape_errors_come_before_the_admin_check(login: Login, world: World) -> None:
    http = await login(world.carol)  # not a platform admin

    problem(
        await http.get(f"{API}/admin/api-keys", params={"state": "revoked"}),
        422,
        "validation_error",
    )
    problem(await http.delete(f"{API}/admin/api-keys/not-a-uuid"), 422, "validation_error")
    problem(await http.get(f"{API}/admin/api-keys"), 403, "forbidden")
    problem(
        await http.post(f"{API}/me/api-keys", json={"name": "", "scopes": ["read"]}),
        422,
        "validation_error",
    )
