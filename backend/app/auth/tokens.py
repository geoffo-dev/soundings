"""Opaque random tokens (sessions, CSRF): generation, hashing and comparison."""

from __future__ import annotations

import hashlib
import hmac
import secrets

__all__ = ["hash_token", "new_token", "tokens_match"]

TOKEN_BYTES = 32
"""256 bits of randomness (ADR 0005)."""


def new_token() -> str:
    """A URL- and cookie-safe random token (43 characters)."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> str:
    """SHA-256 hex digest: what the database stores instead of the token.

    A plain hash is enough for 256-bit random tokens (no guessing, no rainbow tables);
    a database leak does not reveal usable cookies.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def tokens_match(presented: str | None, expected: str) -> bool:
    """Constant-time comparison; a missing or empty value never matches."""
    if not presented or not expected:
        return False
    return hmac.compare_digest(presented.encode("utf-8"), expected.encode("utf-8"))
