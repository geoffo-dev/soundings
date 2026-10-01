"""An SSO sign-in in progress (``GET /auth/login`` -> ``GET /auth/callback``,
contract-phase2 section 3.2), sealed into the HttpOnly ``soundings_oidc`` cookie.

Nothing is stored server-side: starting a sign-in writes no row, so no number of
unfinished sign-ins (from any number of addresses) can fill a table or lock anyone
else out. The browser carries the attempt but can neither read it (the PKCE verifier
and nonce stay secret) nor change it (AES-GCM, :mod:`app.auth.sealing`). The cookie
binds the attempt to the browser that started it: a callback URL replayed elsewhere
has no cookie (login CSRF), and the IdP accepts each authorization code once.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Final

from app.auth.cookies import OIDC_COOKIE_MAX_AGE
from app.auth.sealing import seal, unseal
from app.config import Settings

__all__ = [
    "ATTEMPT_LIFETIME",
    "MAX_COOKIE_VALUE",
    "LoginAttempt",
    "new_attempt",
    "open_attempt",
    "seal_attempt",
]

ATTEMPT_LIFETIME: Final = OIDC_COOKIE_MAX_AGE
"""10 minutes: the cookie's Max-Age, also enforced on the sealed expiry."""

MAX_COOKIE_VALUE: Final = 3800
"""Browsers keep cookies up to 4096 bytes (name and value): a longer sealed attempt is
sealed again with ``next_path`` = ``/`` (only a very long non-ASCII ``next`` gets
there)."""


@dataclass(frozen=True, slots=True)
class LoginAttempt:
    state: str
    nonce: str
    code_verifier: str
    redirect_uri: str
    """The exact redirect URI sent to the IdP (repeated in the token request)."""
    next_path: str
    """Where to go after signing in: an already validated same-origin path."""
    expires_at: datetime

    @property
    def code_challenge(self) -> str:
        """``BASE64URL(SHA256(code_verifier))`` (PKCE S256)."""
        digest = hashlib.sha256(self.code_verifier.encode("ascii")).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def new_attempt(*, redirect_uri: str, next_path: str, now: datetime) -> LoginAttempt:
    """256-bit ``state`` and ``nonce``, a 512-bit PKCE verifier, 10 minutes to finish."""
    return LoginAttempt(
        state=secrets.token_urlsafe(32),
        nonce=secrets.token_urlsafe(32),
        code_verifier=secrets.token_urlsafe(64),
        redirect_uri=redirect_uri,
        next_path=next_path,
        expires_at=now + ATTEMPT_LIFETIME,
    )


def _seal(settings: Settings, attempt: LoginAttempt) -> str:
    payload = {
        "s": attempt.state,
        "n": attempt.nonce,
        "v": attempt.code_verifier,
        "r": attempt.redirect_uri,
        "x": attempt.next_path,
        "e": int(attempt.expires_at.timestamp()),
    }
    data = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return seal(settings, "oidc-login-attempt", data)


def seal_attempt(settings: Settings, attempt: LoginAttempt) -> str:
    """The cookie value: the attempt, encrypted and authenticated."""
    value = _seal(settings, attempt)
    if len(value) > MAX_COOKIE_VALUE and attempt.next_path != "/":
        value = _seal(settings, replace(attempt, next_path="/"))
    return value


def open_attempt(settings: Settings, value: str | None) -> LoginAttempt | None:
    """The attempt sealed in a cookie value, or ``None`` (missing, forged, changed,
    sealed with another secret key). Expiry is the caller's check."""
    if not value or len(value) > 2 * MAX_COOKIE_VALUE:
        return None
    data = unseal(settings, "oidc-login-attempt", value)
    if data is None:
        return None
    try:
        payload = json.loads(data)
        return LoginAttempt(
            state=_text(payload["s"]),
            nonce=_text(payload["n"]),
            code_verifier=_text(payload["v"]),
            redirect_uri=_text(payload["r"]),
            next_path=_text(payload["x"]),
            expires_at=datetime.fromtimestamp(int(payload["e"]), tz=UTC),
        )
    except (ValueError, KeyError, TypeError, OverflowError, OSError):
        return None  # only the server seals these: a payload of another shape is stale


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("expected a string")
    return value
