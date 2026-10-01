"""The public submitter's two secrets (contract-phase4 section 3.7).

* **Tracking token**: 32 random bytes, base64url (43 characters), shown once in the
  receipt and emailed with the confirmation. Stored as its SHA-256 hex (the lookup:
  ``public_submissions.tracking_token_hash``) and sealed (AES-256-GCM, purpose
  ``submission-tracking-token``, :mod:`app.auth.sealing`) so later emails can carry the
  link; a database leak alone reveals no token. Whoever holds it gets ``public.track``
  for that one submission.
* **Confirmation token**: signed, not stored (like Phase 3's unsubscribe links):
  ``base64url(payload) "." base64url(HMAC-SHA256(key, base64url(payload)))`` with the
  compact JSON payload ``{"v": 1, "s": "<submission id>", "e": "<first 16 hex of
  SHA-256(lower(email))>", "x": <expiry, unix seconds>}`` and the key
  ``HKDF-SHA256(secret key, info="soundings/submission-verify/v1")``, compared in
  constant time, valid 3 days from when the email is rendered. It confirms the address
  only while the submission still has that address.

Neither ever travels in a URL the server sees (links put them after ``#``), and neither
is ever logged or audited.
"""

from __future__ import annotations

import base64
import binascii
import functools
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final
from uuid import UUID

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.auth.sealing import seal, unseal
from app.auth.tokens import hash_token
from app.config import Settings

__all__ = [
    "CONFIRMATION_VALIDITY",
    "Confirmation",
    "email_digest",
    "make_confirmation_token",
    "new_tracking_token",
    "read_confirmation_token",
    "seal_tracking_token",
    "tracking_token_hash",
    "unseal_tracking_token",
]

CONFIRMATION_VALIDITY: Final = timedelta(days=3)
TRACKING_PURPOSE: Final = "submission-tracking-token"
_INFO: Final = b"soundings/submission-verify/v1"
_VERSION: Final = 1
_MAX_TOKEN_LENGTH: Final = 512


# --- Tracking tokens -----------------------------------------------------------------
def new_tracking_token() -> str:
    """43 URL-safe characters (256 bits)."""
    return secrets.token_urlsafe(32)


def tracking_token_hash(token: str) -> str:
    """SHA-256 hex: the lookup column (a plain hash suffices for 256 random bits)."""
    return hash_token(token)


def seal_tracking_token(settings: Settings, token: str) -> str:
    return seal(settings, TRACKING_PURPOSE, token.encode("ascii"))


def unseal_tracking_token(settings: Settings, sealed: str) -> str | None:
    """The token, or ``None`` if the secret key changed (the link can't be re-sent)."""
    raw = unseal(settings, TRACKING_PURPOSE, sealed)
    try:
        return None if raw is None else raw.decode("ascii")
    except UnicodeDecodeError:
        return None


# --- Confirmation tokens -------------------------------------------------------------
@functools.lru_cache(maxsize=4)
def _key(secret: str) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_INFO).derive(
        secret.encode("utf-8")
    )


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _mac(settings: Settings, body: str) -> str:
    key = _key(settings.secret_key.get_secret_value())
    return _b64(hmac.new(key, body.encode("ascii"), hashlib.sha256).digest())


def email_digest(email: str) -> str:
    """First 16 hex digits of SHA-256(lower(email)): binds a confirmation link to the
    address it was sent to, without putting the address in the token."""
    return hashlib.sha256(email.lower().encode("utf-8")).hexdigest()[:16]


def make_confirmation_token(
    settings: Settings, submission_id: UUID, email: str, *, now: datetime
) -> str:
    """The token for ``<base>/verify#<token>`` (charset ``[A-Za-z0-9_.-]``), valid for
    :data:`CONFIRMATION_VALIDITY` from ``now``."""
    payload = json.dumps(
        {
            "v": _VERSION,
            "s": str(submission_id),
            "e": email_digest(email),
            "x": int((now + CONFIRMATION_VALIDITY).timestamp()),
        },
        separators=(",", ":"),
    )
    body = _b64(payload.encode("utf-8"))
    return f"{body}.{_mac(settings, body)}"


@dataclass(frozen=True, slots=True)
class Confirmation:
    """What a valid, unexpired confirmation token says."""

    submission_id: UUID
    email_digest: str


def read_confirmation_token(
    settings: Settings, token: str, *, now: datetime
) -> Confirmation | None:
    """The token's claim if the signature is ours and it hasn't expired; else
    ``None`` (invalid and expired alike: the caller answers 404)."""
    if len(token) > _MAX_TOKEN_LENGTH or token.count(".") != 1:
        return None
    body, mac = token.split(".")
    try:
        expected = _mac(settings, body)
    except UnicodeEncodeError:
        return None
    if not hmac.compare_digest(mac.encode("ascii", "replace"), expected.encode("ascii")):
        return None
    try:
        payload = json.loads(_unb64(body).decode("utf-8"))
        if not isinstance(payload, dict) or set(payload) != {"v", "s", "e", "x"}:
            return None
        if payload["v"] != _VERSION:
            return None
        expires = payload["x"]
        if not isinstance(expires, int) or isinstance(expires, bool):
            return None
        digest = payload["e"]
        if not isinstance(digest, str) or len(digest) != 16:
            return None
        submission_id = UUID(str(payload["s"]))
    except (binascii.Error, ValueError, UnicodeDecodeError, TypeError):
        return None
    if expires <= now.timestamp():
        return None
    return Confirmation(submission_id=submission_id, email_digest=digest)
