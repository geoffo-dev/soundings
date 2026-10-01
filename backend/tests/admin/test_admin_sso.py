"""Admin settings -> Single sign-on (contract-phase2 section 3.10): the effective
configuration, read-only, with secrets masked, the URIs to register per base URL and
the provider's discovery status."""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from app.auth.oidc import OidcProvider
from tests.admin.conftest import AsUser, People, assert_problem, ok

ISSUER = "https://idp.example.com/realms/acme"
SECRETS = ("client-secret-value", "bg-user", "bg-password-value")


def discovery_document(issuer: str = ISSUER, *, end_session: bool = True) -> dict[str, str]:
    document = {
        "issuer": issuer,
        "authorization_endpoint": f"{ISSUER}/protocol/openid-connect/auth",
        "token_endpoint": f"{ISSUER}/protocol/openid-connect/token",
        "jwks_uri": f"{ISSUER}/protocol/openid-connect/certs",
    }
    if end_session:
        document["end_session_endpoint"] = f"{ISSUER}/protocol/openid-connect/logout"
    return document


def use_idp(app: FastAPI, handler: httpx.MockTransport) -> None:
    app.state.oidc_provider = OidcProvider(app.state.settings, transport=handler)


@pytest.mark.settings(
    base_urls=["http://testserver", "https://ideas.example.com"],
    break_glass_enabled=True,
    break_glass_username="bg-user",
    break_glass_password="bg-password-value",
    oidc_client_secret="client-secret-value",
    oidc_groups_claim="",
)
async def test_sso_off(api: AsUser, people: People) -> None:
    admin = await api(people.admin)

    response = await admin.get("/admin/sso")
    config = ok(response)

    assert config["enabled"] is False
    assert config["issuer"] is None
    assert config["discovery"] is None
    assert config["client_id"] == "soundings"
    assert config["client_secret_set"] is True
    assert config["scopes"] == ["openid", "profile", "email"]
    assert config["groups_claim"] is None
    assert config["external_id_claim"] is None
    assert config["external_id_kind"] is None
    assert config["match_verified_email"] is True
    assert config["auto_create_users"] is False
    assert config["redirect_uris"] == [
        {
            "base_url": "http://testserver",
            "redirect_uri": "http://testserver/api/v1/auth/callback",
            "post_logout_redirect_uri": "http://testserver/login?signed_out=1",
        },
        {
            "base_url": "https://ideas.example.com",
            "redirect_uri": "https://ideas.example.com/api/v1/auth/callback",
            "post_logout_redirect_uri": "https://ideas.example.com/login?signed_out=1",
        },
    ]
    assert config["break_glass"] == {"enabled": True, "credentials_set": True, "available": True}
    assert config["dev_login"] is True
    assert not any(secret in response.text for secret in SECRETS)


@pytest.mark.settings(
    oidc_issuer=ISSUER,
    oidc_client_secret="client-secret-value",
    oidc_external_id_claim="attributes.employee_no",
    oidc_auto_create_users=True,
    break_glass_enabled=True,
    break_glass_username="bg-user",
    break_glass_password="bg-password-value",
)
async def test_sso_on_with_discovery(app: FastAPI, api: AsUser, people: People) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json=discovery_document())

    use_idp(app, httpx.MockTransport(handler))
    # SSO sessions need SSO configured; dev login stays on next to it in tests.
    admin = await api(people.admin)

    response = await admin.get("/admin/sso")
    config = ok(response)
    again = ok(await admin.get("/admin/sso"))

    assert config["enabled"] is True
    assert config["issuer"] == ISSUER
    assert config["groups_claim"] == "groups"
    assert config["external_id_claim"] == "attributes.employee_no"
    assert config["external_id_kind"] == "employee_no"
    assert config["auto_create_users"] is True
    assert config["discovery"]["status"] == "ok"
    assert config["discovery"]["end_session_supported"] is True
    assert again["discovery"]["checked_at"] == config["discovery"]["checked_at"]  # cached
    assert calls == [f"{ISSUER}/.well-known/openid-configuration"]
    # Break-glass is off once SSO is configured.
    assert config["break_glass"] == {"enabled": True, "credentials_set": True, "available": False}
    assert not any(secret in response.text for secret in SECRETS)


@pytest.mark.parametrize(
    ("answer", "status"),
    [
        (httpx.Response(503), "unreachable"),
        (httpx.Response(200, text="<html>not json</html>"), "invalid"),
        (httpx.Response(200, json={"issuer": ISSUER}), "invalid"),
        (httpx.Response(200, json=discovery_document(ISSUER + "/")), "issuer_mismatch"),
    ],
)
@pytest.mark.settings(oidc_issuer=ISSUER)
async def test_discovery_problems_are_diagnosed_without_idp_text(
    app: FastAPI, api: AsUser, people: People, answer: httpx.Response, status: str
) -> None:
    use_idp(app, httpx.MockTransport(lambda request: answer))
    admin = await api(people.admin)

    config = ok(await admin.get("/admin/sso"))

    assert config["discovery"]["status"] == status
    assert config["discovery"]["end_session_supported"] is False
    assert "not json" not in str(config)


async def test_only_platform_admins_see_it(api: AsUser, people: People) -> None:
    bob = await api(people.bob)
    assert_problem(await bob.get("/admin/sso"), 403, "forbidden")
