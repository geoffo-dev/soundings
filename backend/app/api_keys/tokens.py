"""API-key strings: generation, format, hashing (contract-phase5 section 3.1).

A key is ``sdg_`` + a 12-character **lookup id** + ``_`` + a 40-character **secret**,
both base62 from :mod:`secrets` (a CSPRNG). The database keeps the lookup id in clear
(the index authentication uses, and the ``prefix`` people see) and the SHA-256 of the
whole key: a fast hash is right for a long random secret (nothing to brute-force), and
no pepper means rotating ``SOUNDINGS_SECRET_KEY`` doesn't revoke every key. Hashes are
compared in constant time.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import string
from typing import Final

from app.schemas.api_keys import (
    API_KEY_LOOKUP_LENGTH,
    API_KEY_PATTERN,
    API_KEY_PREFIX,
    API_KEY_SECRET_LENGTH,
)

__all__ = [
    "BASE62",
    "format_key",
    "hash_key",
    "hashes_match",
    "key_prefix",
    "lookup_id_of",
    "lookup_id_query",
    "new_key",
]

BASE62: Final = string.digits + string.ascii_letters

_KEY: Final = re.compile(API_KEY_PATTERN)
_PREFIX_LENGTH: Final = len(API_KEY_PREFIX) + API_KEY_LOOKUP_LENGTH
_LOOKUP: Final = re.compile(rf"[A-Za-z0-9]{{{API_KEY_LOOKUP_LENGTH}}}")
_PREFIX_QUERY: Final = re.compile(
    rf"(?:{re.escape(API_KEY_PREFIX)})?([A-Za-z0-9]{{{API_KEY_LOOKUP_LENGTH}}})"
    rf"(?:_[A-Za-z0-9]*)?"
)


def _random(length: int) -> str:
    return "".join(secrets.choice(BASE62) for _ in range(length))


def format_key(lookup_id: str, secret: str) -> str:
    return f"{API_KEY_PREFIX}{lookup_id}_{secret}"


def new_key() -> tuple[str, str]:
    """A fresh ``(lookup_id, key)``. The caller stores the lookup id and
    :func:`hash_key` of the key, shows the key once and forgets it."""
    lookup_id = _random(API_KEY_LOOKUP_LENGTH)
    return lookup_id, format_key(lookup_id, _random(API_KEY_SECRET_LENGTH))


def hash_key(key: str) -> str:
    """SHA-256 (hex) of the whole key string: what ``api_keys.secret_hash`` holds."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def hashes_match(presented: str, stored: str) -> bool:
    """Constant-time comparison of two hex digests."""
    return hmac.compare_digest(presented.encode("ascii"), stored.encode("ascii"))


def lookup_id_of(token: str) -> str | None:
    """The lookup id of a well-formed key (exactly ``API_KEY_PATTERN``), else ``None``:
    a malformed token never reaches the database."""
    if len(token) != _PREFIX_LENGTH + 1 + API_KEY_SECRET_LENGTH or not _KEY.fullmatch(token):
        return None
    return token[len(API_KEY_PREFIX) : _PREFIX_LENGTH]


def key_prefix(lookup_id: str) -> str:
    """How a key is shown after creation: ``sdg_`` + its lookup id."""
    return f"{API_KEY_PREFIX}{lookup_id}"


def lookup_id_query(text: str) -> str | None:
    """The lookup id an admin search names: a key's prefix (``sdg_`` + lookup id), the
    bare lookup id, or a pasted whole key (cut to its lookup id; the SPA already cuts it
    before the request). ``None`` for anything else."""
    match = _PREFIX_QUERY.fullmatch(text.strip())
    if match is None or not _LOOKUP.fullmatch(match.group(1)):
        return None
    return match.group(1)
