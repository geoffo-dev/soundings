from __future__ import annotations

import os
from typing import Any

import pytest
import uvicorn
from sqlalchemy.engine import URL

from app import cli, config
from app.config import Settings
from tests.conftest import make_settings


@pytest.fixture
def cli_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    settings = make_settings(
        environment="test",
        host="0.0.0.0",  # noqa: S104 - what the container sets
        trusted_proxies=["10.0.0.0/8", "127.0.0.1"],
        database_url="postgresql://u:p@db/soundings",
    )
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "get_database_settings", lambda: settings)
    return settings


@pytest.fixture
def no_metrics_server(monkeypatch: pytest.MonkeyPatch) -> list[Settings]:
    started: list[Settings] = []
    monkeypatch.setattr(cli, "start_metrics_server", started.append)
    return started


def test_api_runs_uvicorn_behind_trusted_proxies(
    cli_settings: Settings, monkeypatch: pytest.MonkeyPatch, no_metrics_server: list[Settings]
) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: calls.append({"app": app, **kwargs}))

    assert cli.main(["api", "--port", "8001"]) == 0

    [call] = calls
    assert call["app"] == "app.main:app"
    assert call["host"] == "0.0.0.0"  # noqa: S104
    assert call["port"] == 8001
    assert call["workers"] == 1
    assert call["proxy_headers"] is False  # app.middleware.ProxyHeadersMiddleware does it
    assert "forwarded_allow_ips" not in call
    assert call["access_log"] is False
    assert call["log_config"] is None
    assert no_metrics_server == [cli_settings]  # the separate /metrics port (9090)


def test_api_with_reload_serves_metrics_on_the_app_port(
    cli_settings: Settings, monkeypatch: pytest.MonkeyPatch, no_metrics_server: list[Settings]
) -> None:
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: None)
    monkeypatch.setenv("SOUNDINGS_METRICS_PORT", "9090")

    assert cli.main(["api", "--reload"]) == 0

    assert no_metrics_server == []
    assert os.environ["SOUNDINGS_METRICS_PORT"] == "0"


def test_metrics_server_serves_prometheus_text(cli_settings: Settings) -> None:
    import socket
    import urllib.request

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    cli.start_metrics_server(make_settings(host="127.0.0.1", metrics_port=port))

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics", timeout=5) as response:
        body = response.read().decode()

    assert "soundings_http_requests_total" in body


def test_migrate_upgrades_the_configured_database(
    cli_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    upgraded: list[URL] = []
    monkeypatch.setattr("app.migrate.upgrade_database", upgraded.append)

    assert cli.main(["migrate"]) == 0

    assert [url.render_as_string(hide_password=False) for url in upgraded] == [
        "postgresql+psycopg://u:p@db/soundings"
    ]


def test_worker_uses_requested_concurrency(
    cli_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[int | None] = []

    async def fake_run_worker(settings: Settings, *, concurrency: int | None = None) -> None:
        seen.append(concurrency)

    monkeypatch.setattr("app.worker.run_worker", fake_run_worker)

    assert cli.main(["worker", "--concurrency", "3"]) == 0
    assert seen == [3]


def test_a_command_is_required(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exited:
        cli.main([])

    assert exited.value.code == 2
    assert "COMMAND" in capsys.readouterr().err


def test_migrate_needs_no_secret_key_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    """A migration Job gets the database settings only, not SOUNDINGS_SECRET_KEY."""
    for name in list(os.environ):
        if name.startswith("SOUNDINGS_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("SOUNDINGS_ENVIRONMENT", "production")
    monkeypatch.setenv("SOUNDINGS_DATABASE_URL", "postgresql://u:p@db/soundings")
    config.get_database_settings.cache_clear()
    monkeypatch.setattr(cli, "get_settings", _no_api_settings)
    upgraded: list[URL] = []
    monkeypatch.setattr("app.migrate.upgrade_database", upgraded.append)
    try:
        assert cli.main(["migrate"]) == 0
    finally:
        config.get_database_settings.cache_clear()

    assert [url.host for url in upgraded] == ["db"]


def _no_api_settings() -> Settings:
    raise AssertionError("migrate must not load the API settings")


def test_wait_for_db_returns_when_the_database_answers(
    cli_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, float]] = []

    def fake_wait(dsn: str, *, timeout: float) -> bool:
        calls.append((dsn, timeout))
        return True

    monkeypatch.setattr("app.migrate.wait_for_database", fake_wait)

    assert cli.main(["wait-for-db", "--timeout", "5"]) == 0
    assert calls == [("postgresql://u:p@db/soundings", 5.0)]


def test_wait_for_db_fails_after_the_timeout(cli_settings: Settings) -> None:
    unreachable = make_settings(database_url="postgresql://nobody:x@127.0.0.1:1/none")

    from app.migrate import wait_for_database

    assert wait_for_database(unreachable.database_dsn, timeout=0.3, interval=0.1) is False


def test_wait_for_db_succeeds_against_the_test_database(database_url: str) -> None:
    from app.migrate import wait_for_database

    assert wait_for_database(make_settings(database_url=database_url).database_dsn, timeout=10)


@pytest.mark.parametrize("command", ["api", "worker"])
def test_serving_commands_refuse_an_implicit_development_mode(
    command: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Security review P7 M1: without SOUNDINGS_ENVIRONMENT the app would run in
    development mode with the public development key (forgeable unsubscribe links and
    ALTCHA challenges). The image sets production; a bare install must say so."""
    started: list[str] = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: started.append(app))
    monkeypatch.setattr(cli, "start_metrics_server", lambda settings: None)
    implicit = make_settings(database_url="postgresql://u:p@db/soundings")
    monkeypatch.setattr(cli, "get_settings", lambda: implicit)

    assert implicit.environment == "development"
    assert implicit.implicit_development_secret
    assert cli.main([command]) == 2
    assert "SOUNDINGS_ENVIRONMENT" in capsys.readouterr().err
    assert started == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"environment": "development"},  # a developer machine says so
        {"secret_key": "x" * 40},  # a real key, environment left at its default
    ],
)
def test_explicit_development_or_a_real_key_starts(
    overrides: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    no_metrics_server: list[Settings],
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: calls.append(app))
    settings = make_settings(database_url="postgresql://u:p@db/soundings", **overrides)
    monkeypatch.setattr(cli, "get_settings", lambda: settings)

    assert not settings.implicit_development_secret
    assert cli.main(["api"]) == 0
    assert calls == ["app.main:app"]
