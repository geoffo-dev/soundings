"""Phase 2 settings: OIDC (SOUNDINGS_OIDC_*) and the break-glass admin."""

from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from app.config import Settings
from tests.conftest import make_settings

STRONG_SECRET = "s" * 40
ISSUER = "https://keycloak.example.com/realms/acme"


def test_sso_is_off_by_default() -> None:
    settings = make_settings()

    assert settings.oidc_issuer is None
    assert not settings.sso_configured
    assert settings.oidc_scopes == ["openid", "profile", "email"]
    assert settings.oidc_groups_claim == "groups"
    assert settings.oidc_match_verified_email is True
    assert settings.oidc_auto_create_users is False
    assert not settings.break_glass_available


def test_chart_environment_names_are_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """The names deploy/helm/README.md documents."""
    for name, value in {
        "SOUNDINGS_OIDC_ISSUER": ISSUER,
        "SOUNDINGS_OIDC_CLIENT_ID": "soundings",
        "SOUNDINGS_OIDC_CLIENT_SECRET": "shh",
        "SOUNDINGS_OIDC_GROUPS_CLAIM": "realm_access.roles",
        "SOUNDINGS_OIDC_EXTERNAL_ID_CLAIM": "employee_no",
        "SOUNDINGS_OIDC_SCOPES": "openid,profile,email,groups",
        "SOUNDINGS_BREAK_GLASS_ENABLED": "true",
        "SOUNDINGS_BREAK_GLASS_USERNAME": "admin",
        "SOUNDINGS_BREAK_GLASS_PASSWORD": "pw",
    }.items():
        monkeypatch.setenv(name, value)

    settings = Settings()

    assert settings.sso_configured
    assert settings.oidc_issuer == ISSUER
    assert settings.oidc_client_secret is not None
    assert settings.oidc_client_secret.get_secret_value() == "shh"
    assert settings.oidc_groups_claim == "realm_access.roles"
    assert settings.oidc_external_id_kind == "employee_no"
    assert settings.oidc_scopes == ["openid", "profile", "email", "groups"]
    assert settings.break_glass_enabled
    # Off once SSO is configured.
    assert not settings.break_glass_available
    assert "shh" not in repr(settings)
    assert "'pw'" not in repr(settings)


def test_openid_scope_is_always_requested() -> None:
    assert make_settings(oidc_scopes=["email"]).oidc_scopes == ["openid", "email"]
    with pytest.raises(ValidationError):
        make_settings(oidc_scopes=['bad"scope'])


@pytest.mark.parametrize("issuer", ["keycloak.example.com", "ftp://x.example.com", f"{ISSUER}?a=1"])
def test_invalid_issuers_are_rejected(issuer: str) -> None:
    with pytest.raises(ValidationError):
        make_settings(oidc_issuer=issuer)


def test_blank_issuer_means_sso_off() -> None:
    assert not make_settings(oidc_issuer="  ").sso_configured


def test_external_id_kind_defaults_to_the_claim_paths_last_segment() -> None:
    assert make_settings(oidc_external_id_claim="employee_no").oidc_external_id_kind == (
        "employee_no"
    )
    assert make_settings(oidc_external_id_claim="attributes.emp").oidc_external_id_kind == "emp"
    assert make_settings(oidc_external_id_kind="employee_no").oidc_external_id_kind == ""
    explicit = make_settings(
        oidc_external_id_claim="extension_EmployeeId", oidc_external_id_kind="emp"
    )
    assert explicit.oidc_external_id_kind == "emp"
    with pytest.raises(ValidationError, match="EXTERNAL_ID_KIND"):
        make_settings(oidc_external_id_claim="extension_EmployeeId")


def test_issuer_fits_the_identities_table() -> None:
    long_issuer = "https://idp.example.com/" + "r" * 500
    with pytest.raises(ValidationError, match="512"):
        make_settings(oidc_issuer=long_issuer)


def test_break_glass_needs_both_credentials_and_no_sso() -> None:
    def available(**overrides: object) -> bool:
        values: dict[str, object] = {
            "break_glass_enabled": True,
            "break_glass_username": SecretStr("admin"),
            "break_glass_password": SecretStr("pw"),
            **overrides,
        }
        return make_settings(**values).break_glass_available

    assert available()
    assert not available(break_glass_enabled=False)
    assert not available(break_glass_username=None)
    assert not available(break_glass_password=SecretStr(""))
    assert not available(oidc_issuer=ISSUER)


def test_production_wants_https_issuer_and_a_long_break_glass_password() -> None:
    production = {"environment": "production", "secret_key": SecretStr(STRONG_SECRET)}
    with pytest.raises(ValidationError, match="OIDC_ISSUER"):
        make_settings(**production, oidc_issuer="http://keycloak.example.com/realms/acme")
    with pytest.raises(ValidationError, match="BREAK_GLASS_PASSWORD"):
        make_settings(
            **production,
            break_glass_enabled=True,
            break_glass_username=SecretStr("admin"),
            break_glass_password=SecretStr("short"),
        )

    assert make_settings(
        **production,
        base_urls=["https://ideas.example.com"],
        oidc_issuer=ISSUER,
        break_glass_enabled=True,
        break_glass_username=SecretStr("admin"),
        break_glass_password=SecretStr("p" * 16),
    )


def test_production_sso_needs_https_base_urls() -> None:
    """Redirect URIs carry the authorization code, and cookies follow the base URL."""
    production = {"environment": "production", "secret_key": SecretStr(STRONG_SECRET)}
    with pytest.raises(ValidationError, match="BASE_URLS"):
        make_settings(
            **production,
            base_urls=["https://ideas.example.com", "http://ideas.example.org"],
            oidc_issuer=ISSUER,
        )
    # Without SSO (dev login off, break-glass only) a plain-http base URL still starts.
    assert make_settings(**production, base_urls=["http://localhost:18081"])
    # Outside production http is fine (local Keycloak).
    assert make_settings(oidc_issuer="http://localhost:8080/realms/soundings")


def test_redirect_uris_derive_from_base_urls() -> None:
    settings = make_settings(base_urls=["https://ideas.example.com", "https://ideas.example.org"])

    assert [settings.oidc_redirect_uri(url) for url in settings.base_urls] == [
        "https://ideas.example.com/api/v1/auth/callback",
        "https://ideas.example.org/api/v1/auth/callback",
    ]
    assert settings.oidc_post_logout_redirect_uri(settings.base_urls[1]) == (
        "https://ideas.example.org/login?signed_out=1"
    )
