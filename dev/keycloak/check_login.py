#!/usr/bin/env python3
"""Sign each dev user in to the local Keycloak and print the claims Soundings relies on.

Drives the real authorisation-code + PKCE (S256) flow with the standard library only,
the same way a browser would, then prints ``groups`` and ``employee_no`` from the ID
token and from userinfo. Also checks that a request without PKCE is refused.

    python3 dev/keycloak/check_login.py                        # http://localhost:8080
    python3 dev/keycloak/check_login.py http://localhost:18080 alice bob
"""

# ruff: noqa: T201, S310 - a CLI that prints; URLs are http(s) (checked in main)
from __future__ import annotations

import base64
import hashlib
import html
import http.cookiejar
import json
import re
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

REALM = "soundings"
CLIENT_ID = "soundings"
CLIENT_SECRET = "soundings-dev-secret"  # noqa: S105 - dev realm only
REDIRECT_URI = "http://localhost:8000/auth/callback"
USERS = ("alice", "bob", "carol", "dave", "erin")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_: Any, **__: Any) -> None:
        return None


class _LocalhostPolicy(http.cookiejar.DefaultCookiePolicy):
    """Browsers treat http://localhost as a secure context and send Secure cookies."""

    def return_ok_secure(self, cookie: http.cookiejar.Cookie, request: Any) -> bool:
        return True


def _opener() -> urllib.request.OpenerDirector:
    jar = http.cookiejar.CookieJar(policy=_LocalhostPolicy())
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(jar), _NoRedirect
    )


def _jwt_claims(token: str) -> dict[str, Any]:
    payload = token.split(".")[1]
    claims: dict[str, Any] = json.loads(
        base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
    )
    return claims


def sign_in(base: str, username: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (ID token claims, userinfo) for ``username`` / password ``password``."""
    opener = _opener()
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    query = urllib.parse.urlencode(
        {
            "client_id": CLIENT_ID,
            "response_type": "code",
            "scope": "openid profile email",
            "redirect_uri": REDIRECT_URI,
            "state": secrets.token_urlsafe(8),
            "nonce": secrets.token_urlsafe(8),
            "code_challenge": challenge.rstrip(b"=").decode(),
            "code_challenge_method": "S256",
        }
    )
    page = opener.open(f"{base}/protocol/openid-connect/auth?{query}").read().decode()
    form = re.search(r'id="kc-form-login"[^>]*action="([^"]+)"', page, re.S)
    if form is None:
        raise RuntimeError("login form not found")
    credentials = urllib.parse.urlencode({"username": username, "password": "password"}).encode()
    try:
        opener.open(html.unescape(form.group(1)), credentials)
        raise RuntimeError(f"{username}: sign-in did not redirect (wrong password?)")
    except urllib.error.HTTPError as redirect:
        location = redirect.headers.get("Location") or ""
    code = urllib.parse.parse_qs(urllib.parse.urlsplit(location).query)["code"][0]
    token_request = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        }
    ).encode()
    tokens = json.load(opener.open(f"{base}/protocol/openid-connect/token", token_request))
    userinfo_request = urllib.request.Request(
        f"{base}/protocol/openid-connect/userinfo",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    return _jwt_claims(tokens["id_token"]), json.load(opener.open(userinfo_request))


def pkce_is_required(base: str) -> bool:
    query = urllib.parse.urlencode(
        {
            "client_id": CLIENT_ID,
            "response_type": "code",
            "scope": "openid",
            "redirect_uri": REDIRECT_URI,
            "state": "x",
        }
    )
    try:
        _opener().open(f"{base}/protocol/openid-connect/auth?{query}")
    except urllib.error.HTTPError as redirect:
        return "error=invalid_request" in (redirect.headers.get("Location") or "")
    return False


def main() -> int:
    keycloak = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://localhost:8080"
    if urllib.parse.urlsplit(keycloak).scheme not in {"http", "https"}:
        raise SystemExit("usage: check_login.py [http(s)://keycloak-host:port] [user ...]")
    users = sys.argv[2:] or list(USERS)
    base = f"{keycloak}/realms/{REALM}"
    for username in users:
        claims, userinfo = sign_in(base, username)
        print(
            f"{username:6} {claims.get('email')!s:20} groups={claims.get('groups')} "
            f"employee_no={claims.get('employee_no')} "
            f"(userinfo: groups={userinfo.get('groups')} employee_no={userinfo.get('employee_no')})"
        )
    required = pkce_is_required(base)
    print(f"PKCE required: {required}")
    return 0 if required else 1


if __name__ == "__main__":
    raise SystemExit(main())
