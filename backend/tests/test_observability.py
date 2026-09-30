from __future__ import annotations

import json
import logging
import re
import sys
import uuid

import httpx
import pytest
from fastapi import APIRouter, FastAPI

from app.observability import JsonFormatter, RequestIdFilter, logging_config, request_id_var


@pytest.fixture
def nested_route(app: FastAPI) -> str:
    """A route from a router nested under a parametrised prefix; returns its template."""
    ideas = APIRouter(prefix="/ideas")

    @ideas.get("/{idea_id}")
    async def get_test_idea(project_id: str, idea_id: str) -> dict[str, str]:
        return {"project_id": project_id, "idea_id": idea_id}

    projects = APIRouter(prefix="/api/v1/test-projects/{project_id}")
    projects.include_router(ideas)
    app.include_router(projects)
    return "/api/v1/test-projects/{project_id}/ideas/{idea_id}"


async def test_request_id_is_generated(client: httpx.AsyncClient) -> None:
    response = await client.get("/healthz")

    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["x-request-id"])


async def test_well_formed_incoming_request_id_is_reused(client: httpx.AsyncClient) -> None:
    response = await client.get("/healthz", headers={"X-Request-ID": "ingress-abc.123"})

    assert response.headers["x-request-id"] == "ingress-abc.123"


@pytest.mark.parametrize("incoming", [b"has space", b"x" * 129, "evilé".encode("latin-1"), b""])
async def test_malformed_incoming_request_id_is_replaced(
    client: httpx.AsyncClient, incoming: bytes
) -> None:
    response = await client.get("/healthz", headers={b"X-Request-ID": incoming})

    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["x-request-id"])


async def test_metrics_use_route_templates_not_raw_paths(
    client: httpx.AsyncClient, nested_route: str
) -> None:
    project_id, idea_id = uuid.uuid4().hex, uuid.uuid4().hex
    assert (
        await client.get(f"/api/v1/test-projects/{project_id}/ideas/{idea_id}")
    ).status_code == 200
    await client.get(f"/api/v1/nothing-here/{idea_id}")

    response = await client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    body = response.text
    assert (
        f'soundings_http_requests_total{{method="GET",route="{nested_route}",status="200"}}' in body
    )
    assert 'route="unmatched",status="404"' in body
    assert "soundings_http_request_duration_seconds_bucket" in body
    assert project_id not in body
    assert idea_id not in body


async def test_access_log_has_route_template_and_no_raw_path(
    client: httpx.AsyncClient, nested_route: str, caplog: pytest.LogCaptureFixture
) -> None:
    secret_id = uuid.uuid4().hex
    with caplog.at_level(logging.INFO, logger="soundings.request"):
        response = await client.get(
            f"/api/v1/test-projects/p1/ideas/{secret_id}?email=someone@example.com",
            headers={"Cookie": "session=abc", "Authorization": "Bearer tok"},
        )

    [record] = [r for r in caplog.records if r.name == "soundings.request"]
    assert record.route == nested_route  # type: ignore[attr-defined]
    assert record.status == 200  # type: ignore[attr-defined]
    assert record.method == "GET"  # type: ignore[attr-defined]
    assert record.request_id == response.headers["x-request-id"]  # type: ignore[attr-defined]
    rendered = json.dumps(record.__dict__, default=str)
    for leaked in (secret_id, "someone@example.com", "session=abc", "Bearer tok"):
        assert leaked not in rendered


async def test_security_headers(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/does-not-exist")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert "strict-transport-security" not in response.headers


async def test_hsts_only_over_https(app: FastAPI) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as https:
        response = await https.get("/healthz")

    assert response.headers["strict-transport-security"] == "max-age=31536000"


def test_json_log_format() -> None:
    formatter_config = dict(logging_config("INFO")["formatters"]["json"])
    formatter = formatter_config.pop("()")(**formatter_config)
    record = logging.LogRecord("soundings.test", logging.INFO, __file__, 1, "hello", None, None)
    record.color_message = "\x1b[1mhello\x1b[0m"
    token = request_id_var.set("req-1")
    try:
        RequestIdFilter().filter(record)
    finally:
        request_id_var.reset(token)

    payload = json.loads(formatter.format(record))

    assert payload["level"] == "INFO"
    assert payload["logger"] == "soundings.test"
    assert payload["message"] == "hello"
    assert payload["request_id"] == "req-1"
    assert "timestamp" in payload
    assert "color_message" not in payload


EMAIL = "@".join(["bob", "example.com"])  # built at runtime: absent from source lines


def _raise_chained() -> None:
    try:
        raise KeyError(EMAIL)
    except KeyError as exc:
        raise RuntimeError(f"duplicate key (email)=({EMAIL})") from exc


def test_production_tracebacks_have_no_exception_messages() -> None:
    formatter = JsonFormatter("%(message)s", redact_exception_messages=True)
    try:
        _raise_chained()
    except RuntimeError:
        record = logging.LogRecord(
            "t", logging.ERROR, __file__, 1, "unhandled error", None, sys.exc_info()
        )

    payload = json.loads(formatter.format(record))

    assert EMAIL not in json.dumps(payload)
    assert "builtins.KeyError: <message redacted>" in payload["exc_info"]
    assert "builtins.RuntimeError: <message redacted>" in payload["exc_info"]
    assert "_raise_chained" in payload["exc_info"]


def test_development_tracebacks_keep_exception_messages() -> None:
    formatter = JsonFormatter("%(message)s")
    try:
        _raise_chained()
    except RuntimeError:
        record = logging.LogRecord("t", logging.ERROR, __file__, 1, "boom", None, sys.exc_info())

    assert EMAIL in json.loads(formatter.format(record))["exc_info"]
