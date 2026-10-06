"""Phase 6 settings: AI assistance through kagent (contract-phase6 section 3.2; the
chart's names). The controller URL is the only host Soundings ever calls for AI, so it
is validated strictly."""

from __future__ import annotations

from datetime import timedelta
from typing import get_args

import pytest
from pydantic import ValidationError

from app.config import (
    AI_RUN_TIMEOUT_MAX,
    AI_RUN_TIMEOUT_MIN,
    KAGENT_DEFAULT_URL,
    AiProtocolName,
    Settings,
)
from app.models.ai import KUBERNETES_LABEL_PATTERN
from app.models.enums import AiAgentProtocol
from tests.conftest import make_settings


def test_defaults() -> None:
    settings = make_settings()

    assert settings.ai_enabled is False
    assert settings.kagent_url == KAGENT_DEFAULT_URL == "http://kagent-controller.kagent:8083"
    assert settings.kagent_token is None
    assert settings.ai_default_protocol == "kagent_v0_10"
    assert settings.ai_run_timeout == timedelta(minutes=5)
    assert settings.ai_run_timeout_seconds == 300
    assert settings.ai_max_concurrent_runs == 4
    # L8: kagent's own agents (in its namespace, kagent) aren't registrable by default.
    assert settings.ai_agent_namespaces == ["soundings"]
    assert settings.ai_mcp_url is None
    assert settings.ai_mcp_url_effective == settings.public_base_url + "/mcp"


def test_chart_environment_names_are_read(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in {
        "SOUNDINGS_AI_ENABLED": "true",
        "SOUNDINGS_KAGENT_URL": "http://kagent-controller.kagent.svc.cluster.local:8083",
        "SOUNDINGS_KAGENT_TOKEN": "eyJhbGciOiJub25lIn0.e30.",
        "SOUNDINGS_AI_DEFAULT_PROTOCOL": "kagent_v1_0",
        "SOUNDINGS_AI_RUN_TIMEOUT": "PT10M",
        "SOUNDINGS_AI_MAX_CONCURRENT_RUNS": "2",
        "SOUNDINGS_AI_AGENT_NAMESPACES": "soundings, kagent",
        "SOUNDINGS_AI_MCP_URL": "http://soundings.soundings.svc.cluster.local:8000/mcp",
    }.items():
        monkeypatch.setenv(name, value)

    settings = Settings()

    assert settings.ai_enabled is True
    assert settings.kagent_url == "http://kagent-controller.kagent.svc.cluster.local:8083"
    assert settings.kagent_token is not None
    assert settings.ai_default_protocol == "kagent_v1_0"
    assert settings.ai_run_timeout_seconds == 600
    assert settings.ai_max_concurrent_runs == 2
    assert settings.ai_agent_namespaces == ["kagent", "soundings"]
    assert settings.ai_mcp_url_effective.endswith(".svc.cluster.local:8000/mcp")


def test_the_protocol_names_are_the_enums() -> None:
    assert set(get_args(AiProtocolName)) == {protocol.value for protocol in AiAgentProtocol}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("http://kagent-controller.kagent:8083", "http://kagent-controller.kagent:8083"),
        ("HTTP://Kagent-Controller.Kagent:8083/", "http://kagent-controller.kagent:8083"),
        (" https://kagent.example.com ", "https://kagent.example.com"),
    ],
)
def test_the_controller_url_is_normalised(raw: str, expected: str) -> None:
    assert make_settings(kagent_url=raw).kagent_url == expected


@pytest.mark.parametrize(
    "raw",
    [
        "kagent-controller.kagent:8083",  # no scheme
        "ftp://kagent:8083",
        "http://",
        "http://user:secret@kagent:8083",  # credentials belong in kagent_token
        "http://kagent:8083/api/a2a",  # the path is the protocol's, never configured
        "http://kagent:8083?x=1",
        "http://kagent:8083#x",
        "http://kagent:8083/\r\nX-Injected: 1",
    ],
)
def test_a_controller_url_with_more_than_an_origin_is_refused(raw: str) -> None:
    with pytest.raises(ValidationError):
        make_settings(kagent_url=raw)


def test_the_token_is_secret_and_one_word() -> None:
    settings = make_settings(kagent_token="abc.def.ghi")

    assert "abc.def.ghi" not in repr(settings)
    assert make_settings(kagent_token="  ").kagent_token is None
    for bad in ("two words", "line\nbreak", "tab\there"):
        with pytest.raises(ValidationError):
            make_settings(kagent_token=bad)


def test_the_run_timeout_is_bounded() -> None:
    assert make_settings(ai_run_timeout=AI_RUN_TIMEOUT_MIN).ai_run_timeout_seconds == 30
    assert make_settings(ai_run_timeout=AI_RUN_TIMEOUT_MAX).ai_run_timeout_seconds == 3600
    assert make_settings(ai_run_timeout=90).ai_run_timeout_seconds == 90
    for bad in (timedelta(seconds=29), timedelta(hours=1, seconds=1), "PT2H"):
        with pytest.raises(ValidationError):
            make_settings(ai_run_timeout=bad)


def test_concurrency_is_bounded() -> None:
    for bad in (0, 51):
        with pytest.raises(ValidationError):
            make_settings(ai_max_concurrent_runs=bad)


def test_agent_namespaces_are_kubernetes_names() -> None:
    assert make_settings(ai_agent_namespaces="b,a,a").ai_agent_namespaces == ["a", "b"]
    assert make_settings(ai_agent_namespaces='["kagent"]').ai_agent_namespaces == ["kagent"]
    for bad in ("", " , ", "Soundings", "a.b", "a/b", "x" * 64, "-a"):  # none: no "any"
        with pytest.raises(ValidationError):
            make_settings(ai_agent_namespaces=bad)
    assert KUBERNETES_LABEL_PATTERN == r"^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$"


def test_the_mcp_url_hint() -> None:
    assert make_settings(ai_mcp_url="").ai_mcp_url is None
    hint = "http://soundings.soundings.svc.cluster.local:8000/mcp"
    assert make_settings(ai_mcp_url=hint).ai_mcp_url_effective == hint
    for bad in ("soundings/mcp", "http://u:p@host/mcp", "http://host/mcp?key=x", "ftp://h/mcp"):
        with pytest.raises(ValidationError):
            make_settings(ai_mcp_url=bad)
