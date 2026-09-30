from __future__ import annotations

from typing import Any

import pytest
import uvicorn
from sqlalchemy.engine import URL

from app import cli
from app.config import Settings
from tests.conftest import make_settings


@pytest.fixture
def cli_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    settings = make_settings(
        host="0.0.0.0",  # noqa: S104 - what the container sets
        trusted_proxies=["10.0.0.0/8", "127.0.0.1"],
        database_url="postgresql://u:p@db/soundings",
    )
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    return settings


def test_api_runs_uvicorn_behind_trusted_proxies(
    cli_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: calls.append({"app": app, **kwargs}))

    assert cli.main(["api", "--port", "8001"]) == 0

    [call] = calls
    assert call["app"] == "app.main:app"
    assert call["host"] == "0.0.0.0"  # noqa: S104
    assert call["port"] == 8001
    assert call["workers"] == 1
    assert call["proxy_headers"] is True
    assert call["forwarded_allow_ips"] == "10.0.0.0/8,127.0.0.1"
    assert call["access_log"] is False
    assert call["log_config"] is None


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
