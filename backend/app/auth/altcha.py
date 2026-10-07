"""ALTCHA proof of work for the public form (contract-phase4 section 3.5, research R1
section 7).

The public form fetches a challenge (``GET /public/projects/{slug}/altcha``); the
``altcha@3`` widget solves it in the browser (PoW v2: find a counter whose
``PBKDF2/SHA-256`` key starts with ``00``, about 250 attempts at
``SOUNDINGS_ALTCHA_COST`` iterations each) and posts the payload in the form's
``altcha`` field. Nothing about the visitor is stored: the challenge is signed (HMAC
with a key derived from ``SOUNDINGS_SECRET_KEY``), carries its expiry and the form's
slug in ``data`` (a challenge fetched for another project's form is refused), and
works offline (no third-party service).

The library (``altcha`` 2.x) checks expiry, the signature and the solution, but it
has **no replay protection**, trusts the cost and expiry inside the signature (so
:func:`verify` also refuses a cost below ``SOUNDINGS_ALTCHA_COST`` and an expiry beyond
``SOUNDINGS_ALTCHA_EXPIRY``: a leaked key can't mint cheap or lasting challenges) and
trusts the payload's shape (a counter outside
``uint32`` or a non-ASCII signature raises instead of failing). So :func:`verify`
parses the payload strictly first (anything unexpected is simply "not verified") and
:func:`spend` records the challenge's signature in ``altcha_used_challenges`` until it
expires, in the caller's transaction: a solution is accepted once.
"""

from __future__ import annotations

import base64
import binascii
import functools
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final, TypeGuard

import altcha
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.public import AltchaUsedChallenge

__all__ = [
    "ALGORITHM",
    "KEY_LENGTH",
    "KEY_PREFIX",
    "VerifiedChallenge",
    "hmac_key",
    "new_challenge",
    "spend",
    "verify",
]

ALGORITHM: Final = "PBKDF2/SHA-256"
"""The widget's default key derivation, done with WebCrypto in the browser."""
KEY_LENGTH: Final = 32
KEY_PREFIX: Final = "00"
"""Random mode: a derived key starting with one zero byte (1 in 256 attempts)."""

_INFO: Final = b"soundings/altcha/v1"
_HEX64: Final = re.compile(r"[0-9a-f]{64}")
_HEX32: Final = re.compile(r"[0-9a-f]{32}")
_PARAMETER_KEYS: Final = frozenset(
    {"algorithm", "cost", "keyLength", "keyPrefix", "nonce", "salt", "expiresAt", "data"}
)
_MAX_COUNTER: Final = 2**32 - 1  # the library packs it as a big-endian uint32
_CLOCK_SKEW: Final = timedelta(minutes=1)
"""How far another replica's clock may run ahead when it issued a challenge."""


@functools.lru_cache(maxsize=4)
def _key(secret: str) -> str:
    derived = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_INFO).derive(
        secret.encode("utf-8")
    )
    return derived.hex()


def hmac_key(settings: Settings) -> str:
    """The HMAC key for challenges: ``HKDF-SHA256(secret key, "soundings/altcha/v1")``
    in hex. Every replica derives the same key; rotating the secret key invalidates
    outstanding challenges."""
    return _key(settings.secret_key.get_secret_value())


def new_challenge(settings: Settings, slug: str, *, now: datetime) -> dict[str, Any]:
    """A signed challenge for ``slug``'s form, in the widget's JSON format
    (``{"parameters": {...}, "signature": "..."}``), expiring after
    ``SOUNDINGS_ALTCHA_EXPIRY``."""
    challenge = altcha.create_challenge(
        ALGORITHM,
        settings.altcha_cost,
        key_length=KEY_LENGTH,
        key_prefix=KEY_PREFIX,
        expires_at=int((now + settings.altcha_expiry).timestamp()),
        data={"project": slug},
        hmac_secret=hmac_key(settings),
    )
    return challenge.to_dict()


@dataclass(frozen=True, slots=True)
class VerifiedChallenge:
    """A solved, signed, unexpired challenge for the right form (not yet spent)."""

    signature: str
    expires_at: datetime


def _is_int(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


def _decode(payload: str) -> dict[str, Any] | None:
    """The payload's JSON object (standard or URL-safe base64), or ``None``."""
    try:
        raw = base64.b64decode(
            payload.replace("-", "+").replace("_", "/") + "=" * (-len(payload) % 4),
            validate=True,
        )
        decoded = json.loads(raw.decode("utf-8"))
    except (binascii.Error, ValueError, UnicodeDecodeError, RecursionError):
        return None
    return decoded if isinstance(decoded, dict) else None


def _parse(decoded: dict[str, Any]) -> altcha.Payload | None:
    """A library payload from a strictly checked structure, or ``None``: only what
    :func:`new_challenge` issues (and a solution for it) can pass."""
    challenge, solution = decoded.get("challenge"), decoded.get("solution")
    if not isinstance(challenge, dict) or not isinstance(solution, dict):
        return None
    parameters, signature = challenge.get("parameters"), challenge.get("signature")
    if not isinstance(parameters, dict) or not set(parameters) <= _PARAMETER_KEYS:
        return None
    if not isinstance(signature, str) or not _HEX64.fullmatch(signature):
        return None
    data = parameters.get("data")
    if not (
        parameters.get("algorithm") == ALGORITHM
        and _is_int(parameters.get("cost"))
        and parameters.get("keyLength") == KEY_LENGTH
        and parameters.get("keyPrefix") == KEY_PREFIX
        and isinstance(parameters.get("nonce"), str)
        and _HEX32.fullmatch(parameters["nonce"])
        and isinstance(parameters.get("salt"), str)
        and _HEX32.fullmatch(parameters["salt"])
        and _is_int(parameters.get("expiresAt"))
        and isinstance(data, dict)
        and all(isinstance(k, str) and isinstance(v, str) for k, v in data.items())
    ):
        return None
    counter, derived_key = solution.get("counter"), solution.get("derivedKey")
    if not _is_int(counter) or not 0 <= counter <= _MAX_COUNTER:
        return None
    if not isinstance(derived_key, str) or not _HEX64.fullmatch(derived_key):
        return None
    return altcha.Payload(
        altcha.Challenge(altcha.ChallengeParameters.from_dict(parameters), signature),
        altcha.Solution(counter=counter, derived_key=derived_key),
    )


def verify(
    settings: Settings, payload: str, slug: str, *, now: datetime
) -> VerifiedChallenge | None:
    """The challenge behind a widget payload if it is well formed, signed with our
    key, unexpired, issued for ``slug``'s form and solved; else ``None`` (the caller
    answers 422 ``challenge_failed`` whatever the reason). Doesn't spend it."""
    decoded = _decode(payload)
    parsed = None if decoded is None else _parse(decoded)
    if parsed is None:
        return None
    parameters = parsed.challenge.parameters
    assert parameters.expires_at is not None  # noqa: S101 - checked by _parse
    if parameters.expires_at <= now.timestamp():
        return None
    # Defence in depth (security review P7 L3): only what new_challenge issues passes,
    # even if the key leaked: no cheaper proof of work, no longer life than the settings.
    if parameters.cost < settings.altcha_cost:
        return None
    latest = now + settings.altcha_expiry + _CLOCK_SKEW
    if parameters.expires_at > latest.timestamp():
        return None
    try:
        result = altcha.verify_solution(parsed, hmac_key(settings))
    except (ValueError, TypeError, OverflowError):  # defence in depth: never a 500
        return None
    if not result.verified:
        return None
    # Signed, so ``data`` is what we issued: refuse a challenge for another form.
    if parameters.data != {"project": slug}:
        return None
    assert parsed.challenge.signature is not None  # noqa: S101 - checked by _parse
    return VerifiedChallenge(
        signature=parsed.challenge.signature,
        expires_at=datetime.fromtimestamp(parameters.expires_at, UTC),
    )


async def spend(db: AsyncSession, challenge: VerifiedChallenge) -> bool:
    """Record the challenge as used, in the caller's transaction; ``False`` if it was
    used before (a replay). A concurrent spend of the same challenge waits for the
    first transaction: if that commits, this one sees the row and returns ``False``."""
    spent = await db.scalar(
        insert(AltchaUsedChallenge)
        .values(signature=challenge.signature, expires_at=challenge.expires_at)
        .on_conflict_do_nothing(index_elements=[AltchaUsedChallenge.signature])
        .returning(AltchaUsedChallenge.signature)
    )
    return spent is not None
