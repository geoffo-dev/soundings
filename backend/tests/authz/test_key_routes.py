"""What a key may reach, route by route (role matrix section 5; contract-phase5 sections 2
and 3.3; :mod:`app.authz.keys`).

Every API operation is classified (deny by default for anything unclassified), the
classification follows the rules each route runs (``tests/authz/test_route_rules.py``),
and over HTTP: session-only routes refuse a key with all four scopes, routes without a
rule of their own need ``read``, and public routes never read a key.
"""

from __future__ import annotations

import re
from uuid import uuid4

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import (
    ROUTE_KEY_ACCESS,
    KeyAccess,
    Rule,
    check_route_for_key,
    require_key_scope,
    require_session,
)
from app.authz.rules import SESSION_ONLY_RULES
from app.domain.principal import Principal
from app.errors import ProblemError
from app.models.user import User
from tests.api_keys.helpers import ALL_SCOPES, World, key_client, make_key, problem
from tests.authz.test_route_rules import PUBLIC, ROUTE_RULES, SIGNED_IN
from tests.factories import make_idea
from tests.test_contract_routes import CONTRACT, PUBLIC_OPERATIONS

# Session only although one of their rules has a scope: the inbox and the bell are a
# person's reading state; the moderation queue and a submission's details are
# moderation (contract-phase5 section 2, role matrix section 5); creating a key checks
# project.view only for its restriction.
SESSION_BY_DECISION = frozenset(
    {
        "create_my_api_key",
        "list_notifications",
        "get_notification_summary",
        "mark_notification_read",
        "mark_all_notifications_read",
        "list_moderation_queue",
        "get_idea_submission",
    }
)


def _expected_access(operation_id: str) -> KeyAccess:
    rules = ROUTE_RULES[operation_id]
    named = [rule for rule in rules if rule not in (SIGNED_IN, PUBLIC)]
    if operation_id in PUBLIC_OPERATIONS:
        return KeyAccess.PUBLIC
    if operation_id in SESSION_BY_DECISION:
        return KeyAccess.SESSION
    if named and all(Rule(rule) in SESSION_ONLY_RULES for rule in named):
        return KeyAccess.SESSION
    if SIGNED_IN in rules:
        return KeyAccess.READ
    return KeyAccess.POLICY


def test_every_operation_is_classified() -> None:
    assert set(ROUTE_KEY_ACCESS) == {operation_id for _, _, operation_id in CONTRACT}


@pytest.mark.parametrize("operation_id", sorted(ROUTE_KEY_ACCESS))
def test_the_classification_follows_the_routes_rules(operation_id: str) -> None:
    assert ROUTE_KEY_ACCESS[operation_id] is _expected_access(operation_id)


def test_routes_without_a_rule_need_read() -> None:
    reads = {op for op, access in ROUTE_KEY_ACCESS.items() if access is KeyAccess.READ}

    assert reads == {"get_me", "get_my_work", "list_my_owned_ideas", "global_search"}


# --- The helpers --------------------------------------------------------------------------------
def _principal(auth: str = "session", scopes: tuple[str, ...] | None = None) -> Principal:
    user = User(id=uuid4(), email="me@example.com", display_name="Me")
    return Principal(
        user=user,
        auth=auth,  # type: ignore[arg-type]
        scopes=None if scopes is None else frozenset(scopes),  # type: ignore[arg-type]
    )


def _refused(call: object) -> None:
    assert callable(call)
    with pytest.raises(ProblemError) as raised:
        call()
    assert (raised.value.status, raised.value.code) == (403, "insufficient_scope")


def test_the_gate_lets_sessions_through_and_denies_keys_by_default() -> None:
    session = _principal()
    key = _principal("api_key", ALL_SCOPES)
    mcp_only = _principal("api_key", ("mcp",))

    for operation_id in [*ROUTE_KEY_ACCESS, None, "made_up"]:
        check_route_for_key(session, operation_id)
    _refused(lambda: check_route_for_key(key, None))
    _refused(lambda: check_route_for_key(key, "made_up"))
    _refused(lambda: check_route_for_key(key, "list_my_api_keys"))
    _refused(lambda: check_route_for_key(key, "get_branding"))  # public: never a key
    _refused(lambda: check_route_for_key(mcp_only, "get_me"))
    check_route_for_key(key, "get_me")
    check_route_for_key(mcp_only, "get_idea")  # the policy decides there


def test_require_session_and_require_key_scope() -> None:
    session = _principal()
    read = _principal("api_key", ("read",))

    require_session(session)
    require_key_scope(session, "write")
    require_key_scope(read, "read")
    _refused(lambda: require_session(read))
    _refused(lambda: require_key_scope(read, "write"))


# --- Over HTTP ------------------------------------------------------------------------------------
def _path(template: str) -> str:
    """Any value for each path parameter: the gate refuses before the route reads them."""
    values = {"idea": "CUST-1", "slug": "customer-innovation", "section_key": "risks"}
    return re.sub(r"\{(\w+)\}", lambda m: values.get(m.group(1), str(uuid4())), template)


SESSION_OPERATIONS = sorted(
    (method, path, op) for method, path, op in CONTRACT if ROUTE_KEY_ACCESS[op] is KeyAccess.SESSION
)
READ_OPERATIONS = sorted(
    (method, path, op) for method, path, op in CONTRACT if ROUTE_KEY_ACCESS[op] is KeyAccess.READ
)
PUBLIC_ROUTES = sorted(
    (method, path, op) for method, path, op in CONTRACT if ROUTE_KEY_ACCESS[op] is KeyAccess.PUBLIC
)


@pytest.fixture
async def full_key(world: World, db_session: AsyncSession) -> str:
    """A platform admin's key with every scope: the most a key can be."""
    return await make_key(db_session, world.platform, scopes=ALL_SCOPES)


async def test_session_only_routes_refuse_a_key_with_every_scope(
    app: FastAPI, full_key: str
) -> None:
    async with key_client(app, full_key) as http:
        for method, path, operation_id in SESSION_OPERATIONS:
            app.state.throttles = {}  # not the key's write cap: the gate is under test
            response = await http.request(method, _path(path), json={})
            assert response.status_code == 403, (operation_id, response.text)
            assert response.json()["code"] == "insufficient_scope", operation_id


async def test_routes_without_a_rule_need_the_read_scope(
    app: FastAPI, world: World, db_session: AsyncSession
) -> None:
    mcp_only = await make_key(db_session, world.carol, scopes=["mcp"], name="MCP only")
    read = await make_key(db_session, world.carol, scopes=["read"], name="Read")

    async with key_client(app, mcp_only) as without, key_client(app, read) as with_read:
        for method, path, operation_id in READ_OPERATIONS:
            params = {"q": "refund"} if operation_id == "global_search" else None
            problem(await without.request(method, path, params=params), 403, "insufficient_scope")
            response = await with_read.request(method, path, params=params)
            assert response.status_code == 200, (operation_id, response.text)


async def test_public_routes_never_read_a_key(app: FastAPI, world: World) -> None:
    """A garbage bearer token on a public route is ignored, not refused (the public
    routes don't authenticate at all)."""
    async with key_client(app, "nonsense") as http:
        for method, path, operation_id in PUBLIC_ROUTES:
            response = await http.request(method, _path(path), json={})
            assert "www-authenticate" not in response.headers, operation_id
            if response.status_code == 401:
                assert response.json()["code"] != "unauthorized", operation_id


async def test_rule_routes_refuse_a_key_without_the_rules_scope(
    app: FastAPI, world: World, db_session: AsyncSession
) -> None:
    """A key with only ``mcp`` reads nothing through REST: rules answer
    ``insufficient_scope`` and lists match nothing."""
    idea = await make_idea(db_session, world.cust, submitted_by=world.carol)
    key = await make_key(db_session, world.platform, scopes=["mcp"])
    slug, ref = world.cust.slug, f"CUST-{idea.number}"

    async with key_client(app, key) as http:
        listed = await http.get("/api/v1/projects")
        refused = [
            await http.get(f"/api/v1/projects/{slug}"),
            await http.get(f"/api/v1/projects/{slug}/ideas"),
            await http.get(f"/api/v1/projects/{slug}/board"),
            await http.get(f"/api/v1/projects/{slug}/members"),
            await http.get(f"/api/v1/ideas/{ref}"),
            await http.get(f"/api/v1/ideas/{ref}/evaluations"),
            await http.get(f"/api/v1/ideas/{ref}/activity"),
            await http.get("/api/v1/users", params={"q": "carol"}),
            await http.post(f"/api/v1/ideas/{ref}/comments", json={"body_md": "Hi"}),
        ]

    assert listed.status_code == 200
    assert listed.json() == []
    for response in refused:
        problem(response, 403, "insufficient_scope")


def test_operation_ids_reach_the_gate(app: FastAPI) -> None:
    """The gate keys on ``route.operation_id``: every API route sets one explicitly."""
    from fastapi.routing import APIRoute

    missing = [
        route.path
        for route in app.routes
        if isinstance(route, APIRoute)
        and route.path.startswith("/api/v1/")
        and route.operation_id not in ROUTE_KEY_ACCESS
    ]

    assert missing == []


@pytest.mark.parametrize("header", ["Bearer", "Bearer ", "bearer x"])
async def test_an_empty_or_short_bearer_is_refused_not_ignored(
    app: FastAPI, world: World, header: str
) -> None:
    async with key_client(app) as http:
        response = await http.get("/api/v1/auth/me", headers={"Authorization": header})

    problem(response, 401, "unauthorized")
    assert response.headers["www-authenticate"] == 'Bearer realm="soundings"'


async def test_a_key_on_a_session_route_is_refused_before_its_body_is_read(
    app: FastAPI, full_key: str
) -> None:
    """The gate answers before the route's own checks: a session-only route refuses a
    key with 403 even for a malformed body or an unknown resource (it reveals
    nothing: the answer doesn't depend on the resource)."""
    async with key_client(app, full_key) as http:
        malformed = await http.post("/api/v1/me/api-keys", json={"scopes": "nope"})
        unknown = await http.delete(f"/api/v1/ideas/NOPE-{uuid4().int % 1000}")

    problem(malformed, 403, "insufficient_scope")
    problem(unknown, 403, "insufficient_scope")
