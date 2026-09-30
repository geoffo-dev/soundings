from __future__ import annotations

import httpx
import pytest


async def test_healthz_is_ok(client: httpx.AsyncClient) -> None:
    response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


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
