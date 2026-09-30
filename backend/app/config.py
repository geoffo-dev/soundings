"""Application settings, read from ``SOUNDINGS_*`` environment variables.

Every setting has a development-friendly default; production values come from the
Helm chart. List settings accept either a JSON array or a comma-separated string.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from sqlalchemy.engine import URL, make_url

BACKEND_DIR = Path(__file__).resolve().parent.parent
"""The ``backend/`` directory (contains ``app/`` and ``migrations/``)."""

DEV_SECRET_KEY = "dev-insecure-secret-key-change-me"  # noqa: S105 - rejected in production
_ACCEPTED_DRIVERS = {"postgres", "postgresql", "postgresql+psycopg"}

Environment = Literal["development", "test", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


def _split_csv(value: object) -> object:
    """Allow list settings to be given as ``a,b,c`` as well as a JSON array."""
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("["):
            return json.loads(stripped)
        return [item.strip() for item in stripped.split(",") if item.strip()]
    return value


class Settings(BaseSettings):
    """Runtime configuration. Construct via :func:`get_settings` in app code."""

    model_config = SettingsConfigDict(
        env_prefix="SOUNDINGS_",
        extra="ignore",
        frozen=True,
        # Validation errors must not echo values: they include passwords and keys.
        hide_input_in_errors=True,
    )

    environment: Environment = "development"

    # --- Database -----------------------------------------------------------------
    database_url: str = Field(
        default="postgresql+psycopg://soundings:soundings@localhost:5432/soundings",
        repr=False,
        description="SQLAlchemy URL; postgresql:// and postgres:// are accepted too.",
    )
    database_password: SecretStr | None = Field(
        default=None,
        description="Overrides the password in database_url (avoids URL-encoding it).",
    )
    database_pool_size: int = Field(default=5, ge=1, le=100)

    # --- HTTP -----------------------------------------------------------------------
    base_urls: Annotated[list[str], NoDecode] = Field(
        default=["http://localhost:8000"],
        description="External origins the app is served on; the first is the default.",
    )
    trusted_proxies: Annotated[list[str], NoDecode] = Field(
        default=["127.0.0.1"],
        description="IPs/CIDRs whose X-Forwarded-* headers are trusted ('*' = all).",
    )
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    workers: int = Field(default=1, ge=1)
    static_dir: Path = BACKEND_DIR.parent / "frontend" / "dist"

    # --- Security -------------------------------------------------------------------
    secret_key: SecretStr = SecretStr(DEV_SECRET_KEY)
    dev_login_enabled: bool = False

    # --- Observability / worker -----------------------------------------------------
    log_level: LogLevel = "INFO"
    otel_endpoint: str | None = Field(
        default=None,
        description="OTLP/HTTP base URL, e.g. http://otel-collector:4318 (unset: no tracing).",
    )
    worker_concurrency: int = Field(default=4, ge=1, le=64)

    @field_validator("base_urls", "trusted_proxies", mode="before")
    @classmethod
    def _parse_list(cls, value: object) -> object:
        return _split_csv(value)

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_log_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @field_validator("base_urls")
    @classmethod
    def _validate_base_urls(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("at least one base URL is required")
        normalised: list[str] = []
        for raw in value:
            parts = urlsplit(raw.strip())
            if parts.scheme not in {"http", "https"} or not parts.netloc:
                raise ValueError(f"base URL must be an absolute http(s) URL: {raw!r}")
            if parts.query or parts.fragment:
                raise ValueError(f"base URL must not have a query or fragment: {raw!r}")
            normalised.append(f"{parts.scheme}://{parts.netloc.lower()}{parts.path.rstrip('/')}")
        return normalised

    @field_validator("database_url")
    @classmethod
    def _validate_database_url(cls, value: str) -> str:
        url = make_url(value)
        if url.drivername not in _ACCEPTED_DRIVERS:
            raise ValueError("database_url must be a postgresql:// or postgresql+psycopg:// URL")
        return url.set(drivername="postgresql+psycopg").render_as_string(hide_password=False)

    @field_validator("otel_endpoint")
    @classmethod
    def _validate_otel_endpoint(cls, value: str | None) -> str | None:
        if not value:
            return None
        if urlsplit(value).scheme not in {"http", "https"}:
            raise ValueError("otel_endpoint must be an http(s) URL")
        return value.rstrip("/")

    @model_validator(mode="after")
    def _production_guards(self) -> Settings:
        if self.is_production:
            secret = self.secret_key.get_secret_value()
            if secret == DEV_SECRET_KEY or len(secret) < 32:
                raise ValueError("SOUNDINGS_SECRET_KEY must be set to 32+ random characters")
            if self.dev_login_enabled:
                raise ValueError("SOUNDINGS_DEV_LOGIN_ENABLED must be false in production")
        return self

    # --- Derived values -------------------------------------------------------------
    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def sqlalchemy_url(self) -> URL:
        """Database URL for SQLAlchemy (``postgresql+psycopg``)."""
        url = make_url(self.database_url)
        if self.database_password is not None:
            url = url.set(password=self.database_password.get_secret_value())
        return url

    @property
    def database_dsn(self) -> str:
        """libpq-style DSN (``postgresql://...``) for psycopg / procrastinate."""
        return self.sqlalchemy_url.set(drivername="postgresql").render_as_string(
            hide_password=False
        )

    @property
    def allowed_hosts(self) -> list[str]:
        """Host[:port] values of the configured base URLs."""
        return [urlsplit(url).netloc for url in self.base_urls]

    def base_url_for_host(self, host: str | None) -> str:
        """The configured base URL matching a request ``Host`` header.

        Falls back to the first base URL, so links and redirect URIs are only ever
        built from configured values, never from an arbitrary Host header.
        """
        if host:
            wanted = host.lower()
            for url in self.base_urls:
                if urlsplit(url).netloc == wanted:
                    return url
        return self.base_urls[0]

    @property
    def forwarded_allow_ips(self) -> str:
        """``trusted_proxies`` in the comma-separated form uvicorn expects."""
        return ",".join(self.trusted_proxies)


@lru_cache
def get_settings() -> Settings:
    """Process-wide settings (cached). Tests build ``Settings`` directly instead."""
    return Settings()
