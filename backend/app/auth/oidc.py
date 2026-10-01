"""The OIDC relying party: provider metadata, JWKS, the token request and ID token
validation (contract-phase2 section 3.2). One provider per instance
(``SOUNDINGS_OIDC_*``).

Deliberately small: HTTP with ``httpx`` (timeouts, no redirects, proxy and CA
settings from the environment) and signatures with ``joserfc`` (what Authlib 1.8 uses
underneath). Authlib's Starlette client would need a cookie-backed
``request.session``; here the login attempt is sealed into the ``soundings_oidc``
cookie (:mod:`app.auth.login_attempt`).

* :meth:`OidcProvider.discover`: ``<issuer>/.well-known/openid-configuration``, cached
  for an hour when usable and for 30 seconds when not (an unreachable IdP is neither
  hammered nor slow for every request). Its ``issuer`` must equal
  ``SOUNDINGS_OIDC_ISSUER`` exactly, and in production every endpoint must be https
  (the token request carries the client secret and the code). The same result feeds
  ``GET /admin/sso`` (:meth:`OidcProvider.discovery_status`).
* :meth:`OidcProvider.exchange_code`: the token request (10 s timeout), with the PKCE
  verifier and ``client_secret_basic`` (``client_secret_post`` when the provider only
  supports that; a public client sends just ``client_id``).
* :meth:`OidcProvider.validate_id_token`: signature against the JWKS (asymmetric
  algorithms only; fetched again every hour, so a key the IdP withdrew stops working,
  and once for an unknown ``kid``), ``iss``, ``aud``/``azp``, ``exp``/``iat`` (60 s
  leeway), ``nonce`` and ``sub``.

Nothing here logs tokens, codes, claims or IdP error text: failures carry a fixed
reason for the server log only.
"""

from __future__ import annotations

import asyncio
import base64
import hmac
import json
import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal
from urllib.parse import quote_plus, urlsplit

import httpx
from joserfc import jws
from joserfc.errors import InvalidKeyIdError, JoseError
from joserfc.jwk import KeySet

from app.config import Settings
from app.models.base import utcnow
from app.schemas.sso import SsoDiscovery

__all__ = [
    "ALLOWED_ALGORITHMS",
    "CLOCK_LEEWAY",
    "Discovery",
    "OidcError",
    "OidcProvider",
    "ProviderMetadata",
    "get_provider",
]

logger = logging.getLogger("soundings.oidc")

ALLOWED_ALGORITHMS: Final = frozenset(
    {
        "RS256", "RS384", "RS512",
        "PS256", "PS384", "PS512",
        "ES256", "ES384", "ES512",
        "EdDSA",
    }
)  # fmt: skip
"""Asymmetric signatures only: ``none`` and HMAC (``HS*``, keyed with the client
secret) are refused."""

CLOCK_LEEWAY: Final = 60.0
"""Seconds of clock skew allowed for ``exp`` and ``iat``."""

DISCOVERY_TTL: Final = 3600.0
FAILED_DISCOVERY_TTL: Final = 30.0
JWKS_TTL: Final = 3600.0
"""The key set is fetched again after this long (and at once for an unknown ``kid``)."""
DISCOVERY_TIMEOUT: Final = httpx.Timeout(5.0)
TOKEN_TIMEOUT: Final = httpx.Timeout(10.0)
MAX_SUBJECT_LENGTH: Final = 255

DiscoveryStatus = Literal["ok", "unreachable", "invalid", "issuer_mismatch"]


class OidcError(Exception):
    """The provider answered something unusable. ``reason`` is a fixed string for the
    server log; it never contains token, claim or IdP text."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class ProviderMetadata:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    end_session_endpoint: str | None
    token_endpoint_auth_methods: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Discovery:
    status: DiscoveryStatus
    metadata: ProviderMetadata | None
    checked_at: datetime
    fetched_at: float
    """Monotonic time of the fetch (cache age)."""

    @property
    def ttl(self) -> float:
        return DISCOVERY_TTL if self.status == "ok" else FAILED_DISCOVERY_TTL


_ENDPOINTS: Final = ("authorization_endpoint", "token_endpoint", "jwks_uri")


def _url(value: object) -> str | None:
    if isinstance(value, str) and urlsplit(value).scheme in {"http", "https"}:
        return value
    return None


def parse_metadata(
    document: object, issuer: str, *, https_only: bool = False
) -> ProviderMetadata | DiscoveryStatus:
    """The usable parts of a discovery document, or why it is unusable.
    ``https_only`` (production): an endpoint that isn't https makes it ``invalid``."""
    if not isinstance(document, Mapping):
        return "invalid"
    endpoints = {name: _url(document.get(name)) for name in _ENDPOINTS}
    if None in endpoints.values():
        return "invalid"
    if https_only and any(
        isinstance(url, str) and urlsplit(url).scheme != "https"
        for url in (*endpoints.values(), document.get("end_session_endpoint"))
    ):
        return "invalid"
    if document.get("issuer") != issuer:
        return "issuer_mismatch"
    methods = document.get("token_endpoint_auth_methods_supported")
    return ProviderMetadata(
        issuer=issuer,
        authorization_endpoint=str(endpoints["authorization_endpoint"]),
        token_endpoint=str(endpoints["token_endpoint"]),
        jwks_uri=str(endpoints["jwks_uri"]),
        end_session_endpoint=_url(document.get("end_session_endpoint")),
        token_endpoint_auth_methods=tuple(method for method in methods if isinstance(method, str))
        if isinstance(methods, list)
        else (),
    )


class OidcProvider:
    """The configured provider, with its cached metadata and keys (per process).

    ``transport`` replaces the network (tests); ``clock`` is monotonic seconds.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings
        self._transport = transport
        self._clock = clock
        self._discovery: Discovery | None = None
        self._discovery_lock = asyncio.Lock()
        self._keys: KeySet | None = None
        self._keys_uri: str | None = None
        self._keys_fetched_at = 0.0

    # --- HTTP -------------------------------------------------------------------------
    def _client(self, timeout: httpx.Timeout) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=self._transport,
            timeout=timeout,
            follow_redirects=False,
            headers={"Accept": "application/json"},
        )

    async def _get_json(self, url: str) -> object:
        async with self._client(DISCOVERY_TIMEOUT) as client:
            response = await client.get(url)
        response.raise_for_status()
        return response.json()

    # --- Discovery --------------------------------------------------------------------
    @property
    def issuer(self) -> str:
        if self.settings.oidc_issuer is None:
            raise OidcError("sso not configured")
        return self.settings.oidc_issuer

    def cached_discovery(self) -> Discovery | None:
        """The cached result while it is fresh."""
        cached = self._discovery
        if cached is not None and self._clock() - cached.fetched_at < cached.ttl:
            return cached
        return None

    async def discover(self) -> Discovery:
        """The provider's metadata (cached: an hour when usable, 30 s when not)."""
        cached = self.cached_discovery()
        if cached is not None:
            return cached
        async with self._discovery_lock:
            cached = self.cached_discovery()
            if cached is not None:
                return cached
            discovery = await self._fetch_discovery()
            self._discovery = discovery
            if discovery.status != "ok":
                logger.warning("oidc discovery failed", extra={"status": discovery.status})
            return discovery

    async def _fetch_discovery(self) -> Discovery:
        issuer = self.issuer
        url = issuer.rstrip("/") + "/.well-known/openid-configuration"
        checked_at, fetched_at = utcnow(), self._clock()
        try:
            document = await self._get_json(url)
        except (httpx.HTTPError, ValueError) as exc:
            status: DiscoveryStatus = "invalid" if isinstance(exc, ValueError) else "unreachable"
            return Discovery(status, None, checked_at, fetched_at)
        parsed = parse_metadata(document, issuer, https_only=self.settings.is_production)
        if isinstance(parsed, str):
            return Discovery(parsed, None, checked_at, fetched_at)
        return Discovery("ok", parsed, checked_at, fetched_at)

    async def metadata(self) -> ProviderMetadata | None:
        """Usable metadata, or ``None`` (sign-in answers ``sso_unavailable``)."""
        return (await self.discover()).metadata

    async def discovery_status(self) -> SsoDiscovery | None:
        """For ``GET /admin/sso`` (section 3.10): the cached result, fetched now only when
        nothing is cached; ``None`` when SSO is off. No IdP error text."""
        if not self.settings.sso_configured:
            return None
        discovery = self._discovery or await self.discover()
        metadata = discovery.metadata
        return SsoDiscovery(
            status=discovery.status,
            end_session_supported=metadata is not None
            and metadata.end_session_endpoint is not None,
            checked_at=discovery.checked_at,
        )

    # --- Token request ------------------------------------------------------------------
    async def exchange_code(
        self, metadata: ProviderMetadata, *, code: str, redirect_uri: str, code_verifier: str
    ) -> dict[str, Any]:
        """The token endpoint's JSON for an authorization code (PKCE)."""
        settings = self.settings
        form = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
        }
        headers: dict[str, str] = {}
        secret = (
            settings.oidc_client_secret.get_secret_value() if settings.oidc_client_secret else ""
        )
        methods = metadata.token_endpoint_auth_methods
        if not secret:
            form["client_id"] = settings.oidc_client_id  # public client
        elif methods and "client_secret_basic" not in methods and "client_secret_post" in methods:
            form["client_id"] = settings.oidc_client_id
            form["client_secret"] = secret
        else:
            # RFC 6749 section 2.3.1: form-encode both parts before Base64.
            pair = f"{quote_plus(settings.oidc_client_id)}:{quote_plus(secret)}"
            headers["Authorization"] = "Basic " + base64.b64encode(pair.encode()).decode()
        try:
            async with self._client(TOKEN_TIMEOUT) as client:
                response = await client.post(metadata.token_endpoint, data=form, headers=headers)
        except httpx.HTTPError as exc:
            raise OidcError("token request failed") from exc
        if response.status_code != 200:
            raise OidcError(f"token endpoint answered {response.status_code}")
        try:
            body = response.json()
        except ValueError as exc:
            raise OidcError("token response is not JSON") from exc
        if not isinstance(body, dict):
            raise OidcError("token response is not an object")
        return body

    # --- ID token ---------------------------------------------------------------------------
    async def _key_set(self, metadata: ProviderMetadata, *, refresh: bool) -> KeySet:
        """The provider's keys: cached for :data:`JWKS_TTL`, fetched now when
        ``refresh`` (an unknown ``kid``), when due, or when ``jwks_uri`` changed."""
        due = self._clock() - self._keys_fetched_at >= JWKS_TTL
        if refresh or due or self._keys is None or self._keys_uri != metadata.jwks_uri:
            fetched_at = self._clock()
            try:
                document = await self._get_json(metadata.jwks_uri)
                if not isinstance(document, dict) or not isinstance(document.get("keys"), list):
                    raise OidcError("jwks is not a key set")
                keys = KeySet.import_key_set({"keys": document["keys"]})
            except (httpx.HTTPError, ValueError, JoseError) as exc:
                raise OidcError("jwks unavailable") from exc
            self._keys, self._keys_uri, self._keys_fetched_at = keys, metadata.jwks_uri, fetched_at
            return keys
        return self._keys

    async def validate_id_token(
        self, metadata: ProviderMetadata, id_token: str, *, nonce: str, now: float | None = None
    ) -> dict[str, Any]:
        """The ID token's claims after every check of section 3.2 step 6, else
        :class:`OidcError`."""
        try:
            compact = jws.extract_compact(id_token.encode("ascii"))
        except (JoseError, ValueError, UnicodeError) as exc:
            raise OidcError("id token is not a compact JWS") from exc
        algorithm = compact.headers().get("alg")
        if algorithm not in ALLOWED_ALGORITHMS:
            raise OidcError("id token algorithm not allowed")
        keys = await self._key_set(metadata, refresh=False)
        try:
            valid = _verify(compact, keys, algorithm)
        except InvalidKeyIdError:
            keys = await self._key_set(metadata, refresh=True)  # the IdP rotated its keys
            try:
                valid = _verify(compact, keys, algorithm)
            except JoseError as exc:
                raise OidcError("no key for the id token") from exc
        except (JoseError, ValueError) as exc:
            raise OidcError("id token signature not verifiable") from exc
        if not valid:
            raise OidcError("id token signature invalid")
        try:
            claims = json.loads(compact.payload)
        except ValueError as exc:
            raise OidcError("id token payload is not JSON") from exc
        if not isinstance(claims, dict):
            raise OidcError("id token payload is not an object")
        check_id_token_claims(
            claims,
            issuer=metadata.issuer,
            client_id=self.settings.oidc_client_id,
            nonce=nonce,
            now=time.time() if now is None else now,
        )
        return claims


def _verify(compact: jws.CompactSignature, keys: KeySet, algorithm: str) -> bool:
    try:
        return jws.validate_compact(compact, keys, algorithms=[algorithm])
    except InvalidKeyIdError:
        raise
    except ValueError as exc:  # joserfc's "Invalid key" for an unusable key
        raise OidcError("id token key unusable") from exc


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def check_id_token_claims(
    claims: Mapping[str, Any], *, issuer: str, client_id: str, nonce: str, now: float
) -> None:
    """``iss``, ``aud`` (and ``azp``), ``exp``, ``iat``, ``nonce`` and ``sub``."""
    if claims.get("iss") != issuer:
        raise OidcError("id token issuer mismatch")
    audience = claims.get("aud")
    audiences = [audience] if isinstance(audience, str) else audience
    if not isinstance(audiences, list) or client_id not in audiences:
        raise OidcError("id token audience mismatch")
    azp = claims.get("azp")
    if (len(audiences) > 1 or azp is not None) and azp != client_id:
        raise OidcError("id token azp mismatch")
    expires = _number(claims.get("exp"))
    if expires is None or expires <= now - CLOCK_LEEWAY:
        raise OidcError("id token expired")
    issued = _number(claims.get("iat"))
    if issued is None or issued > now + CLOCK_LEEWAY:
        raise OidcError("id token issued in the future")
    presented = claims.get("nonce")
    if not isinstance(presented, str) or not hmac.compare_digest(
        presented.encode("utf-8"), nonce.encode("utf-8")
    ):
        raise OidcError("id token nonce mismatch")
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject or len(subject) > MAX_SUBJECT_LENGTH:
        raise OidcError("id token subject invalid")


def get_provider(app: Any) -> OidcProvider:
    """The app's provider (created on first use; tests may set
    ``app.state.oidc_provider`` to one with a fake transport)."""
    provider: OidcProvider | None = getattr(app.state, "oidc_provider", None)
    if provider is None:
        provider = OidcProvider(app.state.settings)
        app.state.oidc_provider = provider
    return provider
