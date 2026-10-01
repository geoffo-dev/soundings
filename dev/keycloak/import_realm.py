#!/usr/bin/env python3
"""Load the dev realm into a running Keycloak through the admin REST API.

For a Keycloak that can't read ``realm-soundings.json`` at startup (a CI service
container, which has no access to the repository): waits until Keycloak answers,
replaces the ``soundings`` realm with the file's, and adds ``--origin`` values as valid
(post-logout) redirect URIs ``<origin>/*`` of the ``soundings`` client. Standard
library only.

    python3 dev/keycloak/import_realm.py http://keycloak:8080 --origin http://testserver
"""

# ruff: noqa: T201, S310 - a CLI that prints; URLs are http(s) (checked in main)
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

REALM_FILE = Path(__file__).with_name("realm-soundings.json")
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _request(
    method: str, url: str, token: str | None = None, body: Any = None, form: bool = False
) -> Any:
    headers: dict[str, str] = {}
    data = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        if form:
            data = urllib.parse.urlencode(body).encode()
        else:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with _OPENER.open(request, timeout=30) as response:
        text = response.read().decode()
    return json.loads(text) if text else None


def _wait(base: str, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while True:
        try:
            _request("GET", f"{base}/realms/master/.well-known/openid-configuration")
            return
        except (urllib.error.URLError, OSError):
            if time.monotonic() > deadline:
                raise SystemExit(f"Keycloak at {base} did not answer in {seconds:.0f} s") from None
            time.sleep(2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("keycloak", help="Keycloak base URL, e.g. http://keycloak:8080")
    parser.add_argument("--origin", action="append", default=[], help="extra redirect origin")
    parser.add_argument("--admin", default="admin")
    parser.add_argument("--password", default="admin")
    parser.add_argument("--wait", type=float, default=180, help="seconds to wait for Keycloak")
    args = parser.parse_args()
    base = args.keycloak.rstrip("/")
    if urllib.parse.urlsplit(base).scheme not in {"http", "https"}:
        parser.error("the Keycloak URL must be http(s)")

    realm: dict[str, Any] = json.loads(REALM_FILE.read_text(encoding="utf-8"))
    uris = [f"{origin.rstrip('/')}/*" for origin in args.origin]
    for client in realm["clients"]:
        if client["clientId"] == "soundings":
            client["redirectUris"] = list(dict.fromkeys([*client["redirectUris"], *uris]))
            attributes = client.setdefault("attributes", {})
            current = [u for u in attributes.get("post.logout.redirect.uris", "").split("##") if u]
            attributes["post.logout.redirect.uris"] = "##".join(dict.fromkeys([*current, *uris]))

    _wait(base, args.wait)
    token = _request(
        "POST",
        f"{base}/realms/master/protocol/openid-connect/token",
        body={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": args.admin,
            "password": args.password,
        },
        form=True,
    )["access_token"]
    name = realm["realm"]
    try:
        _request("DELETE", f"{base}/admin/realms/{name}", token)
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
    _request("POST", f"{base}/admin/realms", token, realm)
    print(f"realm {name!r} loaded into {base} (extra redirect origins: {args.origin or 'none'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
