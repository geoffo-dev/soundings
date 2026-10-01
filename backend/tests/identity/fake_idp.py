"""A fake OIDC provider behind ``httpx.MockTransport``: discovery, JWKS, the token
endpoint (checking the code, redirect URI, PKCE verifier and client authentication)
and signed ID tokens. ``authorize()`` plays the browser at the IdP: it reads our
authorization request and returns the callback URL the IdP would redirect to."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
from joserfc import jwt
from joserfc.jwk import OctKey, RSAKey

ISSUER = "https://idp.example.com/realms/acme"
CLIENT_ID = "soundings"
CLIENT_SECRET = "s3cret:with/odd chars"


@dataclass
class Grant:
    claims: dict[str, Any]
    redirect_uri: str
    challenge: str
    nonce: str


@dataclass
class FakeIdp:
    issuer: str = ISSUER
    key: RSAKey = field(default_factory=lambda: RSAKey.generate_key(2048, auto_kid=True))
    grants: dict[str, Grant] = field(default_factory=dict)
    requests: list[httpx.Request] = field(default_factory=list)
    discovery: dict[str, Any] | None = None
    """Overrides the discovery document (None: the default)."""
    discovery_status: int = 200
    token_status: int = 200
    token_body: dict[str, Any] | None = None
    end_session: bool = True
    auth_methods: list[str] | None = None
    published_keys: list[RSAKey] | None = None
    """Keys in the JWKS (default: ``[key]``)."""
    id_token_override: dict[str, Any] = field(default_factory=dict)
    """Claims merged into every ID token (after the defaults)."""
    header_override: dict[str, Any] = field(default_factory=dict)
    signing_key: Any = None
    """Sign with this key instead (wrong key, HMAC with the client secret, ...)."""

    # --- Endpoints -----------------------------------------------------------------------
    def document(self) -> dict[str, Any]:
        if self.discovery is not None:
            return self.discovery
        document: dict[str, Any] = {
            "issuer": self.issuer,
            "authorization_endpoint": f"{self.issuer}/protocol/openid-connect/auth",
            "token_endpoint": f"{self.issuer}/protocol/openid-connect/token",
            "jwks_uri": f"{self.issuer}/protocol/openid-connect/certs",
            "id_token_signing_alg_values_supported": ["RS256"],
        }
        if self.end_session:
            document["end_session_endpoint"] = f"{self.issuer}/protocol/openid-connect/logout"
        if self.auth_methods is not None:
            document["token_endpoint_auth_methods_supported"] = self.auth_methods
        return document

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(self.discovery_status, json=self.document())
        if path.endswith("/certs"):
            keys = self.published_keys if self.published_keys is not None else [self.key]
            return httpx.Response(200, json={"keys": [key.as_dict(private=False) for key in keys]})
        if path.endswith("/token"):
            return self.token(request)
        return httpx.Response(404)

    def token(self, request: httpx.Request) -> httpx.Response:
        form = {key: values[0] for key, values in parse_qs(request.content.decode()).items()}
        if self.token_status != 200:
            return httpx.Response(self.token_status, json={"error": "invalid_grant"})
        if not self._client_authenticated(request, form):
            return httpx.Response(401, json={"error": "invalid_client"})
        grant = self.grants.pop(form.get("code", ""), None)
        if (
            grant is None
            or form.get("grant_type") != "authorization_code"
            or form.get("redirect_uri") != grant.redirect_uri
            or _challenge(form.get("code_verifier", "")) != grant.challenge
        ):
            return httpx.Response(400, json={"error": "invalid_grant"})
        if self.token_body is not None:
            return httpx.Response(200, json=self.token_body)
        return httpx.Response(
            200,
            json={
                "access_token": "opaque-access-token",
                "token_type": "Bearer",
                "id_token": self.id_token(grant.claims, nonce=grant.nonce),
            },
        )

    def _client_authenticated(self, request: httpx.Request, form: dict[str, str]) -> bool:
        header = request.headers.get("authorization", "")
        if header.startswith("Basic "):
            from urllib.parse import unquote_plus

            user, _, password = base64.b64decode(header[6:]).decode().partition(":")
            return (unquote_plus(user), unquote_plus(password)) == (CLIENT_ID, CLIENT_SECRET)
        return form.get("client_id") == CLIENT_ID and form.get("client_secret") in (
            CLIENT_SECRET,
            None,
        )

    # --- Tokens ----------------------------------------------------------------------------
    def id_token(self, claims: dict[str, Any], *, nonce: str) -> str:
        now = int(time.time())
        payload = {
            "iss": self.issuer,
            "aud": CLIENT_ID,
            "azp": CLIENT_ID,
            "iat": now,
            "exp": now + 300,
            "nonce": nonce,
            **claims,
            **self.id_token_override,
        }
        payload = {key: value for key, value in payload.items() if value is not _DROP}
        key = self.signing_key or self.key
        header = {"alg": "RS256", "kid": self.key.kid, **self.header_override}
        if header["alg"] == "none":
            encoded = _b64(json.dumps(header)) + "." + _b64(json.dumps(payload)) + "."
            return encoded
        algorithms = [header["alg"]]
        return jwt.encode(header, payload, key, algorithms=algorithms)

    def authorize(self, location: str, claims: dict[str, Any]) -> str:
        """The IdP's answer to our authorization request: the callback URL with a code."""
        parts = urlsplit(location)
        assert (
            f"{parts.scheme}://{parts.netloc}{parts.path}"
            == self.document()["authorization_endpoint"]
        )
        query = {key: values[0] for key, values in parse_qs(parts.query).items()}
        assert query["response_type"] == "code"
        assert query["client_id"] == CLIENT_ID
        assert query["code_challenge_method"] == "S256"
        code = secrets.token_urlsafe(16)
        self.grants[code] = Grant(
            claims=claims,
            redirect_uri=query["redirect_uri"],
            challenge=query["code_challenge"],
            nonce=query["nonce"],
        )
        return (
            query["redirect_uri"]
            + "?"
            + urlencode({"code": code, "state": query["state"], "iss": self.issuer})
        )

    def calls(self, suffix: str) -> int:
        return sum(1 for request in self.requests if request.url.path.endswith(suffix))


_DROP = object()
DROP: Any = _DROP
"""Use as a claim value in ``id_token_override`` to leave the claim out."""


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).rstrip(b"=").decode()


def _challenge(verifier: str) -> str:
    return (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )


def hmac_key(secret: str = CLIENT_SECRET) -> OctKey:
    return OctKey.import_key(secret.encode())
