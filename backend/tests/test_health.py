from __future__ import annotations

import gc

import httpx
import pytest


async def test_healthz_is_ok(client: httpx.AsyncClient) -> None:
    response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_startup_freezes_the_heap(client: httpx.AsyncClient) -> None:
    # app.main.freeze_startup_heap: the first full collection of everything imported
    # at startup must not land on a request.
    assert (await client.get("/healthz")).status_code == 200
    assert gc.get_freeze_count() > 0


async def test_readyz_checks_the_database(client: httpx.AsyncClient) -> None:
    response = await client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.settings(database_url="postgresql+psycopg://nobody:nothing@127.0.0.1:1/none")
async def test_readyz_reports_unreachable_database_as_problem(client: httpx.AsyncClient) -> None:
    response = await client.get("/readyz")

    assert response.status_code == 503
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["code"] == "not_ready"
    assert "nobody" not in response.text  # no connection details leak


async def test_probes_are_not_in_the_openapi_document(client: httpx.AsyncClient) -> None:
    paths = (await client.get("/api/v1/openapi.json")).json()["paths"]

    assert not {"/healthz", "/readyz", "/metrics"} & set(paths)
