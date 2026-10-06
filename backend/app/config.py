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
import ssl
from datetime import UTC, timedelta, tzinfo
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from sqlalchemy.engine import URL, make_url

BACKEND_DIR = Path(__file__).resolve().parent.parent
"""The ``backend/`` directory in a source checkout (contains ``app/`` and ``tests/``)."""

DEV_SECRET_KEY = "dev-insecure-secret-key-change-me"  # noqa: S105 - rejected in production
_ACCEPTED_DRIVERS = {"postgres", "postgresql", "postgresql+psycopg"}

Environment = Literal["development", "test", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]
SmtpSecurity = Literal["none", "starttls", "tls"]
"""``none``: plain SMTP (in-cluster relays, Mailpit); ``starttls``: upgrade on port 587;
``tls``: implicit TLS, usually port 465."""


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
_SMTP_HOST = re.compile(r"[A-Za-z0-9._-]{1,253}")  # a DNS name or IPv4 address

_ATEXT = r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+"
_DOMAIN_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
MAIL_ADDRESS_PATTERN = rf"^{_ATEXT}(?:\.{_ATEXT})*@{_DOMAIN_LABEL}(?:\.{_DOMAIN_LABEL})*$"
"""One plain ASCII address, ``local@domain``: a dot-atom local part and a host name.
No display name, comment, quoting, IP literal, list or whitespace, so nothing a
header could be split on and nothing that names a second recipient
(``victim@corp.com,postmaster`` fails). Used for From / Reply-To, the test email's
``to`` and, at send time, every recipient address (contract-phase3 section 3.11)."""
MAIL_ADDRESS = re.compile(MAIL_ADDRESS_PATTERN)
MAIL_ADDRESS_MAX_LENGTH = 254
"""RFC 5321's limit for a forward path, without the angle brackets."""
MAIL_LOCAL_PART_MAX_LENGTH = 64


def is_mail_address(value: str) -> bool:
    """``value`` is exactly one plain ASCII address (:data:`MAIL_ADDRESS_PATTERN`) within
    the RFC 5321 lengths."""
    return (
        len(value) <= MAIL_ADDRESS_MAX_LENGTH
        and MAIL_ADDRESS.fullmatch(value) is not None
        and len(value.rpartition("@")[0]) <= MAIL_LOCAL_PART_MAX_LENGTH
    )


SMTP_DEFAULT_PORTS: dict[str, int] = {"none": 587, "starttls": 587, "tls": 465}
"""``SOUNDINGS_SMTP_PORT`` when it is unset or empty, by ``SOUNDINGS_SMTP_SECURITY``."""

REMINDER_DAYS_MAX = 30
"""Evaluation reminders go out at most this many days before the due date."""

BRANDING_UPLOAD_MAX_BYTES = 900 * 1024
"""Ceiling for ``SOUNDINGS_BRANDING_MAX_UPLOAD_BYTES``: an image must fit in a request
body under the 1 MiB limit (``app.middleware.MAX_REQUEST_BODY_BYTES``)."""

AiProtocolName = Literal["kagent_v0_10", "kagent_v1_0"]
"""= ``app.models.enums.AiAgentProtocol`` values (config imports nothing from the app;
``tests/test_config_ai.py`` keeps them equal)."""

KAGENT_DEFAULT_URL = "http://kagent-controller.kagent:8083"
"""kagent's Helm default: the ``kagent-controller`` Service in namespace ``kagent``,
A2A on port 8083 (docs/research/kagent-a2a-claude-code-frontend.md section 1)."""

AI_RUN_TIMEOUT_MIN = timedelta(seconds=30)
AI_RUN_TIMEOUT_MAX = timedelta(hours=1)
"""Bounds of ``SOUNDINGS_AI_RUN_TIMEOUT`` (= ``ck_ai_runs_timeout_range``)."""

_KUBERNETES_LABEL = re.compile(r"[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?")
"""= ``app.models.ai.KUBERNETES_LABEL_PATTERN`` (a DNS-1123 label)."""


def _has_control_characters(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)


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
        default=timedelta(hours=24),
        gt=timedelta(0),
        description=(
            "A session ends this long after sign-in, however active it is (default 24 "
            "hours, so IdP removals and group changes apply within a day)."
        ),
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

    # --- Email over SMTP (contract-phase3 section 3.1) -------------------------------
    # Names match the chart (deploy/helm/README.md); credentials come from a Secret.
    smtp_host: str | None = Field(
        default=None,
        description=(
            "SMTP server host name or IP address. Empty: email is off and people get "
            "in-app notifications only (platform admins see a banner)."
        ),
    )
    smtp_port: int = Field(
        default=587,
        ge=1,
        le=65535,
        description="SMTP port. Unset or empty: 465 with security tls, else 587.",
    )
    smtp_security: SmtpSecurity = Field(
        default="starttls",
        description=(
            "none (plain SMTP: an in-cluster relay, Mailpit), starttls (upgrade, usually "
            "port 587) or tls (implicit TLS, usually port 465). TLS verifies the server's "
            "certificate and host name."
        ),
    )
    smtp_username: SecretStr | None = Field(
        default=None, description="Optional SMTP AUTH user name (from the chart's Secret)."
    )
    smtp_password: SecretStr | None = Field(
        default=None, description="Optional SMTP AUTH password (from the chart's Secret)."
    )
    smtp_username_set: bool = Field(
        default=False,
        description=(
            "API pods: the worker has an SMTP user name. Only the worker sends mail, so "
            "the chart gives the credentials to the worker alone and tells the API "
            "(Settings > Email) that they are set."
        ),
    )
    smtp_password_set: bool = Field(
        default=False, description="API pods: the worker has an SMTP password (as above)."
    )
    smtp_from: str | None = Field(
        default=None,
        description="Sender address, e.g. soundings@example.com (required with smtp_host).",
    )
    smtp_from_name: str = Field(
        default="Soundings", max_length=100, description="Sender display name."
    )
    smtp_reply_to: str | None = Field(
        default=None, description="Optional Reply-To address (default: no Reply-To header)."
    )
    smtp_ca_bundle: Path | None = Field(
        default=None,
        description=(
            "PEM file with the CA certificate(s) that signed the SMTP server's certificate "
            "(default: the system trust store). The chart mounts it from a ConfigMap."
        ),
    )
    smtp_timeout: float = Field(
        default=10,
        gt=0,
        le=120,
        description="Seconds to wait for the connection and for each SMTP command.",
    )

    # --- Notifications (contract-phase3 sections 3.6-3.7) ---------------------------
    timezone: str = Field(
        default="UTC",
        description=(
            "IANA time zone of the organisation (e.g. Europe/London): the daily digest "
            "and evaluation reminders go out at digest_hour in it, and emails show dates "
            "in it. One zone per instance (no per-user zones)."
        ),
    )
    digest_hour: int = Field(
        default=8,
        ge=0,
        le=23,
        description="Hour of the day (0-23, in timezone) for daily digests and reminders.",
    )
    reminder_days: Annotated[list[int], NoDecode] = Field(
        default=[2, 0],
        description=(
            "Evaluation reminders: days before the due date (0 = on the due date), e.g. "
            "2,0. Empty: no reminders."
        ),
    )

    # --- Public submission and branding (contract-phase4 sections 3.4-3.12) ---------
    # Names match the chart (deploy/helm/README.md). The ALTCHA HMAC key, the
    # verification-link key and the tracking-token sealing key are derived from
    # secret_key (HKDF, one purpose each): nothing more to configure or rotate.
    public_submission_enabled: bool = Field(
        default=True,
        description=(
            "Instance switch for public submission (the chart's features.publicSubmission). "
            "false: every project's public form, tracking link and verification link "
            "answers 404, and project settings can't turn a form on."
        ),
    )
    public_submissions_per_ip: int = Field(
        default=10,
        ge=1,
        le=1000,
        description=(
            "Public submissions one client IP address (IPv6: per /64) may send per hour, "
            "across all projects. Counted per API process, like the sign-in throttles."
        ),
    )
    public_submissions_per_project: int = Field(
        default=100,
        ge=1,
        le=10_000,
        description=(
            "Public submissions one project accepts per hour, from everyone (counted in the "
            "database, so across API replicas)."
        ),
    )
    altcha_cost: int = Field(
        default=5_000,
        ge=1_000,
        le=1_000_000,
        description=(
            "ALTCHA proof-of-work cost (PBKDF2/SHA-256 iterations per attempt, random "
            "mode). Higher is slower for bots and for people on old phones."
        ),
    )
    altcha_expiry: timedelta = Field(
        default=timedelta(minutes=30),
        description=(
            "How long an ALTCHA challenge can be solved and sent (an ISO 8601 duration such "
            "as PT30M; 1 minute to 1 day). Solved challenges are remembered this long, so a "
            "solution is accepted once."
        ),
    )
    branding_max_upload_bytes: int = Field(
        default=512 * 1024,
        ge=16 * 1024,
        le=BRANDING_UPLOAD_MAX_BYTES,
        description=(
            "Largest logo or favicon upload in bytes (default 512 KiB, at most 900 KiB so "
            "it fits the 1 MiB request limit)."
        ),
    )

    # --- AI assistance through kagent (contract-phase6 section 3.2) ------------------
    # Names match the chart (features.ai, kagent.*). The A2A URL of an agent is built
    # from kagent_url + the protocol's fixed path + the agent's namespace and name
    # (DNS labels), never taken from a request or an agent card, so nothing else can be
    # reached from the UI (SSRF).
    ai_enabled: bool = Field(
        default=False,
        description=(
            "Instance switch for AI assistance (the chart's features.ai). false: no run "
            "starts (c10: 409 ai_unavailable), queued runs fail ai_disabled, and the idea "
            "page hides the AI actions; Admin settings -> AI agents still registers agents."
        ),
    )
    kagent_url: str = Field(
        default=KAGENT_DEFAULT_URL,
        description=(
            "Base URL of kagent's controller (its A2A endpoint, port 8083): an absolute "
            "http(s) URL without a path, query or credentials."
        ),
    )
    kagent_token: SecretStr | None = Field(
        default=None,
        repr=False,
        description=(
            "Optional bearer token for the kagent controller (its trusted-proxy auth mode): "
            "sent as Authorization: Bearer <token> on every A2A request. Never logged or "
            "shown (Admin settings shows only whether it is set)."
        ),
    )
    ai_default_protocol: AiProtocolName = Field(
        default="kagent_v0_10",
        description=(
            "Protocol of a newly registered agent when the admin doesn't choose one: "
            "kagent_v0_10 (/api/a2a/{namespace}/{name}/, A2A 0.3) or kagent_v1_0 "
            "(/agents/{namespace}/{name}, A2A 1.0)."
        ),
    )
    ai_run_timeout: timedelta = Field(
        default=timedelta(minutes=5),
        description=(
            "How long a run may take once it has started (an ISO 8601 duration such as "
            "PT5M, or seconds; 30 seconds to 1 hour). Then the worker asks the agent to "
            "cancel and the run is timed_out."
        ),
    )
    ai_max_concurrent_runs: int = Field(
        default=4,
        ge=1,
        le=50,
        description=(
            "Runs talking to agents at the same time, across every worker; the rest wait "
            "queued, oldest first."
        ),
    )
    ai_agent_namespaces: Annotated[list[str], NoDecode] = Field(
        default_factory=list,
        description=(
            "Kubernetes namespaces agents may be registered in (comma-separated). Empty: "
            "any namespace."
        ),
    )
    ai_mcp_url: str | None = Field(
        default=None,
        description=(
            "The MCP URL agents use to reach Soundings (the chart sets the Service URL, "
            "http://<release>.<namespace>.svc.cluster.local:<port>/mcp). Sent to agents as a "
            "hint and shown in Admin settings; unset: the first base URL + /mcp."
        ),
    )

    # --- Observability / worker -----------------------------------------------------
    otel_endpoint: str | None = Field(
        default=None,
        description="OTLP/HTTP base URL, e.g. http://otel-collector:4318 (unset: no tracing).",
    )
    worker_concurrency: int = Field(default=4, ge=1, le=64)

    @field_validator(
        "base_urls",
        "trusted_proxies",
        "oidc_scopes",
        "reminder_days",
        "ai_agent_namespaces",
        mode="before",
    )
    @classmethod
    def _parse_list(cls, value: object) -> object:
        return _split_csv(value)

    @field_validator("kagent_url")
    @classmethod
    def _validate_kagent_url(cls, value: str) -> str:
        parts = urlsplit(value.strip())
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise ValueError("kagent_url must be an absolute http(s) URL")
        if parts.username is not None or parts.password is not None:
            raise ValueError("kagent_url must not contain credentials (use kagent_token)")
        if parts.path.strip("/") or parts.query or parts.fragment:
            raise ValueError("kagent_url must not have a path, query or fragment")
        if _has_control_characters(value):
            raise ValueError("kagent_url must not contain control characters")
        return f"{parts.scheme}://{parts.netloc.lower()}"

    @field_validator("kagent_token", mode="before")
    @classmethod
    def _empty_token_is_unset(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("kagent_token")
    @classmethod
    def _validate_kagent_token(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and (
            _has_control_characters(value.get_secret_value()) or " " in value.get_secret_value()
        ):
            raise ValueError("kagent_token must be one token without spaces or control characters")
        return value

    @field_validator("ai_run_timeout")
    @classmethod
    def _validate_ai_run_timeout(cls, value: timedelta) -> timedelta:
        if not AI_RUN_TIMEOUT_MIN <= value <= AI_RUN_TIMEOUT_MAX:
            raise ValueError("ai_run_timeout must be between 30 seconds and 1 hour")
        return value

    @field_validator("ai_agent_namespaces")
    @classmethod
    def _validate_ai_agent_namespaces(cls, value: list[str]) -> list[str]:
        for namespace in value:
            if not _KUBERNETES_LABEL.fullmatch(namespace):
                raise ValueError(f"not a Kubernetes namespace name: {namespace!r}")
        return sorted(set(value))

    @field_validator("ai_mcp_url", mode="before")
    @classmethod
    def _empty_mcp_url_is_unset(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("ai_mcp_url")
    @classmethod
    def _validate_ai_mcp_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parts = urlsplit(value.strip())
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise ValueError("ai_mcp_url must be an absolute http(s) URL")
        if parts.username is not None or parts.query or parts.fragment:
            raise ValueError("ai_mcp_url must not have credentials, a query or a fragment")
        if _has_control_characters(value):
            raise ValueError("ai_mcp_url must not contain control characters")
        return value.strip()

    @model_validator(mode="before")
    @classmethod
    def _default_smtp_port(cls, data: object) -> object:
        """An unset or empty port follows the security mode (465 for implicit TLS)."""
        if not isinstance(data, dict):
            return data
        port = data.get("smtp_port")
        if port is None or (isinstance(port, str) and not port.strip()):
            security = data.get("smtp_security") or "starttls"
            default = SMTP_DEFAULT_PORTS.get(str(security).strip(), 587)
            return {**data, "smtp_port": default}
        return data

    @field_validator(
        "smtp_host",
        "smtp_username",
        "smtp_password",
        "smtp_from",
        "smtp_reply_to",
        "smtp_ca_bundle",
        mode="before",
    )
    @classmethod
    def _empty_is_unset(cls, value: object) -> object:
        """The chart passes optional values as empty strings; treat them as unset."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("smtp_host")
    @classmethod
    def _validate_smtp_host(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if ":" in value:  # only an IPv6 address may contain colons (no host:port)
            try:
                ipaddress.IPv6Address(value)
            except ValueError:
                raise ValueError(
                    "smtp_host must be a host name or IP address (no scheme or port)"
                ) from None
        elif not _SMTP_HOST.fullmatch(value):
            raise ValueError("smtp_host must be a host name or IP address (no scheme or port)")
        return value

    @field_validator("smtp_from", "smtp_reply_to")
    @classmethod
    def _validate_mail_address(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not is_mail_address(value):
            raise ValueError("must be a plain email address such as soundings@example.com")
        return value

    @field_validator("smtp_from_name")
    @classmethod
    def _validate_from_name(cls, value: str) -> str:
        value = value.strip()
        if _has_control_characters(value):
            raise ValueError("smtp_from_name must not contain control characters")
        return value or "Soundings"

    @field_validator("smtp_ca_bundle")
    @classmethod
    def _validate_ca_bundle(cls, value: Path | None) -> Path | None:
        if value is None:
            return None
        if not value.is_file():
            raise ValueError("smtp_ca_bundle must be the path of an existing PEM file")
        # Fail at startup, not on every send ("TLS handshake failed", twelve times).
        try:
            context = ssl.create_default_context(cafile=str(value))
        except (ssl.SSLError, OSError, ValueError):
            context = None
        if context is None or not context.cert_store_stats().get("x509"):
            raise ValueError(
                "smtp_ca_bundle must be a PEM file with at least one certificate "
                "(-----BEGIN CERTIFICATE-----)"
            )
        return value

    @field_validator("timezone")
    @classmethod
    def _validate_timezone(cls, value: str) -> str:
        value = value.strip() or "UTC"
        if value == "UTC":
            return value  # needs no time zone database
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(
                f"timezone must be an IANA time zone such as Europe/London: {value!r}"
            ) from None
        return value

    @field_validator("reminder_days")
    @classmethod
    def _validate_reminder_days(cls, value: list[int]) -> list[int]:
        if any(day < 0 or day > REMINDER_DAYS_MAX for day in value):
            raise ValueError(f"reminder_days must be between 0 and {REMINDER_DAYS_MAX}")
        if len(set(value)) > 5:
            raise ValueError("at most 5 reminder days")
        return sorted(set(value), reverse=True)

    @field_validator("altcha_expiry")
    @classmethod
    def _validate_altcha_expiry(cls, value: timedelta) -> timedelta:
        if not timedelta(minutes=1) <= value <= timedelta(days=1):
            raise ValueError("altcha_expiry must be between 1 minute and 1 day")
        return value

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
        if self.smtp_host and not self.smtp_from:
            raise ValueError("SOUNDINGS_SMTP_FROM is required when SOUNDINGS_SMTP_HOST is set")
        password = self.smtp_password.get_secret_value() if self.smtp_password else ""
        password = password or ("set" if self.smtp_password_set else "")
        if self.is_production and self.smtp_host and self.smtp_security == "none" and password:
            # SMTP AUTH over a plain connection sends the password in clear text.
            raise ValueError(
                "SOUNDINGS_SMTP_SECURITY=none can't be used with a password in "
                "production: use starttls or tls"
            )
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
    def smtp_configured(self) -> bool:
        """Email is on: a host (and, enforced above, a sender) is configured. Otherwise
        nothing is written to the outbox and people get in-app notifications only."""
        return self.smtp_host is not None and self.smtp_from is not None

    @property
    def ai_mcp_url_effective(self) -> str:
        """The MCP URL agents are told about: ``ai_mcp_url``, else the first base URL +
        ``/mcp``."""
        return self.ai_mcp_url or self.public_base_url + "/mcp"

    @property
    def ai_run_timeout_seconds(self) -> int:
        """``ai_run_timeout`` in whole seconds (``ai_runs.timeout_seconds``)."""
        return int(self.ai_run_timeout.total_seconds())

    @property
    def public_base_url(self) -> str:
        """The origin used in links that leave the app (emails): the first base URL."""
        return self.base_urls[0]

    @property
    def tz(self) -> tzinfo:
        """:attr:`timezone` as a ``tzinfo`` (``datetime.UTC`` for ``UTC``)."""
        return UTC if self.timezone == "UTC" else ZoneInfo(self.timezone)

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
