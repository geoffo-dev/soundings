"""The SSO sign-in flow end to end against a fake IdP (contract-phase2 sections 3.1,
3.2, 3.9 and 4.2): authorization request, state and PKCE, the callback's every
failure, ID token validation, session creation and sign-out with the IdP."""

from __future__ import annotations

import base64
import hashlib
import logging
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi import FastAPI
from joserfc.jwk import RSAKey
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import auth_sso
from app.auth.login_attempt import LoginAttempt, open_attempt, seal_attempt
from app.auth.oidc import OidcProvider
from app.auth.sealing import unseal
from app.models.base import utcnow
from app.models.user import User, UserIdentity, UserSession
from tests.factories import make_user
from tests.identity.fake_idp import CLIENT_ID, CLIENT_SECRET, DROP, ISSUER, FakeIdp, hmac_key
from tests.identity.helpers import (
    add_external_id,
    add_to_group,
    audit_entries,
    make_group,
    memberships,
)

LOGIN = "/api/v1/auth/login"
CALLBACK = "/api/v1/auth/callback"
LOGOUT = "/api/v1/auth/logout/redirect"
ERIN = {"sub": "kc-erin", "email": "erin@example.com", "email_verified": True, "name": "Erin"}


@pytest.fixture
def settings_overrides() -> dict[str, Any]:
    return {
        "oidc_issuer": ISSUER,
        "oidc_client_id": CLIENT_ID,
        "oidc_client_secret": CLIENT_SECRET,
        "oidc_groups_claim": "groups",
        "oidc_external_id_claim": "employee_no",
        "dev_login_enabled": True,
    }


@pytest.fixture
def idp(app: FastAPI) -> FakeIdp:
    fake = FakeIdp()
    app.state.oidc_provider = OidcProvider(app.state.settings, transport=fake.transport())
    return fake


@pytest.fixture
async def erin(db_session: AsyncSession) -> User:
    return await make_user(db_session, "Erin Evans", email="erin@example.com")


async def start(client: httpx.AsyncClient, next_path: str | None = None) -> httpx.Response:
    params = {"next": next_path} if next_path is not None else None
    return await client.get(LOGIN, params=params)


async def sso_sign_in(
    client: httpx.AsyncClient, idp: FakeIdp, claims: dict[str, Any], next_path: str | None = None
) -> httpx.Response:
    started = await start(client, next_path)
    assert started.status_code == 302, started.text
    return await client.get(idp.authorize(started.headers["location"], claims))


def query_of(location: str) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(urlsplit(location).query).items()}


def set_cookie_headers(response: httpx.Response) -> dict[str, str]:
    return {header.split("=", 1)[0]: header for header in response.headers.get_list("set-cookie")}


def attempt_of(app: FastAPI, client: httpx.AsyncClient) -> LoginAttempt:
    """The sign-in attempt sealed in the client's ``soundings_oidc`` cookie."""
    attempt = open_attempt(app.state.settings, client.cookies.get("soundings_oidc"))
    assert attempt is not None
    return attempt


def stored_id_token(app: FastAPI, stored: str | None) -> str:
    """The ID token a session row keeps (sealed at rest: review L4)."""
    assert stored is not None
    raw = unseal(app.state.settings, "session-id-token", stored)
    assert raw is not None
    return raw.decode()


def plant_attempt(app: FastAPI, client: httpx.AsyncClient, **changes: Any) -> None:
    """Re-seal the client's attempt with ``changes`` (as only the server could)."""
    from dataclasses import replace

    changed = replace(attempt_of(app, client), **changes)
    client.cookies.set("soundings_oidc", seal_attempt(app.state.settings, changed))


# --- Sign-in methods (section 3.1) ------------------------------------------------------------
@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, {"sso": True, "dev_login": True, "break_glass": False}),
        (
            {"oidc_issuer": None, "dev_login_enabled": False},
            {"sso": False, "dev_login": False, "break_glass": False},
        ),
        (
            {
                "oidc_issuer": None,
                "break_glass_enabled": True,
                "break_glass_username": "a",
                "break_glass_password": "b",
            },
            {"sso": False, "dev_login": True, "break_glass": True},
        ),
        (
            {"break_glass_enabled": True, "break_glass_username": "a", "break_glass_password": "b"},
            {"sso": True, "dev_login": True, "break_glass": False},  # off once SSO is configured
        ),
        (
            {"oidc_issuer": None, "break_glass_enabled": True, "break_glass_username": "a"},
            {"sso": False, "dev_login": True, "break_glass": False},  # no password
        ),
    ],
)
async def test_auth_config(
    database_url: str,
    settings_overrides: dict[str, Any],
    overrides: dict[str, Any],
    expected: dict[str, bool],
) -> None:
    from app.main import create_app
    from tests.conftest import make_settings

    settings = make_settings(
        **{
            "environment": "test",
            "database_url": database_url,
            "base_urls": ["http://testserver"],
            **settings_overrides,
            **overrides,
        }
    )
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/api/v1/auth/config")

    assert response.status_code == 200
    assert response.json() == expected


# --- Starting the flow (section 3.2, GET /auth/login) -------------------------------------------
async def test_login_redirects_to_the_idp_with_pkce(
    app: FastAPI, client: httpx.AsyncClient, idp: FakeIdp
) -> None:
    response = await start(client, "/ideas/CUST-12")

    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith(f"{ISSUER}/protocol/openid-connect/auth?")
    query = query_of(location)
    assert query["response_type"] == "code"
    assert query["client_id"] == CLIENT_ID
    assert query["redirect_uri"] == "http://testserver/api/v1/auth/callback"
    assert query["scope"] == "openid profile email"
    assert query["code_challenge_method"] == "S256"
    assert len(query["state"]) >= 43  # 256 bits
    assert len(query["nonce"]) >= 43
    # The attempt is sealed into an HttpOnly cookie: the browser can't read the
    # verifier or nonce, and nothing is stored server-side.
    cookie = set_cookie_headers(response)["soundings_oidc"]
    for attribute in ("HttpOnly", "Max-Age=600", "Path=/", "SameSite=lax"):
        assert attribute in cookie
    value = client.cookies["soundings_oidc"]
    attempt = attempt_of(app, client)
    assert attempt.state == query["state"]
    assert attempt.nonce == query["nonce"]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(attempt.code_verifier.encode()).digest())
    assert challenge.rstrip(b"=").decode() == query["code_challenge"]
    assert attempt.code_verifier not in location
    raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    for secret in (attempt.code_verifier, attempt.nonce, attempt.state, "CUST-12"):
        assert secret not in value
        assert secret.encode() not in raw
    assert attempt.next_path == "/ideas/CUST-12"
    assert attempt.redirect_uri == query["redirect_uri"]
    remaining = (attempt.expires_at - utcnow()).total_seconds()
    assert 590 <= remaining <= 600


async def test_starting_sign_ins_stores_nothing_and_locks_no_one_out(
    app: FastAPI,
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    idp: FakeIdp,
    erin: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review H1: unfinished sign-ins from many addresses can't make SSO unavailable for
    anyone else (a global cap of live attempts could be filled from ~17 addresses)."""
    monkeypatch.setattr(auth_sso, "MAX_LIVE_ATTEMPTS", 100, raising=False)  # the old cap
    for n in range(4):  # 4 addresses x 60 starts (the per-address limit)
        transport = httpx.ASGITransport(app=app, client=(f"198.51.100.{n}", 1234))
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as other:
            for _ in range(60):
                assert (await start(other)).headers["location"].startswith(ISSUER)

    response = await sso_sign_in(client, idp, ERIN)

    assert response.headers["location"] == "/"
    assert (await client.get("/api/v1/auth/me")).json()["id"] == str(erin.id)
    tables = set(
        await db_session.scalars(
            text("SELECT tablename FROM pg_tables WHERE schemaname = current_schema()")
        )
    )
    assert "oidc_login_attempts" not in tables  # nothing to fill


@pytest.mark.parametrize(
    "tamper",
    ["flip_a_byte", "truncate", "garbage", "other_purpose", "other_secret_key", "plain_state"],
)
async def test_a_forged_or_changed_attempt_cookie_is_refused(
    app: FastAPI,
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    idp: FakeIdp,
    erin: User,
    tamper: str,
) -> None:
    from app.auth.sealing import seal
    from tests.conftest import make_settings

    started = await start(client)
    callback = idp.authorize(started.headers["location"], ERIN)
    value = client.cookies["soundings_oidc"]
    attempt = attempt_of(app, client)
    match tamper:
        case "flip_a_byte":
            raw = bytearray(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
            raw[20] ^= 1
            forged = base64.urlsafe_b64encode(bytes(raw)).rstrip(b"=").decode()
        case "truncate":
            forged = value[:-4]
        case "garbage":
            forged = "not-a-sealed-value"
        case "other_purpose":  # sealed by this server, but for something else
            forged = seal(app.state.settings, "session-id-token", b'{"s":"x"}')
        case "other_secret_key":
            other = make_settings(secret_key="another-secret-key-of-32-characters!")
            forged = seal_attempt(other, attempt)
        case "plain_state":  # the old cookie format (just the state)
            forged = attempt.state
    client.cookies.set("soundings_oidc", forged)

    response = await client.get(callback)

    assert response.headers["location"] == "/login?error=login_expired"
    assert (await client.get("/api/v1/auth/me")).status_code == 401
    assert await denials(db_session) == []  # no attempt to speak of


async def test_a_very_long_next_still_fits_in_the_cookie(
    app: FastAPI, client: httpx.AsyncClient, idp: FakeIdp
) -> None:
    from app.auth.login_attempt import MAX_COOKIE_VALUE

    ascii_next = "/" + "x" * 2047
    await start(client, ascii_next)
    assert attempt_of(app, client).next_path == ascii_next
    assert len(client.cookies["soundings_oidc"]) <= MAX_COOKIE_VALUE

    await start(client, "/" + "\u00e9" * 2047)  # 4 KB of UTF-8: too big for a cookie

    assert attempt_of(app, client).next_path == "/"
    assert len(client.cookies["soundings_oidc"]) <= MAX_COOKIE_VALUE


@pytest.mark.parametrize(
    ("next_path", "kept"),
    [
        ("/ideas/CUST-12", "/ideas/CUST-12"),
        ("/projects/cust?view=list&q=a%20b", "/projects/cust?view=list&q=a%20b"),
        ("/", "/"),
        (None, "/"),
        ("", "/"),
        ("//evil.example.com/x", "/"),
        ("/\\evil.example.com", "/"),
        ("/a\\b", "/"),
        ("https://evil.example.com/", "/"),
        ("ideas/CUST-12", "/"),
        ("/a b", "/"),
        ("/a\tb", "/"),
        ("/a\u2028b", "/"),
        ("/a\u0085b", "/"),
        ("/api/v1/auth/logout", "/"),
        ("/api", "/"),
        ("/api?x=1", "/"),
        pytest.param("/" + "x" * 2047, "/" + "x" * 2047, id="2048-characters"),
        pytest.param("/" + "x" * 2048, "/", id="2049-characters"),
        # Review N1: no dot segments (also percent-encoded) and no "//" in the path.
        ("/..//evil.example.com", "/"),
        ("/./ideas", "/"),
        ("/ideas/..", "/"),
        ("/%2e%2e//evil.example.com", "/"),
        ("/%2E./ideas", "/"),
        ("/.%2e/ideas", "/"),
        ("/ideas//CUST-1", "/"),
        ("/ideas/CUST-1?q=a//b#x//y", "/ideas/CUST-1?q=a//b#x//y"),  # query and fragment
        ("/ideas/v1.2/..x", "/ideas/v1.2/..x"),  # dots inside a segment are fine
    ],
)
async def test_next_must_be_a_same_origin_spa_path(
    app: FastAPI,
    client: httpx.AsyncClient,
    idp: FakeIdp,
    next_path: str | None,
    kept: str,
) -> None:
    response = await start(client, next_path)

    assert response.status_code == 302
    assert attempt_of(app, client).next_path == kept
    assert auth_sso.safe_next_path(next_path) == kept


@pytest.mark.settings(base_urls=["http://ideas.example.com", "http://testserver"])
async def test_each_configured_host_signs_in_on_itself(
    client: httpx.AsyncClient, idp: FakeIdp
) -> None:
    response = await start(client)

    assert (
        query_of(response.headers["location"])["redirect_uri"]
        == "http://testserver/api/v1/auth/callback"
    )


@pytest.mark.settings(base_urls=["http://ideas.example.com"])
async def test_an_unconfigured_host_goes_to_the_first_base_url_first(
    client: httpx.AsyncClient, idp: FakeIdp
) -> None:
    other = await client.get(
        LOGIN, params={"next": "/ideas/CUST-1"}, headers={"Host": "localhost:8000"}
    )

    assert other.status_code == 302
    assert (
        other.headers["location"]
        == "http://ideas.example.com/api/v1/auth/login?next=%2Fideas%2FCUST-1"
    )
    assert "set-cookie" not in other.headers


async def test_no_prompt_is_sent_by_default(client: httpx.AsyncClient, idp: FakeIdp) -> None:
    response = await start(client)

    assert response.status_code == 302
    query = query_of(response.headers["location"])
    assert "prompt" not in query
    assert "max_age" not in query


@pytest.mark.parametrize("prompt", ["login", "select_account"])
async def test_prompt_is_passed_to_the_idp(
    client: httpx.AsyncClient, idp: FakeIdp, prompt: str
) -> None:
    """Review M3, "Use a different account": the IdP shows its account picker or
    sign-in form instead of reusing the account it already has a session for."""
    response = await client.get(LOGIN, params={"prompt": prompt, "next": "/ideas/CUST-1"})

    assert response.status_code == 302
    query = query_of(response.headers["location"])
    assert query["prompt"] == prompt
    # max_age=0 asks for a fresh sign-in where the prompt value is ignored (Keycloak 26
    # ignores select_account and would reuse the refused account's session).
    assert query["max_age"] == "0"
    assert query["code_challenge_method"] == "S256"


@pytest.mark.parametrize(
    "prompt",
    [
        "",
        "none",
        "consent",
        "SELECT_ACCOUNT",
        "login select_account",
        pytest.param("x" * 3000, id="overlong"),
    ],
)
async def test_any_other_prompt_is_a_422(
    client: httpx.AsyncClient, idp: FakeIdp, prompt: str
) -> None:
    response = await client.get(LOGIN, params={"prompt": prompt})

    assert response.status_code == 422, response.text
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "validation_error"
    assert "soundings_oidc" not in set_cookie_headers(response)


@pytest.mark.settings(base_urls=["http://ideas.example.com"])
async def test_an_unconfigured_host_keeps_the_prompt(
    client: httpx.AsyncClient, idp: FakeIdp
) -> None:
    other = await client.get(
        LOGIN,
        params={"next": "/ideas/CUST-1", "prompt": "select_account"},
        headers={"Host": "localhost:8000"},
    )

    assert other.status_code == 302
    assert other.headers["location"] == (
        "http://ideas.example.com/api/v1/auth/login?next=%2Fideas%2FCUST-1&prompt=select_account"
    )


@pytest.mark.settings(oidc_issuer=None)
async def test_login_without_sso_configured(client: httpx.AsyncClient) -> None:
    response = await start(client)

    assert response.status_code == 302
    assert response.headers["location"] == "/login?error=sso_unavailable"


@pytest.mark.parametrize(
    ("change", "status"),
    [
        ({"discovery_status": 500}, "unreachable"),
        ({"discovery": {"issuer": ISSUER}}, "invalid"),
        ({"discovery": ["not", "an", "object"]}, "invalid"),
        ({"issuer": ISSUER + "/"}, "issuer_mismatch"),
    ],
)
async def test_unusable_discovery_is_sso_unavailable_and_cached_briefly(
    app: FastAPI, client: httpx.AsyncClient, idp: FakeIdp, change: dict[str, Any], status: str
) -> None:
    for name, value in change.items():
        setattr(idp, name, value)
    if "issuer" in change:  # the document names another issuer than the configured one
        idp.discovery = {**FakeIdp().document(), "issuer": change["issuer"]}

    first = await start(client)
    second = await start(client)

    for response in (first, second):
        assert response.status_code == 302
        assert response.headers["location"] == "/login?error=sso_unavailable"
    assert idp.calls("openid-configuration") == 1  # the failure is cached (30 s)
    discovery = await app.state.oidc_provider.discovery_status()
    assert discovery.status == status


async def test_unreachable_idp(app: FastAPI, client: httpx.AsyncClient) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    app.state.oidc_provider = OidcProvider(
        app.state.settings, transport=httpx.MockTransport(refuse)
    )

    response = await start(client)

    assert response.headers["location"] == "/login?error=sso_unavailable"
    assert (await app.state.oidc_provider.discovery_status()).status == "unreachable"


async def test_discovery_is_cached(client: httpx.AsyncClient, idp: FakeIdp) -> None:
    for _ in range(3):
        await start(client)

    assert idp.calls("openid-configuration") == 1


@pytest.mark.parametrize(
    "endpoint",
    ["authorization_endpoint", "token_endpoint", "jwks_uri", "end_session_endpoint"],
)
async def test_production_needs_https_idp_endpoints(endpoint: str) -> None:
    """Review L5: the issuer is https, but discovery could still point the token
    request (client secret, code) or the JWKS at plain http."""
    from tests.conftest import make_settings

    https = {"base_urls": ["https://ideas.example.com"], "oidc_issuer": ISSUER}
    production = make_settings(
        environment="production", secret_key="k" * 32, dev_login_enabled=False, **https
    )
    fake = FakeIdp()
    fake.discovery = {**fake.document(), endpoint: "http://idp.example.com/plain"}

    found = await OidcProvider(production, transport=fake.transport()).discover()
    outside_production = await OidcProvider(
        make_settings(**https), transport=fake.transport()
    ).discover()

    assert (found.status, found.metadata) == ("invalid", None)
    assert outside_production.status == "ok"


async def test_signing_keys_are_refreshed_hourly(app: FastAPI, client: httpx.AsyncClient) -> None:
    """Review L1: a key the IdP has withdrawn stops working within an hour, even when
    no token with an unknown kid ever arrives."""
    now = [1000.0]
    idp = FakeIdp()
    app.state.oidc_provider = OidcProvider(
        app.state.settings, transport=idp.transport(), clock=lambda: now[0]
    )
    erin = {**ERIN, "sub": "kc-erin-2"}
    await sso_sign_in(client, idp, erin)  # caches the key set
    idp.published_keys = [RSAKey.generate_key(2048, auto_kid=True)]  # the old key is withdrawn

    now[0] += 3000  # within the hour: the cached keys still verify
    within = await sso_sign_in(client, idp, erin)
    now[0] += 700  # past the hour: fetched again, and the withdrawn key is gone
    after = await sso_sign_in(client, idp, erin)

    assert within.headers["location"] == "/login?error=no_account"  # verified, then matched
    assert after.headers["location"] == "/login?error=sso_failed"
    assert idp.calls("/certs") >= 2


async def test_login_starts_are_throttled_per_client(
    app: FastAPI, client: httpx.AsyncClient, idp: FakeIdp
) -> None:
    statuses = [(await start(client)).headers["location"] for _ in range(61)]

    assert all(location.startswith(ISSUER) for location in statuses[:60])
    assert statuses[60] == "/login?error=too_many_attempts"


# --- The callback: success --------------------------------------------------------------------
async def test_sso_sign_in(
    app: FastAPI, client: httpx.AsyncClient, db_session: AsyncSession, idp: FakeIdp, erin: User
) -> None:
    response = await sso_sign_in(client, idp, ERIN, next_path="/ideas/CUST-12")

    assert response.status_code == 302, response.text
    assert response.headers["location"] == "/ideas/CUST-12"
    cookies = set_cookie_headers(response)
    assert "HttpOnly" in cookies["soundings_session"]
    assert "Max-Age=0" in cookies["soundings_oidc"]  # cleared
    me = await client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["id"] == str(erin.id)
    assert me.json()["auth_method"] == "sso"
    [identity] = list(await db_session.scalars(select(UserIdentity)))
    assert (identity.user_id, identity.issuer, identity.subject) == (erin.id, ISSUER, "kc-erin")
    assert identity.last_login_at is not None
    [session] = list(await db_session.scalars(select(UserSession)))
    assert session.auth_method == "sso"
    assert session.id_token is not None
    assert stored_id_token(app, session.id_token).count(".") == 2
    [signed_in] = await audit_entries(db_session, "session.sign_in")
    assert signed_in.actor_id == erin.id
    assert signed_in.details == {
        "method": "sso",
        "session_id": str(session.id),
        "identity_id": str(identity.id),
        "matched_by": "email",
        "auth_method": "sso",
    }


async def test_sign_in_rotates_an_existing_session(
    client: httpx.AsyncClient, db_session: AsyncSession, idp: FakeIdp, erin: User
) -> None:
    bob = await make_user(db_session, "Bob")
    await client.post("/api/v1/auth/dev/login", json={"user_id": str(bob.id)})
    before = client.cookies["soundings_session"]

    await sso_sign_in(client, idp, ERIN)

    assert client.cookies["soundings_session"] != before
    owners = list(await db_session.scalars(select(UserSession.user_id)))
    assert owners == [erin.id]


async def test_sign_in_syncs_groups(
    client: httpx.AsyncClient, db_session: AsyncSession, idp: FakeIdp, erin: User
) -> None:
    viewers = await make_group(db_session, "Viewers", idp_values=["/viewers"])
    old = await make_group(db_session, "Old", idp_values=["/old"])
    await add_to_group(db_session, old, erin, manual=False, synced=True)

    await sso_sign_in(client, idp, {**ERIN, "groups": ["/viewers"]})

    assert await memberships(db_session, erin) == {viewers.id: (False, True)}
    [synced] = await audit_entries(db_session, "user.groups_sync")
    assert synced.details["added_group_ids"] == [str(viewers.id)]
    assert synced.details["removed_group_ids"] == [str(old.id)]


async def test_external_id_sign_in(
    client: httpx.AsyncClient, db_session: AsyncSession, idp: FakeIdp
) -> None:
    carol = await make_user(db_session, "Carol", email="carol@example.com")
    await add_external_id(db_session, carol, "employee_no", "E1003")

    response = await sso_sign_in(client, idp, {"sub": "kc-carol", "employee_no": "E1003"})

    assert response.headers["location"] == "/"
    assert (await client.get("/api/v1/auth/me")).json()["id"] == str(carol.id)
    [signed_in] = await audit_entries(db_session, "session.sign_in")
    assert signed_in.details["matched_by"] == "external_id"


async def test_big_id_tokens_are_not_stored(
    client: httpx.AsyncClient, db_session: AsyncSession, idp: FakeIdp, erin: User
) -> None:
    groups = [f"/a-rather-long-group-name/number-{n}" for n in range(120)]

    response = await sso_sign_in(client, idp, {**ERIN, "groups": groups})

    assert response.status_code == 302
    assert (await client.get("/api/v1/auth/me")).status_code == 200
    assert await db_session.scalar(select(UserSession.id_token)) is None


async def test_client_secret_post_when_basic_is_not_supported(
    client: httpx.AsyncClient, idp: FakeIdp, erin: User
) -> None:
    idp.auth_methods = ["client_secret_post"]

    await sso_sign_in(client, idp, ERIN)

    [token_request] = [r for r in idp.requests if r.url.path.endswith("/token")]
    assert "authorization" not in token_request.headers
    assert b"client_secret=" in token_request.content
    assert (await client.get("/api/v1/auth/me")).status_code == 200


async def test_client_secret_basic_by_default(
    client: httpx.AsyncClient, idp: FakeIdp, erin: User
) -> None:
    await sso_sign_in(client, idp, ERIN)

    [token_request] = [r for r in idp.requests if r.url.path.endswith("/token")]
    assert token_request.headers["authorization"].startswith("Basic ")
    assert b"client_secret" not in token_request.content
    assert b"code_verifier=" in token_request.content


@pytest.mark.settings(oidc_client_secret=None)
async def test_public_client_sends_only_its_id(
    client: httpx.AsyncClient, idp: FakeIdp, erin: User
) -> None:
    await sso_sign_in(client, idp, ERIN)

    [token_request] = [r for r in idp.requests if r.url.path.endswith("/token")]
    assert "authorization" not in token_request.headers
    assert b"client_id=soundings" in token_request.content
    assert (await client.get("/api/v1/auth/me")).status_code == 200


async def test_rotated_signing_key_is_fetched_once(
    client: httpx.AsyncClient, idp: FakeIdp, erin: User
) -> None:
    await sso_sign_in(client, idp, ERIN)  # caches the JWKS
    idp.key = RSAKey.generate_key(2048, auto_kid=True)  # the IdP rotates its key

    response = await sso_sign_in(client, idp, ERIN)

    assert response.headers["location"] == "/"
    assert idp.calls("/certs") == 2


# --- The callback: failures ------------------------------------------------------------------
async def callback_after_start(
    client: httpx.AsyncClient, idp: FakeIdp, next_path: str | None = None, **params: str
) -> httpx.Response:
    started = await start(client, next_path)
    state = query_of(started.headers["location"])["state"]
    return await client.get(CALLBACK, params={"state": state, **params})


async def denials(db: AsyncSession) -> list[tuple[str, Any, Any]]:
    return [
        (entry.details["reason"], entry.actor_id, entry.target_id)
        for entry in await audit_entries(db, "session.sign_in_denied")
    ]


async def test_callback_without_sso(
    app: FastAPI, client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    app.state.settings = app.state.settings.model_copy(update={"oidc_issuer": None})

    response = await client.get(CALLBACK, params={"code": "x", "state": "y"})

    assert response.headers["location"] == "/login?error=sso_unavailable"
    assert await denials(db_session) == []


@pytest.mark.parametrize("problem", ["no_state", "no_cookie", "other_cookie", "unknown_state"])
async def test_state_must_match_the_cookie_and_an_attempt(
    client: httpx.AsyncClient, db_session: AsyncSession, idp: FakeIdp, problem: str
) -> None:
    started = await start(client)
    state = query_of(started.headers["location"])["state"]
    params = {"code": "x", "state": state}
    match problem:
        case "no_state":
            del params["state"]
        case "no_cookie":
            client.cookies.clear()
        case "other_cookie":
            client.cookies.set("soundings_oidc", "someone-elses-state")
        case "unknown_state":
            client.cookies.set("soundings_oidc", "made-up")
            params["state"] = "made-up"

    response = await client.get(CALLBACK, params=params)

    assert response.status_code == 302
    assert response.headers["location"] == "/login?error=login_expired"
    assert "Max-Age=0" in set_cookie_headers(response)["soundings_oidc"]
    assert await denials(db_session) == []  # no attempt to speak of


async def test_a_callback_url_works_only_once(
    client: httpx.AsyncClient, db_session: AsyncSession, idp: FakeIdp, erin: User
) -> None:
    started = await start(client)
    callback = idp.authorize(started.headers["location"], ERIN)
    cookie = client.cookies["soundings_oidc"]

    first = await client.get(callback)
    after_first = client.cookies["soundings_session"]
    replay_without_cookie = await client.get(callback)  # the callback cleared it
    client.cookies.set("soundings_oidc", cookie)  # someone kept a copy
    replay = await client.get(callback)

    assert first.headers["location"] == "/"
    assert "Max-Age=0" in set_cookie_headers(first)["soundings_oidc"]
    assert replay_without_cookie.headers["location"] == "/login?error=login_expired"
    # The IdP accepts each code once, so a kept cookie doesn't help either.
    assert replay.headers["location"] == "/login?error=sso_failed"
    assert [reason for reason, *_ in await denials(db_session)] == ["sso_failed"]
    assert client.cookies["soundings_session"] == after_first  # no second session
    assert await db_session.scalar(select(func.count()).select_from(UserSession)) == 1


async def test_expired_attempt(
    app: FastAPI, client: httpx.AsyncClient, db_session: AsyncSession, idp: FakeIdp
) -> None:
    started = await start(client, "/ideas/CUST-1")
    plant_attempt(app, client, expires_at=utcnow())  # a browser that kept the cookie
    state = query_of(started.headers["location"])["state"]

    response = await client.get(CALLBACK, params={"code": "x", "state": state})

    assert response.headers["location"] == "/login?error=login_expired&next=%2Fideas%2FCUST-1"
    assert await denials(db_session) == [("login_expired", None, None)]
    assert "Max-Age=0" in set_cookie_headers(response)["soundings_oidc"]


@pytest.mark.parametrize(
    ("params", "code", "reason"),
    [
        (
            {"error": "access_denied", "error_description": "User said no"},
            "login_cancelled",
            "login_cancelled",
        ),
        ({"error": "server_error", "error_description": "x" * 5000}, "sso_failed", "sso_failed"),
        ({}, "sso_failed", "sso_failed"),  # no code
        ({"code": "x", "iss": "https://evil.example.com"}, "sso_failed", "sso_failed"),
        ({"code": "not-issued-by-the-idp"}, "sso_failed", "sso_failed"),
        ({"code": "y" * 10_000}, "sso_failed", "sso_failed"),
    ],
)
async def test_idp_errors(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    idp: FakeIdp,
    caplog: pytest.LogCaptureFixture,
    params: dict[str, str],
    code: str,
    reason: str,
) -> None:
    caplog.set_level(logging.DEBUG)

    response = await callback_after_start(client, idp, **params)

    assert response.status_code == 302
    assert response.headers["location"] == f"/login?error={code}"
    entries = await audit_entries(db_session, "session.sign_in_denied")
    assert [(e.details["reason"], e.details["method"], e.actor_id) for e in entries] == [
        (reason, "sso", None)
    ]
    assert entries[0].details["issuer"] == ISSUER
    assert "User said no" not in caplog.text  # IdP text is never logged
    assert "x" * 100 not in caplog.text
    assert "soundings_session" not in response.headers.get("set-cookie", "")


def _bad_token(change: str, idp: FakeIdp) -> None:
    match change:
        case "wrong_key":
            idp.signing_key = RSAKey.generate_key(2048)
        case "hmac":
            idp.signing_key = hmac_key()
            idp.header_override = {"alg": "HS256"}
        case "none":
            idp.header_override = {"alg": "none"}
        case "unknown_kid":
            idp.header_override = {"kid": "not-a-known-key"}
        case "issuer":
            idp.id_token_override = {"iss": "https://evil.example.com"}
        case "audience":
            idp.id_token_override = {"aud": "another-client", "azp": "another-client"}
        case "audiences_without_azp":
            idp.id_token_override = {"aud": [CLIENT_ID, "other"], "azp": DROP}
        case "azp":
            idp.id_token_override = {"azp": "other"}
        case "expired":
            idp.id_token_override = {"exp": 1_000_000_000}
        case "future_iat":
            idp.id_token_override = {"iat": 4_000_000_000}
        case "no_exp":
            idp.id_token_override = {"exp": DROP}
        case "nonce":
            idp.id_token_override = {"nonce": "replayed"}
        case "no_nonce":
            idp.id_token_override = {"nonce": DROP}
        case "no_sub":
            idp.id_token_override = {"sub": DROP}
        case "empty_sub":
            idp.id_token_override = {"sub": ""}
        case "long_sub":
            idp.id_token_override = {"sub": "s" * 256}
        case "no_id_token":
            idp.token_body = {"access_token": "x", "token_type": "Bearer"}
        case "token_error":
            idp.token_status = 400
        case _:
            raise AssertionError(change)


BAD_TOKENS = [
    "wrong_key", "hmac", "none", "unknown_kid", "issuer", "audience", "audiences_without_azp",
    "azp", "expired", "future_iat", "no_exp", "nonce", "no_nonce", "no_sub", "empty_sub",
    "long_sub", "no_id_token", "token_error",
]  # fmt: skip


@pytest.mark.parametrize("change", BAD_TOKENS)
async def test_invalid_id_tokens_are_refused(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    idp: FakeIdp,
    erin: User,
    caplog: pytest.LogCaptureFixture,
    change: str,
) -> None:
    _bad_token(change, idp)

    response = await sso_sign_in(client, idp, ERIN, next_path="/ideas/CUST-3")

    assert response.headers["location"] == "/login?error=sso_failed&next=%2Fideas%2FCUST-3"
    assert (await client.get("/api/v1/auth/me")).status_code == 401
    assert await db_session.scalar(select(func.count()).select_from(UserIdentity)) == 0
    assert [reason for reason, *_ in await denials(db_session)] == ["sso_failed"]
    assert "sso sign-in failed" in caplog.text


async def test_clock_skew_within_a_minute_is_accepted(
    client: httpx.AsyncClient, idp: FakeIdp, erin: User
) -> None:
    import time

    idp.id_token_override = {"iat": int(time.time()) + 50, "exp": int(time.time()) - 50}

    response = await sso_sign_in(client, idp, ERIN)

    assert response.headers["location"] == "/"


async def test_group_overage_is_refused_before_matching(
    client: httpx.AsyncClient, db_session: AsyncSession, idp: FakeIdp, erin: User
) -> None:
    tools = await make_group(db_session, "Tools", idp_values=["/tools"])
    await add_to_group(db_session, tools, erin, manual=False, synced=True)
    claims = {**ERIN, "_claim_names": {"groups": "src1"}, "_claim_sources": {"src1": {}}}

    response = await sso_sign_in(client, idp, claims)

    assert response.headers["location"] == "/login?error=sso_failed"
    assert await denials(db_session) == [("groups_overage", None, None)]
    [entry] = await audit_entries(db_session, "session.sign_in_denied")
    assert entry.details["subject"] == "kc-erin"
    assert await memberships(db_session, erin) == {tools.id: (False, True)}  # untouched
    assert await db_session.scalar(select(func.count()).select_from(UserIdentity)) == 0


@pytest.mark.parametrize(
    ("claims", "code", "reason", "target"),
    [
        (
            {"sub": "kc-x", "email": "nobody@example.com", "email_verified": True},
            "no_account",
            "no_match",
            False,
        ),
        ({**ERIN, "email_verified": False}, "no_account", "email_not_verified", False),
    ],
)
async def test_matching_denials(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    idp: FakeIdp,
    erin: User,
    claims: dict[str, Any],
    code: str,
    reason: str,
    target: bool,
) -> None:
    response = await sso_sign_in(client, idp, claims, next_path="/work")

    assert response.headers["location"] == f"/login?error={code}&next=%2Fwork"
    entries = await audit_entries(db_session, "session.sign_in_denied")
    assert [(e.details["reason"], e.actor_id) for e in entries] == [(reason, None)]
    assert entries[0].details == {
        "method": "sso",
        "reason": reason,
        "issuer": ISSUER,
        "subject": claims["sub"],
    }


async def test_deactivated_user_is_refused(
    client: httpx.AsyncClient, db_session: AsyncSession, idp: FakeIdp, erin: User
) -> None:
    erin.is_active = False
    await db_session.commit()

    response = await sso_sign_in(client, idp, ERIN)

    assert response.headers["location"] == "/login?error=account_disabled"
    assert await denials(db_session) == [("account_disabled", None, erin.id)]
    assert await db_session.scalar(select(func.count()).select_from(UserSession)) == 0


async def test_nothing_personal_reaches_the_audit_log_or_logs(
    app: FastAPI,
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    idp: FakeIdp,
    erin: User,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    await sso_sign_in(client, idp, {**ERIN, "groups": ["/secret-group"]})
    await sso_sign_in(
        client, idp, {"sub": "kc-y", "email": "stranger@example.com", "email_verified": True}
    )
    token = stored_id_token(app, await db_session.scalar(select(UserSession.id_token)))

    rendered = str([entry.details for entry in await audit_entries(db_session)])
    for secret in (
        "erin@example.com",
        "stranger@example.com",
        "secret-group",
        token,
        CLIENT_SECRET,
    ):
        assert secret not in rendered
        assert secret not in caplog.text


# --- Sign-out with the IdP (section 3.9) --------------------------------------------------------
async def test_logout_redirect_ends_the_sso_session_at_the_idp(
    app: FastAPI, client: httpx.AsyncClient, db_session: AsyncSession, idp: FakeIdp, erin: User
) -> None:
    await sso_sign_in(client, idp, ERIN)
    id_token = stored_id_token(app, await db_session.scalar(select(UserSession.id_token)))

    response = await client.post(
        LOGOUT, headers={"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"}
    )

    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith(f"{ISSUER}/protocol/openid-connect/logout?")
    assert query_of(location) == {
        "client_id": CLIENT_ID,
        "post_logout_redirect_uri": "http://testserver/login?signed_out=1",
        "id_token_hint": id_token,
    }
    assert await db_session.scalar(select(func.count()).select_from(UserSession)) == 0
    cookies = set_cookie_headers(response)
    assert "Max-Age=0" in cookies["soundings_session"]
    assert "Max-Age=0" in cookies["soundings_csrf"]
    [signed_out] = await audit_entries(db_session, "session.sign_out")
    assert signed_out.details["method"] == "sso"
    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_logout_redirect_without_a_stored_id_token(
    client: httpx.AsyncClient, db_session: AsyncSession, idp: FakeIdp, erin: User
) -> None:
    await sso_sign_in(client, idp, ERIN)
    await db_session.execute(update(UserSession).values(id_token=None))
    await db_session.commit()

    response = await client.post(LOGOUT)

    assert set(query_of(response.headers["location"])) == {"client_id", "post_logout_redirect_uri"}


async def test_the_id_token_is_sealed_at_rest(
    app: FastAPI, client: httpx.AsyncClient, db_session: AsyncSession, idp: FakeIdp, erin: User
) -> None:
    """Review L4: the stored ID token (email, name, groups, employee_no) is unreadable
    without the secret key; sign-out still sends it as id_token_hint."""
    await sso_sign_in(client, idp, {**ERIN, "groups": ["/tools"], "employee_no": "E1005"})
    stored = await db_session.scalar(select(UserSession.id_token))
    assert stored is not None
    id_token = stored_id_token(app, stored)

    payload = id_token.split(".")[1]
    assert payload not in stored
    assert "." not in stored
    raw = base64.urlsafe_b64decode(stored + "=" * (-len(stored) % 4))
    for secret in (b"erin@example.com", b"E1005", b"/tools", payload.encode()):
        assert secret not in raw


async def test_a_legacy_plaintext_id_token_is_not_sent(
    client: httpx.AsyncClient, db_session: AsyncSession, idp: FakeIdp, erin: User
) -> None:
    await sso_sign_in(client, idp, ERIN)
    await db_session.execute(update(UserSession).values(id_token="aaa.bbb.ccc"))
    await db_session.commit()

    response = await client.post(LOGOUT)

    assert set(query_of(response.headers["location"])) == {"client_id", "post_logout_redirect_uri"}


async def test_logout_redirect_when_the_idp_has_no_end_session_endpoint(
    client: httpx.AsyncClient, idp: FakeIdp, erin: User
) -> None:
    idp.end_session = False
    await sso_sign_in(client, idp, ERIN)

    response = await client.post(LOGOUT)

    assert response.headers["location"] == "/login?signed_out=1"


@pytest.mark.parametrize("session", ["dev_login", "none"])
async def test_logout_redirect_for_other_sessions(
    client: httpx.AsyncClient, db_session: AsyncSession, idp: FakeIdp, session: str
) -> None:
    if session == "dev_login":
        ada = await make_user(db_session)
        await client.post("/api/v1/auth/dev/login", json={"user_id": str(ada.id)})

    response = await client.post(LOGOUT)

    assert response.status_code == 303
    assert response.headers["location"] == "/login?signed_out=1"
    assert await db_session.scalar(select(func.count()).select_from(UserSession)) == 0


@pytest.mark.parametrize(
    "headers",
    [
        {"Sec-Fetch-Site": "cross-site"},
        {"Sec-Fetch-Site": "same-site"},  # a sibling subdomain
        {"Origin": "http://evil.testserver"},
        {"Origin": "null"},
    ],
)
async def test_cross_origin_sign_out_ends_nothing(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    idp: FakeIdp,
    erin: User,
    headers: dict[str, str],
) -> None:
    await sso_sign_in(client, idp, ERIN)

    response = await client.post(LOGOUT, headers=headers)

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert "set-cookie" not in response.headers
    assert await db_session.scalar(select(func.count()).select_from(UserSession)) == 1


@pytest.mark.settings(oidc_issuer=None)
async def test_sso_sessions_end_when_sso_is_switched_off(
    app: FastAPI, client: httpx.AsyncClient, db_session: AsyncSession, erin: User
) -> None:
    from app.models.enums import AuthMethod
    from app.services import sessions

    started = await sessions.start_session(
        db_session, erin, settings=app.state.settings, auth_method=AuthMethod.SSO
    )
    await db_session.commit()

    response = await client.get(
        "/api/v1/auth/me", headers={"Cookie": f"soundings_session={started.token}"}
    )

    assert response.status_code == 401


def test_callback_route_is_the_registered_redirect_uri() -> None:
    from app.config import OIDC_CALLBACK_PATH

    paths = {route.path for route in auth_sso.router.routes}  # type: ignore[attr-defined]
    assert OIDC_CALLBACK_PATH.removeprefix("/api/v1") in paths
