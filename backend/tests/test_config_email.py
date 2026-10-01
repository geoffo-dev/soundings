"""Phase 3 settings: SMTP (SOUNDINGS_SMTP_*, the chart's names) and notifications."""

from __future__ import annotations

from datetime import UTC
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from app.config import Settings
from tests.certs import write_ca_bundle
from tests.conftest import make_settings

STRONG_SECRET = "s" * 40


def test_email_is_off_by_default() -> None:
    settings = make_settings()

    assert settings.smtp_host is None
    assert not settings.smtp_configured
    assert settings.smtp_port == 587
    assert settings.smtp_security == "starttls"
    assert settings.smtp_from_name == "Soundings"
    assert settings.smtp_timeout == 10
    assert settings.timezone == "UTC"
    assert settings.tz is UTC
    assert settings.digest_hour == 8
    assert settings.reminder_days == [2, 0]


def test_chart_environment_names_are_read(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The names deploy/helm/README.md documents (configmap and secret)."""
    ca_bundle = write_ca_bundle(tmp_path / "ca.crt")
    for name, value in {
        "SOUNDINGS_SMTP_HOST": "smtp.example.com",
        "SOUNDINGS_SMTP_PORT": "465",
        "SOUNDINGS_SMTP_SECURITY": "tls",
        "SOUNDINGS_SMTP_USERNAME": "mailer",
        "SOUNDINGS_SMTP_PASSWORD": "hunter2-hunter2",
        "SOUNDINGS_SMTP_FROM": "soundings@example.com",
        "SOUNDINGS_SMTP_FROM_NAME": "Acme Soundings",
        "SOUNDINGS_SMTP_REPLY_TO": "innovation@example.com",
        "SOUNDINGS_SMTP_CA_BUNDLE": str(ca_bundle),
        "SOUNDINGS_SMTP_TIMEOUT": "15",
        "SOUNDINGS_TIMEZONE": "Europe/London",
        "SOUNDINGS_DIGEST_HOUR": "7",
        "SOUNDINGS_REMINDER_DAYS": "3,1,0",
    }.items():
        monkeypatch.setenv(name, value)

    settings = Settings()

    assert settings.smtp_configured
    assert settings.smtp_host == "smtp.example.com"
    assert settings.smtp_port == 465
    assert settings.smtp_security == "tls"
    assert settings.smtp_username is not None
    assert settings.smtp_username.get_secret_value() == "mailer"
    assert settings.smtp_password is not None
    assert settings.smtp_password.get_secret_value() == "hunter2-hunter2"
    assert settings.smtp_from == "soundings@example.com"
    assert settings.smtp_from_name == "Acme Soundings"
    assert settings.smtp_reply_to == "innovation@example.com"
    assert settings.smtp_ca_bundle == ca_bundle
    assert settings.smtp_timeout == 15
    assert settings.tz == ZoneInfo("Europe/London")
    assert settings.digest_hour == 7
    assert settings.reminder_days == [3, 1, 0]
    assert "hunter2" not in repr(settings)


def test_empty_optional_values_from_the_chart_are_unset() -> None:
    settings = make_settings(
        smtp_host="mailpit",
        smtp_port=1025,
        smtp_security="none",
        smtp_from="soundings@example.com",
        smtp_username="",
        smtp_password="",
        smtp_reply_to=" ",
        smtp_ca_bundle="",
    )

    assert settings.smtp_configured
    assert settings.smtp_username is None
    assert settings.smtp_password is None
    assert settings.smtp_reply_to is None
    assert settings.smtp_ca_bundle is None


def test_a_host_needs_a_sender() -> None:
    with pytest.raises(ValidationError, match="SOUNDINGS_SMTP_FROM is required"):
        make_settings(smtp_host="smtp.example.com")
    assert not make_settings(smtp_host="").smtp_configured


@pytest.mark.parametrize(
    "host", ["smtp://smtp.example.com", "smtp.example.com:587", "a b", "x/y", "fe80::1::2"]
)
def test_host_is_a_bare_name_or_address(host: str) -> None:
    with pytest.raises(ValidationError, match="smtp_host"):
        make_settings(smtp_host=host, smtp_from="a@example.com")


@pytest.mark.parametrize(
    "address",
    [
        "Soundings <soundings@example.com>",
        "soundings@example.com\r\nBcc: victim@example.com",
        "no-at-sign",
        "a@b@example.com",
        "a,b@example.com",
        "soundings@example.com,postmaster",
        "\u00fcser@example.com",
        "a@[10.0.0.1]",
    ],
)
def test_sender_and_reply_to_are_plain_addresses(address: str) -> None:
    with pytest.raises(ValidationError, match="plain email address"):
        make_settings(smtp_host="smtp.example.com", smtp_from=address)
    with pytest.raises(ValidationError, match="plain email address"):
        make_settings(smtp_reply_to=address)


def test_sender_name_cannot_break_the_header() -> None:
    with pytest.raises(ValidationError, match="control characters"):
        make_settings(smtp_from_name="Soundings\r\nBcc: victim@example.com")
    assert make_settings(smtp_from_name="  ").smtp_from_name == "Soundings"


def test_ca_bundle_must_exist(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="existing PEM file"):
        make_settings(smtp_ca_bundle=str(tmp_path / "missing.crt"))
    with pytest.raises(ValidationError, match="existing PEM file"):
        make_settings(smtp_ca_bundle=str(tmp_path))  # a directory


@pytest.mark.parametrize(
    "content",
    [
        "",
        "-----BEGIN CERTIFICATE-----\n",
        "-----BEGIN CERTIFICATE-----\nnot base64\n-----END CERTIFICATE-----\n",
        "just some text\n",
    ],
    ids=["empty", "truncated", "garbage", "text"],
)
def test_ca_bundle_must_hold_a_certificate(tmp_path: Path, content: str) -> None:
    """Review L5: an unusable bundle was accepted at startup and then failed every
    send as "TLS handshake failed", twelve times."""
    path = tmp_path / "ca.crt"
    path.write_text(content)

    with pytest.raises(ValidationError, match="PEM file with at least one certificate"):
        make_settings(smtp_ca_bundle=str(path))


def test_a_ca_bundle_with_a_certificate_is_accepted(tmp_path: Path) -> None:
    path = write_ca_bundle(tmp_path / "ca.crt")

    assert make_settings(smtp_ca_bundle=str(path)).smtp_ca_bundle == path


@pytest.mark.parametrize("value", ["Mars/Olympus", "UTC+1", "../../etc/passwd"])
def test_timezone_must_be_an_iana_name(value: str) -> None:
    with pytest.raises(ValidationError, match="IANA time zone"):
        make_settings(timezone=value)


@pytest.mark.parametrize(
    ("raw", "parsed"),
    [("2,0", [2, 0]), ("0,2,2", [2, 0]), ("[7, 1]", [7, 1]), ("", []), ("0", [0])],
)
def test_reminder_days_are_deduplicated_and_descending(raw: str, parsed: list[int]) -> None:
    assert make_settings(reminder_days=raw).reminder_days == parsed


@pytest.mark.parametrize("raw", ["-1", "31", "1,2,3,4,5,6", "soon"])
def test_reminder_days_are_bounded(raw: str) -> None:
    with pytest.raises(ValidationError):
        make_settings(reminder_days=raw)


@pytest.mark.parametrize(("hour", "ok"), [(0, True), (23, True), (24, False), (-1, False)])
def test_digest_hour_is_an_hour(hour: int, ok: bool) -> None:
    if ok:
        assert make_settings(digest_hour=hour).digest_hour == hour
    else:
        with pytest.raises(ValidationError):
            make_settings(digest_hour=hour)


def test_production_refuses_a_password_over_plain_smtp() -> None:
    production = {
        "environment": "production",
        "secret_key": STRONG_SECRET,
        "base_urls": ["https://soundings.example.com"],
        "smtp_host": "smtp.example.com",
        "smtp_from": "soundings@example.com",
    }
    with pytest.raises(ValidationError, match="SOUNDINGS_SMTP_SECURITY=none"):
        make_settings(**production, smtp_security="none", smtp_password="secret-password")

    # An unauthenticated in-cluster relay, or TLS with a password, is fine.
    assert make_settings(**production, smtp_security="none").smtp_configured
    assert make_settings(
        **production, smtp_security="starttls", smtp_password="secret-password"
    ).smtp_configured


def test_links_in_emails_use_the_first_base_url() -> None:
    settings = make_settings(base_urls="https://ideas.example.com/,https://alt.example.com")

    assert settings.public_base_url == "https://ideas.example.com"


@pytest.mark.parametrize("host", ["smtp.example.com", "10.0.0.25", "::1", "mailpit"])
def test_host_names_and_addresses_are_accepted(host: str) -> None:
    assert make_settings(smtp_host=host, smtp_from="a@example.com").smtp_host == host


@pytest.mark.parametrize(
    ("security", "port", "expected"),
    [
        ("tls", None, 465),
        ("starttls", None, 587),
        ("none", None, 587),
        ("tls", "", 465),
        ("tls", 587, 587),  # an explicit port always wins
        ("none", 1025, 1025),
    ],
)
def test_port_defaults_follow_the_security_mode(
    security: str, port: int | str | None, expected: int
) -> None:
    overrides: dict[str, object] = {"smtp_security": security}
    if port is not None:
        overrides["smtp_port"] = port

    assert make_settings(**overrides).smtp_port == expected


def test_an_empty_port_from_the_chart_follows_the_security_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SOUNDINGS_SMTP_SECURITY", "tls")
    monkeypatch.setenv("SOUNDINGS_SMTP_PORT", "")

    assert Settings().smtp_port == 465


def test_api_pods_get_credential_flags_instead_of_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review L4: the chart gives the SMTP Secret to the worker only; API pods get
    SOUNDINGS_SMTP_USERNAME_SET / _PASSWORD_SET for the admin page."""
    monkeypatch.setenv("SOUNDINGS_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SOUNDINGS_SMTP_FROM", "soundings@example.com")
    monkeypatch.setenv("SOUNDINGS_SMTP_USERNAME_SET", "true")
    monkeypatch.setenv("SOUNDINGS_SMTP_PASSWORD_SET", "true")

    settings = Settings()

    assert settings.smtp_username is None
    assert settings.smtp_password is None
    assert settings.smtp_username_set
    assert settings.smtp_password_set
    assert not make_settings().smtp_password_set


def test_production_refuses_a_plain_connection_with_a_password_flag() -> None:
    with pytest.raises(ValidationError, match="SECURITY=none"):
        make_settings(
            environment="production",
            secret_key=STRONG_SECRET,
            base_urls=["https://ideas.example.com"],
            smtp_host="relay.example.com",
            smtp_security="none",
            smtp_from="ideas@example.com",
            smtp_password_set=True,
        )
