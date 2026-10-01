"""Application settings, read from ``SOUNDINGS_*`` environment variables.

Every setting has a development-friendly default; production values come from the
Helm chart. List settings accept either a JSON array or a comma-separated string.

:class:`DatabaseSettings` holds only what talking to the database needs; the
``migrate`` and ``wait-for-db`` commands use it, so they run without the API's
secrets (``SECRET_KEY``). :class:`Settings` adds everything else and the production
guards.
"""

from __future__ import annotations

import ipaddress
import json
import re
from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from sqlalchemy.engine import URL, make_url

BACKEND_DIR = Path(__file__).resolve().parent.parent
"""The ``backend/`` directory in a source checkout (contains ``app/`` and ``tests/``)."""

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


_SETTINGS_CONFIG = SettingsConfigDict(
    env_prefix="SOUNDINGS_",
    extra="ignore",
    frozen=True,
    # Validation errors must not echo values: they include passwords and keys.
    hide_input_in_errors=True,
)

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
"""Hosts always accepted outside production (dev servers, the Vite proxy)."""

OIDC_CALLBACK_PATH = "/api/v1/auth/callback"
"""Appended to a base URL: the redirect URI the IdP sends the browser back to."""

POST_LOGOUT_PATH = "/login?signed_out=1"
"""Appended to a base URL: where the IdP returns the browser after signing out."""

BREAK_GLASS_MIN_PASSWORD_LENGTH = 16
"""Production refuses a shorter break-glass password (the chart generates 24)."""

OIDC_ISSUER_MAX_LENGTH = 512
"""= ``user_identities.issuer``: the issuer is stored with every linked identity."""

_SCOPE_TOKEN = re.compile(r"[\x21\x23-\x5b\x5d-\x7e]+")  # RFC 6749 scope-token
_EXTERNAL_ID_KIND = re.compile(r"[a-z][a-z0-9_]{0,39}")  # = app.models.user's pattern


class DatabaseSettings(BaseSettings):
    """What the database commands need: environment, logging and the database."""

    model_config = _SETTINGS_CONFIG

    environment: Environment = "development"
    log_level: LogLevel = "INFO"

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

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_log_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @field_validator("database_url")
    @classmethod
    def _validate_database_url(cls, value: str) -> str:
        url = make_url(value)
        if url.drivername not in _ACCEPTED_DRIVERS:
            raise ValueError("database_url must be a postgresql:// or postgresql+psycopg:// URL")
        return url.set(drivername="postgresql+psycopg").render_as_string(hide_password=False)

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


class Settings(DatabaseSettings):
    """Runtime configuration. Construct via :func:`get_settings` in app code."""

    model_config = _SETTINGS_CONFIG

    # --- HTTP -----------------------------------------------------------------------
    base_urls: Annotated[list[str], NoDecode] = Field(
        default=["http://localhost:8000"],
        description=(
            "External origins the app is served on; the first is the default. Requests "
            "for any other host are refused (400), except /healthz and /readyz."
        ),
    )
    trusted_proxies: Annotated[list[str], NoDecode] = Field(
        default=["127.0.0.1"],
        description=(
            "IPs/CIDRs of the proxies in front of the app (the ingress controller) whose "
            "X-Forwarded-For/-Proto headers are believed ('*' = any peer)."
        ),
    )
    trusted_proxy_hops: int = Field(
        default=1,
        ge=1,
        le=5,
        description=(
            "How many trusted proxies append to X-Forwarded-For in front of the app: 1 "
            "for an ingress controller, 2 with a load balancer in front of it that also "
            "appends. The client is that many entries from the right (fewer if one of "
            "them is not a trusted proxy); entries further left are the client's own."
        ),
    )
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    workers: int = Field(default=1, ge=1)
    static_dir: Path = BACKEND_DIR.parent / "frontend" / "dist"
    metrics_port: int = Field(
        default=9090,
        ge=0,
        le=65535,
        description=(
            "Port of the separate Prometheus endpoint (/metrics), bound to host. 0: no "
            "separate port; outside production /metrics is then served on the app port."
        ),
    )

    # --- Security -------------------------------------------------------------------
    secret_key: SecretStr = SecretStr(DEV_SECRET_KEY)
    dev_login_enabled: bool = False
    session_idle_timeout: timedelta = Field(
        default=timedelta(hours=12),
        gt=timedelta(0),
        description="A session ends after this long without a request (seconds or ISO 8601).",
    )
    session_max_age: timedelta = Field(
        default=timedelta(days=7),
        gt=timedelta(0),
        description="A session ends this long after sign-in, however active it is.",
    )
    cookie_secure: bool | None = Field(
        default=None,
        description=(
            "Secure flag on the session cookies. Default: set, except on plain-http "
            "requests outside production. false is refused in production."
        ),
    )

    # --- Single sign-on (OIDC; contract-phase2 section 3) ----------------------------
    # One provider per instance. Names match the chart (deploy/helm/README.md).
    oidc_issuer: str | None = Field(
        default=None,
        description=(
            "OIDC issuer URL, e.g. https://keycloak.example.com/realms/acme (its "
            "/.well-known/openid-configuration is used). Empty: SSO off."
        ),
    )
    oidc_client_id: str = Field(default="soundings", min_length=1, max_length=255)
    oidc_client_secret: SecretStr | None = Field(
        default=None, description="Confidential client secret (none: a public PKCE client)."
    )
    oidc_scopes: Annotated[list[str], NoDecode] = Field(
        default=["openid", "profile", "email"],
        description="Requested scopes; openid is always included.",
    )
    oidc_groups_claim: str = Field(
        default="groups",
        max_length=200,
        description=(
            "Claim holding the user's IdP groups: a top-level name or a dotted path "
            "(realm_access.roles). Empty: no group sync."
        ),
    )
    oidc_external_id_claim: str = Field(
        default="",
        max_length=200,
        description=(
            "Claim (name or dotted path) matched against users' external IDs at first "
            "sign-in, e.g. employee_no. Empty: no external-ID matching. It MUST come "
            "from an attribute only IdP admins can set (Keycloak: user-profile edit "
            "permission admin only, unmanaged attributes not enabled; Entra ID: oid or "
            "employeeid): whoever can choose its value can sign in as the pre-created "
            "user who has it, platform admins included."
        ),
    )
    oidc_external_id_kind: str = Field(
        default="",
        description=(
            "External-ID kind the claim is matched against. Default: the claim path's "
            "last dotted segment (attributes.employee_no -> employee_no); required when "
            "that is not a valid kind."
        ),
    )
    oidc_match_verified_email: bool = Field(
        default=True,
        description="Link an existing user by email when the IdP says email_verified=true.",
    )
    oidc_auto_create_users: bool = Field(
        default=False,
        description=(
            "Create an account for an unmatched IdP user with a verified email (else: no access)."
        ),
    )

    # --- Break-glass admin (credentials from a K8s Secret) ---------------------------
    break_glass_enabled: bool = Field(
        default=False,
        description=(
            "Allow the local break-glass admin. It is available only while SSO is not "
            "configured (no oidc_issuer) and both credentials are set."
        ),
    )
    break_glass_username: SecretStr | None = None
    break_glass_password: SecretStr | None = None

    # --- Observability / worker -----------------------------------------------------
    otel_endpoint: str | None = Field(
        default=None,
        description="OTLP/HTTP base URL, e.g. http://otel-collector:4318 (unset: no tracing).",
    )
    worker_concurrency: int = Field(default=4, ge=1, le=64)

    @field_validator("base_urls", "trusted_proxies", "oidc_scopes", mode="before")
    @classmethod
    def _parse_list(cls, value: object) -> object:
        return _split_csv(value)

    @field_validator("trusted_proxies")
    @classmethod
    def _validate_trusted_proxies(cls, value: list[str]) -> list[str]:
        for entry in value:
            if entry == "*":
                continue
            try:
                ipaddress.ip_network(entry, strict=False)
            except ValueError:
                raise ValueError(
                    f"trusted_proxies must be IP addresses, CIDR networks or '*': {entry!r}"
                ) from None
        return value

    @field_validator("oidc_issuer")
    @classmethod
    def _validate_oidc_issuer(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip()
        if len(value) > OIDC_ISSUER_MAX_LENGTH:
            raise ValueError(f"oidc_issuer must be at most {OIDC_ISSUER_MAX_LENGTH} characters")
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            raise ValueError("oidc_issuer must be an absolute http(s) URL")
        if parts.query or parts.fragment:
            raise ValueError("oidc_issuer must not have a query or fragment")
        # Kept exactly as configured: it must equal the provider's `iss`.
        return value

    @field_validator("oidc_scopes")
    @classmethod
    def _validate_oidc_scopes(cls, value: list[str]) -> list[str]:
        scopes = ["openid", *(scope.strip() for scope in value)]
        for scope in scopes:
            if not _SCOPE_TOKEN.fullmatch(scope):
                raise ValueError(f"invalid OIDC scope: {scope!r}")
        return list(dict.fromkeys(scopes))

    @field_validator("oidc_groups_claim", "oidc_external_id_claim")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError("must not contain control characters")
        return value

    @field_validator("oidc_external_id_kind")
    @classmethod
    def _default_external_id_kind(cls, value: str, info: ValidationInfo) -> str:
        claim = str(info.data.get("oidc_external_id_claim") or "")
        if not claim:
            return ""
        kind = value.strip() or claim.rsplit(".", 1)[-1]
        if not _EXTERNAL_ID_KIND.fullmatch(kind):
            raise ValueError(
                "SOUNDINGS_OIDC_EXTERNAL_ID_KIND must be set to a kind such as employee_no "
                "(lower-case letters, digits, underscores) when the claim path's last "
                "segment is not one"
            )
        return kind

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
        if self.session_max_age < self.session_idle_timeout:
            raise ValueError("session_max_age must be at least session_idle_timeout")
        if self.is_production:
            secret = self.secret_key.get_secret_value()
            if secret == DEV_SECRET_KEY or len(secret) < 32:
                raise ValueError("SOUNDINGS_SECRET_KEY must be set to 32+ random characters")
            if self.dev_login_enabled:
                raise ValueError("SOUNDINGS_DEV_LOGIN_ENABLED must be false in production")
            if self.cookie_secure is False:
                raise ValueError("SOUNDINGS_COOKIE_SECURE must not be false in production")
            if self.oidc_issuer and urlsplit(self.oidc_issuer).scheme != "https":
                raise ValueError("SOUNDINGS_OIDC_ISSUER must be an https URL in production")
            if self.oidc_issuer and any(not url.startswith("https://") for url in self.base_urls):
                # Redirect URIs (with the authorization code) and cookies would travel
                # over plain HTTP.
                raise ValueError(
                    "SOUNDINGS_BASE_URLS must all be https URLs in production when SSO is "
                    "configured"
                )
            secret_password = self.break_glass_password
            password = secret_password.get_secret_value() if secret_password else ""
            if self.break_glass_enabled and 0 < len(password) < BREAK_GLASS_MIN_PASSWORD_LENGTH:
                raise ValueError(
                    "SOUNDINGS_BREAK_GLASS_PASSWORD must have at least "
                    f"{BREAK_GLASS_MIN_PASSWORD_LENGTH} characters in production"
                )
        return self

    # --- Derived values -------------------------------------------------------------
    @property
    def allowed_hosts(self) -> list[str]:
        """Host[:port] values of the configured base URLs."""
        return [urlsplit(url).netloc for url in self.base_urls]

    @property
    def trusted_hosts(self) -> frozenset[str]:
        """Host names (no port) requests may be addressed to.

        The configured base URLs' hosts; outside production also ``localhost``,
        ``127.0.0.1`` and ``::1``.
        """
        hosts = {urlsplit(url).hostname or "" for url in self.base_urls} - {""}
        if not self.is_production:
            hosts |= LOCAL_HOSTS
        return frozenset(hosts)

    @property
    def sso_configured(self) -> bool:
        """SSO sign-in is on: an issuer is configured."""
        return self.oidc_issuer is not None

    @property
    def break_glass_available(self) -> bool:
        """The break-glass sign-in works: enabled, both credentials set, and SSO not
        configured ("off once SSO is configured"; unset the issuer to bring it back)."""
        return (
            self.break_glass_enabled
            and not self.sso_configured
            and bool(self.break_glass_username and self.break_glass_username.get_secret_value())
            and bool(self.break_glass_password and self.break_glass_password.get_secret_value())
        )

    def oidc_redirect_uri(self, base_url: str) -> str:
        """The callback URL to register at the IdP for one of ``base_urls``."""
        return base_url + OIDC_CALLBACK_PATH

    def oidc_post_logout_redirect_uri(self, base_url: str) -> str:
        """Where the IdP sends the browser after RP-initiated logout, per base URL."""
        return base_url + POST_LOGOUT_PATH

    @property
    def metrics_on_app_port(self) -> bool:
        """Serve ``/metrics`` on the app port: only outside production, with no metrics port."""
        return self.metrics_port == 0 and not self.is_production

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


@lru_cache
def get_settings() -> Settings:
    """Process-wide settings (cached). Tests build ``Settings`` directly instead."""
    return Settings()


@lru_cache
def get_database_settings() -> DatabaseSettings:
    """Only the database settings: needs no API secrets (``migrate``, ``wait-for-db``)."""
    return DatabaseSettings()
