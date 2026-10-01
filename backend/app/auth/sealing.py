"""Authenticated encryption with the app's secret key, for values the server must get
back unread and unchanged: the SSO sign-in attempt in the ``soundings_oidc`` cookie
(contract-phase2 section 3.2), the ID token kept for sign-out (section 3.9) and a public
submitter's tracking token, so later emails can carry their link (contract-phase4
section 3.7).

AES-256-GCM with a key derived per purpose from ``SOUNDINGS_SECRET_KEY`` (HKDF-SHA256),
so a value sealed for one purpose never opens as another. A sealed value is
``base64url(nonce || ciphertext || tag)`` with a random 96-bit nonce. Changing the
secret key makes every sealed value unreadable: sign-ins in progress start again and
sign-out goes without ``id_token_hint``.
"""

from __future__ import annotations

import base64
import binascii
import functools
import secrets
from typing import Final, Literal

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.config import Settings

__all__ = ["Purpose", "seal", "unseal"]

Purpose = Literal["oidc-login-attempt", "session-id-token", "submission-tracking-token"]

_NONCE_BYTES: Final = 12
_TAG_BYTES: Final = 16


@functools.lru_cache(maxsize=8)
def _cipher(secret: str, purpose: str) -> AESGCM:
    key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"soundings/" + purpose.encode("ascii"),
    ).derive(secret.encode("utf-8"))
    return AESGCM(key)


def _for(settings: Settings, purpose: Purpose) -> AESGCM:
    return _cipher(settings.secret_key.get_secret_value(), purpose)


def seal(settings: Settings, purpose: Purpose, data: bytes) -> str:
    """``data`` encrypted and authenticated for ``purpose`` (URL- and cookie-safe)."""
    nonce = secrets.token_bytes(_NONCE_BYTES)
    sealed = nonce + _for(settings, purpose).encrypt(nonce, data, purpose.encode("ascii"))
    return base64.urlsafe_b64encode(sealed).rstrip(b"=").decode("ascii")


def unseal(settings: Settings, purpose: Purpose, value: str) -> bytes | None:
    """The data sealed for ``purpose``, or ``None`` when ``value`` was not sealed with
    this key for this purpose, was changed, or isn't a sealed value at all."""
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (binascii.Error, ValueError):
        return None
    if len(raw) < _NONCE_BYTES + _TAG_BYTES:
        return None
    nonce, ciphertext = raw[:_NONCE_BYTES], raw[_NONCE_BYTES:]
    try:
        return _for(settings, purpose).decrypt(nonce, ciphertext, purpose.encode("ascii"))
    except InvalidTag:
        return None
