"""A key's request holds at most one database connection at a time (security review H1).

Checking a key and moving its ``last_used_at`` run in one short transaction of their
own, committed and closed before the request's own unit of work starts (REST) or
before the SDK reads the body (``/mcp``). Before the fix each request whose
``last_used_at`` was due held the request's connection while waiting for a second
one: with the pool exhausted, every request in the process stalled for the pool
timeout and then failed.

The app here has a pool of one connection plus one overflow, so a request that needs
two at once deadlocks against a second such request; the calls must finish well
inside the pool's 30-second timeout.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Iterable

import httpx2
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from tests.api_keys.helpers import API, World, key_client, key_row, make_key
from tests.mcp.conftest import headers, rpc

pytestmark = pytest.mark.settings(database_pool_size=1)

PARALLEL = 6
LIMIT = 15.0
"""Seconds: a stall on the pool (30 s) fails here, long before the pool times out."""


async def _all[T](calls: Iterable[Awaitable[T]]) -> list[T]:
    return await asyncio.wait_for(asyncio.gather(*calls), LIMIT)


async def test_first_uses_of_many_keys_in_parallel(
    app: FastAPI, world: World, db_session: AsyncSession
) -> None:
    keys = [
        await make_key(db_session, world.carol, scopes=["read"], name=f"Key {n}")
        for n in range(PARALLEL)
    ]
    clients = [key_client(app, key) for key in keys]
    try:
        responses = await _all(http.get(f"{API}/auth/me") for http in clients)
    finally:
        for http in clients:
            await http.aclose()

    assert [response.status_code for response in responses] == [200] * PARALLEL
    for key in keys:  # the throttled update still happened, once per key
        assert (await key_row(db_session, key)).last_used_at is not None


async def test_one_key_in_parallel_on_reads_and_writes(
    app: FastAPI, world: World, db_session: AsyncSession
) -> None:
    key = await make_key(db_session, world.carol, scopes=["read", "write"])

    async with key_client(app, key) as http:
        responses = await _all(
            [
                *(http.get(f"{API}/projects") for _ in range(PARALLEL)),
                *(
                    http.post(
                        f"{API}/projects/{world.cust.slug}/ideas",
                        json={"title": f"Parallel idea {n}", "summary": "Made in parallel."},
                    )
                    for n in range(PARALLEL)
                ),
            ]
        )

    statuses = [response.status_code for response in responses]
    assert statuses == [200] * PARALLEL + [201] * PARALLEL, [r.text[:200] for r in responses]
    assert (await key_row(db_session, key)).last_used_at is not None


async def test_mcp_calls_in_parallel(app: FastAPI, world: World, db_session: AsyncSession) -> None:
    key = await make_key(db_session, world.carol)
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as http:
        responses = await _all(
            http.post(
                "/mcp",
                json=rpc("tools/call", {"name": "list_projects", "arguments": {}}, id=n),
                headers=headers(key),
            )
            for n in range(PARALLEL)
        )

    assert [response.status_code for response in responses] == [200] * PARALLEL
    for response in responses:
        assert response.json()["result"]["isError"] is False
    assert (await key_row(db_session, key)).last_used_at is not None


async def test_a_failing_key_holds_no_connection_of_the_request(
    app: FastAPI, world: World, db_session: AsyncSession
) -> None:
    """Refusals (a mismatched secret here) go through the same short transaction."""
    key = await make_key(db_session, world.carol, scopes=["read"])
    wrong = key[:-4] + ("aaaa" if not key.endswith("aaaa") else "bbbb")

    async with key_client(app, wrong) as http:
        responses = await _all(http.get(f"{API}/auth/me") for _ in range(PARALLEL))

    assert {response.status_code for response in responses} == {401}
