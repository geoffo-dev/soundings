"""Phase 0 follow-ups at the HTTP edge: trusted hosts and where /metrics is served."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr, ValidationError

from app.config import Settings
from app.main import create_app
from app.middleware import host_name
from tests.conftest import make_settings

STRONG_SECRET = SecretStr("s" * 40)


async def _get(app: FastAPI, url: str, host: str | None = None) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    headers = {"Host": host} if host else {}
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        return await http.get(url, headers=headers)


@pytest.fixture
async def production_app(settings: Settings) -> AsyncIterator[FastAPI]:
    values: dict[str, Any] = settings.model_dump() | {
        "environment": "production",
        "secret_key": STRONG_SECRET,
        "dev_login_enabled": False,
        "base_urls": ["https://ideas.example.com", "https://ideas.example.org:8443"],
        "metrics_port": 0,
    }
    application = create_app(make_settings(**values))
    async with application.router.lifespan_context(application):
        yield application


@pytest.mark.parametrize(
    ("host", "status"),
    [
        ("ideas.example.com", 200),
        ("IDEAS.EXAMPLE.COM:443", 200),
        ("ideas.example.org", 200),  # port ignored
        ("evil.example.net", 400),
        ("localhost:8000", 400),  # production: configured hosts only
        ("127.0.0.1", 400),
        ("ideas.example.com.evil.net", 400),
    ],
)
async def test_trusted_hosts_in_production(production_app: FastAPI, host: str, status: int) -> None:
    response = await _get(production_app, "/api/v1/openapi.json", host)

    assert response.status_code == status
    if status == 400:
        assert response.headers["content-type"] == "application/problem+json"
        assert response.json()["code"] == "invalid_host"
        assert response.headers["x-request-id"]  # still logged and traced


@pytest.mark.parametrize("path", ["/healthz", "/readyz"])
async def test_probes_work_on_any_host(production_app: FastAPI, path: str) -> None:
    response = await _get(production_app, path, "10.42.0.17:8000")

    assert response.status_code == 200


async def test_metrics_are_not_on_the_app_port_in_production(production_app: FastAPI) -> None:
    response = await _get(production_app, "/metrics", "ideas.example.com")

    assert response.status_code == 404


@pytest.mark.parametrize("host", ["localhost:5173", "127.0.0.1:8000", "[::1]:8000", "testserver"])
async def test_localhost_is_trusted_outside_production(app: FastAPI, host: str) -> None:
    assert (await _get(app, "/api/v1/openapi.json", host)).status_code == 200


async def test_unknown_hosts_are_refused_outside_production_too(app: FastAPI) -> None:
    assert (await _get(app, "/api/v1/openapi.json", "evil.example.net")).status_code == 400


async def test_metrics_on_the_app_port_when_the_metrics_port_is_0(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/metrics")

    assert response.status_code == 200
    assert "soundings_http_requests_total" in response.text


@pytest.mark.settings(metrics_port=9090)
async def test_metrics_leave_the_app_port_when_a_metrics_port_is_set(
    client: httpx.AsyncClient,
) -> None:
    assert (await client.get("/metrics")).status_code == 404


@pytest.mark.parametrize(
    ("header", "name"),
    [
        ("Example.COM", "example.com"),
        ("example.com:8443", "example.com"),
        ("example.com.", "example.com"),
        ("[::1]:8000", "::1"),
        ("[::1]", "::1"),
        ("", ""),
        ("[broken", ""),
    ],
)
def test_host_name(header: str, name: str) -> None:
    assert host_name(header) == name


# --- Settings -------------------------------------------------------------------------------
def test_trusted_hosts_setting() -> None:
    development = make_settings(base_urls=["https://a.example.com:8443"])
    production = make_settings(
        environment="production", secret_key=STRONG_SECRET, base_urls=["https://a.example.com"]
    )

    assert development.trusted_hosts == {"a.example.com", "localhost", "127.0.0.1", "::1"}
    assert production.trusted_hosts == {"a.example.com"}


def test_metrics_on_the_app_port_only_outside_production() -> None:
    assert make_settings(metrics_port=0).metrics_on_app_port
    assert not make_settings(metrics_port=9090).metrics_on_app_port
    assert not make_settings(
        environment="production", secret_key=STRONG_SECRET, metrics_port=0
    ).metrics_on_app_port


def test_session_lifetimes() -> None:
    settings = make_settings(session_idle_timeout="PT30M", session_max_age=3600)

    assert settings.session_idle_timeout == timedelta(minutes=30)
    assert settings.session_max_age == timedelta(hours=1)
    with pytest.raises(ValidationError, match="session_max_age"):
        make_settings(session_idle_timeout=7200, session_max_age=3600)
    with pytest.raises(ValidationError):
        make_settings(session_idle_timeout=0)


def test_production_refuses_insecure_cookies() -> None:
    with pytest.raises(ValidationError, match="COOKIE_SECURE"):
        make_settings(environment="production", secret_key=STRONG_SECRET, cookie_secure=False)

    assert make_settings(environment="production", secret_key=STRONG_SECRET, cookie_secure=True)
