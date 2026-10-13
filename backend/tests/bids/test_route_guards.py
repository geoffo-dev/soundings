"""Every bid route (contract-phase10 section 2): 401 without a session, 403 ``csrf_failed``
for writes without the CSRF header, and a malformed body's 422 before a hidden idea's 404
(FastAPI validates bodies first; contract section 2.1, step 7)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.models.user import User
from tests.bids.conftest import Crew, assert_problem
from tests.conftest import Login
from tests.test_contract_routes import _METHODS, PHASE10_OPERATIONS, PHASE10_REQUESTS, STUBS

REQUESTS: dict[str, tuple[str, dict[str, Any] | None]] = {**PHASE10_REQUESTS, **STUBS}
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def test_every_bid_operation_has_a_request() -> None:
    assert set(REQUESTS) == PHASE10_OPERATIONS


@pytest.mark.parametrize("operation_id", sorted(PHASE10_OPERATIONS))
async def test_needs_a_session(client: httpx.AsyncClient, operation_id: str) -> None:
    url, body = REQUESTS[operation_id]

    response = await client.request(_METHODS[operation_id], url, json=body)

    assert_problem(response, 401, "unauthorized")


@pytest.mark.parametrize(
    "operation_id", sorted(op for op in PHASE10_OPERATIONS if _METHODS[op] in UNSAFE)
)
async def test_writes_need_the_csrf_header(login: Login, crew: Crew, operation_id: str) -> None:
    url, body = REQUESTS[operation_id]
    http = await login(crew.owner)
    del http.headers["X-CSRF-Token"]

    response = await http.request(_METHODS[operation_id], url, json=body)

    assert_problem(response, 403, "csrf_failed")


async def test_shape_errors_come_before_not_found(login: Login, crew: Crew) -> None:
    outsider: User = crew.outsider
    http = await login(outsider)  # can't see the idea
    url = f"/api/v1/ideas/{crew.key}/bid-call"

    body_error = await http.post(url, json={"title": ""})
    hidden = await http.post(url, json={"title": "A call"})

    assert_problem(body_error, 422, "validation_error")
    assert_problem(hidden, 404, "not_found")
