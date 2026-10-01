"""A real Keycloak 26 for the identity integration tests (``test_keycloak.py``).

The dev realm (``dev/keycloak/realm-soundings.json``) is copied into a fresh
``keycloak/keycloak:26.0`` container with this test client's callback
(``http://testserver/*``) added to the ``soundings`` client: the shared realm file is
not touched. The issuer follows the URL used (``KC_HOSTNAME_STRICT=false``), and both
the tests (playing the browser) and the app (back channel) use the same one.

:class:`Browser` plays the user: it follows our ``GET /auth/login`` redirect to
Keycloak, submits the login form like ``dev/keycloak/check_login.py`` does, and hands
back the callback URL. :class:`KeycloakAdmin` changes group memberships through the
admin REST API, as the acceptance test needs.

Skipped (not failed) when Docker isn't reachable or the image can't be started, so
``make -C backend check`` stays usable without Docker; set
``SOUNDINGS_TEST_KEYCLOAK=0`` to skip it on purpose, or
``SOUNDINGS_TEST_KEYCLOAK_URL=http://localhost:<port>`` to use a Keycloak you already
run (dev realm, with ``http://testserver/*`` as a valid redirect URI).
"""

from __future__ import annotations

import html
import json
import os
import re
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from http.cookies import SimpleCookie
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from app.config import BACKEND_DIR

IMAGE = os.environ.get("SOUNDINGS_TEST_KEYCLOAK_IMAGE", "keycloak/keycloak:26.0")
REALM_FILE = BACKEND_DIR.parent / "dev" / "keycloak" / "realm-soundings.json"
REALM = "soundings"
CLIENT_ID = "soundings"
CLIENT_SECRET = "soundings-dev-secret"  # dev realm only
PASSWORD = "password"  # every dev realm user
TEST_ORIGIN = "http://testserver"
STARTUP_TIMEOUT = 180.0


def _realm_for_tests() -> bytes:
    realm: dict[str, Any] = json.loads(REALM_FILE.read_text(encoding="utf-8"))
    for client in realm["clients"]:
        if client["clientId"] == CLIENT_ID:
            client["redirectUris"] = [*client.get("redirectUris", []), f"{TEST_ORIGIN}/*"]
            attributes = client.setdefault("attributes", {})
            uris = attributes.get("post.logout.redirect.uris", "")
            attributes["post.logout.redirect.uris"] = "##".join(
                filter(None, [uris, f"{TEST_ORIGIN}/*"])
            )
    return json.dumps(realm).encode("utf-8")


@dataclass
class Keycloak:
    base_url: str

    @property
    def issuer(self) -> str:
        return f"{self.base_url}/realms/{REALM}"

    def admin(self) -> KeycloakAdmin:
        return KeycloakAdmin(self.base_url)


class KeycloakAdmin:
    """Just enough of the admin REST API: users' group memberships."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        token = httpx.post(
            f"{base_url}/realms/master/protocol/openid-connect/token",
            data={
                "grant_type": "password",
                "client_id": "admin-cli",
                "username": "admin",
                "password": "admin",
            },
            timeout=30,
        )
        token.raise_for_status()
        self.client = httpx.Client(
            base_url=f"{base_url}/admin/realms/{REALM}",
            headers={"Authorization": f"Bearer {token.json()['access_token']}"},
            timeout=30,
        )

    def user_id(self, username: str) -> str:
        response = self.client.get("/users", params={"username": username, "exact": "true"})
        response.raise_for_status()
        [user] = response.json()
        return str(user["id"])

    def group_id(self, path: str) -> str:
        response = self.client.get(f"/group-by-path{path}")
        response.raise_for_status()
        return str(response.json()["id"])

    def groups_of(self, username: str) -> set[str]:
        response = self.client.get(f"/users/{self.user_id(username)}/groups")
        response.raise_for_status()
        return {group["path"] for group in response.json()}

    def remove_from_group(self, username: str, path: str) -> None:
        user, group = self.user_id(username), self.group_id(path)
        self.client.delete(f"/users/{user}/groups/{group}").raise_for_status()

    def add_to_group(self, username: str, path: str) -> None:
        user, group = self.user_id(username), self.group_id(path)
        self.client.put(f"/users/{user}/groups/{group}").raise_for_status()

    def close(self) -> None:
        self.client.close()


class Browser:
    """The user's browser at Keycloak: its cookies and the login form.

    Keycloak marks its cookies Secure even over http; browsers treat localhost as a
    secure context and send them back, httpx's jar would not. So the cookies are kept
    here by hand (one host, all under ``/realms/``)."""

    def __init__(self) -> None:
        self.client = httpx.Client(timeout=30, follow_redirects=False, trust_env=False)
        self.cookies: dict[str, str] = {}

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        headers = {"Cookie": "; ".join(f"{k}={v}" for k, v in self.cookies.items())}
        response = self.client.request(method, url, headers=headers, **kwargs)
        for header in response.headers.get_list("set-cookie"):
            jar: SimpleCookie = SimpleCookie()
            jar.load(header)
            for name, morsel in jar.items():
                if morsel["max-age"] == "0" or not morsel.value:
                    self.cookies.pop(name, None)
                else:
                    self.cookies[name] = morsel.value
        return response

    def login(self, authorization_url: str, username: str, password: str = PASSWORD) -> str:
        """Open our authorization request at Keycloak and sign in: the callback URL.
        If Keycloak still has a session for this browser it redirects straight back."""
        page = self._request("GET", authorization_url)
        if page.status_code in (302, 303):
            return page.headers["location"]
        page.raise_for_status()
        form = re.search(r'id="kc-form-login"[^>]*action="([^"]+)"', page.text, re.S)
        assert form is not None, "Keycloak login form not found"
        submitted = self._request(
            "POST",
            html.unescape(form.group(1)),
            data={"username": username, "password": password},
        )
        assert submitted.status_code in (302, 303), f"{username}: sign-in failed"
        return submitted.headers["location"]

    def follow(self, url: str) -> httpx.Response:
        """Follow a redirect to Keycloak (e.g. the end-session request)."""
        return self._request("GET", url)

    def close(self) -> None:
        self.client.close()


def query_of(url: str) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}


def _wait_until_ready(base_url: str) -> None:
    deadline = time.monotonic() + STARTUP_TIMEOUT
    while time.monotonic() < deadline:
        try:
            response = httpx.get(
                f"{base_url}/realms/{REALM}/.well-known/openid-configuration", timeout=5
            )
            if response.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(1)
    raise TimeoutError("Keycloak did not become ready")


@pytest.fixture(scope="session")
def keycloak() -> Iterator[Keycloak]:
    if os.environ.get("SOUNDINGS_TEST_KEYCLOAK", "1") == "0":
        pytest.skip("Keycloak tests disabled (SOUNDINGS_TEST_KEYCLOAK=0)")
    if running := os.environ.get("SOUNDINGS_TEST_KEYCLOAK_URL"):
        # A Keycloak you already run with the dev realm and http://testserver/* allowed.
        _wait_until_ready(running.rstrip("/"))
        yield Keycloak(base_url=running.rstrip("/"))
        return
    os.environ.setdefault("RYUK_CONTAINER_IMAGE", "testcontainers/ryuk:0.11.0")
    from testcontainers.core.container import DockerContainer
    from testcontainers.core.docker_client import DockerClient

    try:
        DockerClient().client.ping()
    except Exception as exc:  # noqa: BLE001 - any failure means "no Docker here"
        pytest.skip(f"Keycloak tests need Docker ({type(exc).__name__}); not run")

    prefix = os.environ.get("SOUNDINGS_TEST_CONTAINER_PREFIX", "soundings-test-")
    container = (
        DockerContainer(IMAGE)
        .with_name(f"{prefix}kc-{uuid.uuid4().hex[:8]}")
        .with_command("start-dev --import-realm")
        .with_envs(
            KC_BOOTSTRAP_ADMIN_USERNAME="admin",
            KC_BOOTSTRAP_ADMIN_PASSWORD="admin",
            KC_HOSTNAME_STRICT="false",
            KC_LOG_LEVEL="warn",
        )
        .with_exposed_ports(8080)
        .with_copy_into_container(
            _realm_for_tests(), "/opt/keycloak/data/import/realm-soundings.json"
        )
    )
    try:
        container.start()
    except Exception as exc:  # noqa: BLE001 - e.g. the image can't be pulled offline
        pytest.skip(f"Keycloak container did not start ({type(exc).__name__}); not run")
    try:
        base_url = f"http://{container.get_container_host_ip()}:{container.get_exposed_port(8080)}"
        _wait_until_ready(base_url)
        yield Keycloak(base_url=base_url)
    finally:
        container.stop()
