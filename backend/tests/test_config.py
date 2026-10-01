from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from app.config import Settings
from tests.conftest import make_settings

STRONG_SECRET = "s" * 40


def test_list_settings_accept_csv_and_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "SOUNDINGS_BASE_URLS", "https://ideas.example.com/, https://ideas.example.org"
    )
    monkeypatch.setenv("SOUNDINGS_TRUSTED_PROXIES", '["10.0.0.0/8", "127.0.0.1"]')

    settings = Settings()

    assert settings.base_urls == ["https://ideas.example.com", "https://ideas.example.org"]
    assert settings.trusted_proxies == ["10.0.0.0/8", "127.0.0.1"]
    assert settings.allowed_hosts == ["ideas.example.com", "ideas.example.org"]


@pytest.mark.parametrize(
    "url", ["ftp://example.com", "example.com", "https://example.com/?q=1", "https://"]
)
def test_invalid_base_urls_are_rejected(url: str) -> None:
    with pytest.raises(ValidationError):
        make_settings(base_urls=[url])


def test_base_url_for_host_only_returns_configured_urls() -> None:
    settings = make_settings(base_urls=["https://a.example.com", "https://b.example.com:8443"])

    assert settings.base_url_for_host("b.example.com:8443") == "https://b.example.com:8443"
    assert settings.base_url_for_host("A.EXAMPLE.COM") == "https://a.example.com"
    assert settings.base_url_for_host("evil.example.net") == "https://a.example.com"
    assert settings.base_url_for_host(None) == "https://a.example.com"


@pytest.mark.parametrize(
    "url",
    [
        "postgres://u:p@db:5432/soundings",
        "postgresql://u:p@db:5432/soundings",
        "postgresql+psycopg://u:p@db:5432/soundings",
    ],
)
def test_database_url_is_normalised_to_psycopg(url: str) -> None:
    settings = make_settings(database_url=url)

    assert settings.database_url == "postgresql+psycopg://u:p@db:5432/soundings"
    assert settings.sqlalchemy_url.drivername == "postgresql+psycopg"
    assert settings.database_dsn == "postgresql://u:p@db:5432/soundings"


def test_other_database_drivers_are_rejected() -> None:
    with pytest.raises(ValidationError):
        make_settings(database_url="postgresql+asyncpg://u:p@db/soundings")


def test_database_password_overrides_url_and_is_escaped() -> None:
    settings = make_settings(
        database_url="postgresql://soundings@db/soundings",
        database_password=SecretStr("p@ss:w/rd%"),
    )

    assert settings.database_dsn == "postgresql://soundings:p%40ss%3Aw%2Frd%25@db/soundings"
    assert settings.sqlalchemy_url.password == "p@ss:w/rd%"


def test_secrets_are_not_in_repr() -> None:
    settings = make_settings(
        database_url="postgresql://u:topsecret@db/x", secret_key=SecretStr(STRONG_SECRET)
    )

    assert "topsecret" not in repr(settings)
    assert STRONG_SECRET not in repr(settings)


def test_validation_errors_do_not_echo_secrets() -> None:
    with pytest.raises(ValidationError) as bad_driver:
        make_settings(database_url="postgresql+asyncpg://u:SUPERSECRET@db/x")
    with pytest.raises(ValidationError) as bad_production:
        make_settings(environment="production", database_url="postgresql://u:SUPERSECRET@db/x")

    assert "SUPERSECRET" not in str(bad_driver.value)
    assert "SUPERSECRET" not in str(bad_production.value)


def test_production_requires_a_real_secret_key() -> None:
    with pytest.raises(ValidationError, match="SOUNDINGS_SECRET_KEY"):
        make_settings(environment="production")
    with pytest.raises(ValidationError, match="SOUNDINGS_SECRET_KEY"):
        make_settings(environment="production", secret_key=SecretStr("short"))

    assert make_settings(environment="production", secret_key=SecretStr(STRONG_SECRET))


def test_production_forbids_dev_login() -> None:
    with pytest.raises(ValidationError, match="DEV_LOGIN"):
        make_settings(
            environment="production",
            secret_key=SecretStr(STRONG_SECRET),
            dev_login_enabled=True,
        )


def test_log_level_is_case_insensitive() -> None:
    assert make_settings(log_level="debug").log_level == "DEBUG"


def test_otel_endpoint_is_normalised() -> None:
    assert make_settings(otel_endpoint="").otel_endpoint is None
    assert make_settings(otel_endpoint="http://collector:4318/").otel_endpoint == (
        "http://collector:4318"
    )
    with pytest.raises(ValidationError):
        make_settings(otel_endpoint="collector:4318")
