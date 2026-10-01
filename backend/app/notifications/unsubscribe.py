"""Unsubscribe links (contract-phase3 section 3.5): signed, not stored, no expiry.

Token = ``base64url(payload) "." base64url(HMAC-SHA256(key, base64url(payload)))`` with
the compact JSON payload ``{"v": 1, "u": "<user id>", "s": "<scope>"}`` and a key
derived from ``SOUNDINGS_SECRET_KEY`` by HKDF-SHA256 (info ``soundings/unsubscribe/v1``),
compared in constant time. Rotating the secret key invalidates every link.

A GET never changes anything (link scanners prefetch); a POST turns email off for the
token's scope (``self.unsubscribe``, c14: the token is the authority, no session).
"""

from __future__ import annotations

import base64
import binascii
import functools
import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import Resource, Rule, require
from app.config import Settings
from app.models.enums import NotificationMode, NotificationType
from app.models.user import User
from app.notifications import preferences
from app.schemas.notifications import UnsubscribeInfo, UnsubscribeScope

__all__ = [
    "Unsubscribe",
    "confirm",
    "email_hint",
    "make_token",
    "read_token",
    "unsubscribe_info",
]

_INFO: Final = b"soundings/unsubscribe/v1"
_VERSION: Final = 1


@functools.lru_cache(maxsize=4)
def _key(secret: str) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_INFO).derive(
        secret.encode("utf-8")
    )


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _sign(settings: Settings, body: str) -> str:
    key = _key(settings.secret_key.get_secret_value())
    return _b64(hmac.new(key, body.encode("ascii"), hashlib.sha256).digest())


def make_token(settings: Settings, user_id: UUID, scope: UnsubscribeScope) -> str:
    """The token for an email's unsubscribe link (charset ``[A-Za-z0-9_.-]``)."""
    payload = json.dumps(
        {"v": _VERSION, "u": str(user_id), "s": scope.value}, separators=(",", ":")
    )
    body = _b64(payload.encode("utf-8"))
    return f"{body}.{_sign(settings, body)}"


@dataclass(frozen=True, slots=True)
class Unsubscribe:
    user_id: UUID
    scope: UnsubscribeScope


def read_token(settings: Settings, token: str) -> Unsubscribe | None:
    """The token's user and scope, or ``None`` if it isn't one we signed (forged,
    truncated, signed with another key, unknown version or scope)."""
    body, dot, signature = token.partition(".")
    if not dot or not body or not signature:
        return None
    if not hmac.compare_digest(_sign(settings, body), signature):
        return None
    try:
        data = json.loads(_unb64(body))
        if not isinstance(data, dict) or data.get("v") != _VERSION:
            return None
        return Unsubscribe(user_id=UUID(str(data["u"])), scope=UnsubscribeScope(data["s"]))
    except (ValueError, KeyError, TypeError, binascii.Error, UnicodeError):
        return None


def email_hint(address: str) -> str:
    """``ada@example.com`` -> ``a•••@example.com``."""
    local, _, domain = address.partition("@")
    return f"{local[:1]}•••@{domain}" if domain else "•••"


async def _user(db: AsyncSession, settings: Settings, token: str) -> tuple[User, Unsubscribe]:
    """The token's active user; 404 otherwise (policy ``self.unsubscribe``, c14)."""
    found = read_token(settings, token)
    user = None
    if found is not None:
        user = await db.scalar(select(User).where(User.id == found.user_id))
    valid = found is not None and user is not None and user.is_active
    require(None, Rule.SELF_UNSUBSCRIBE, Resource(token_valid=valid))
    assert user is not None  # noqa: S101 - narrowed by require
    assert found is not None  # noqa: S101
    return user, found


def _scope_types(
    scope: UnsubscribeScope, modes: dict[NotificationType, NotificationMode]
) -> list[NotificationType]:
    if scope is UnsubscribeScope.ALL:
        return list(NotificationType)
    if scope is UnsubscribeScope.DIGEST:
        return [type_ for type_ in NotificationType if modes[type_] is NotificationMode.DIGEST]
    return [NotificationType(scope.value)]


async def unsubscribe_info(db: AsyncSession, settings: Settings, token: str) -> UnsubscribeInfo:
    """What the link turns off (``GET``): changes nothing."""
    user, found = await _user(db, settings, token)
    modes = await preferences.all_modes(db, user.id)
    types = _scope_types(found.scope, modes)
    return UnsubscribeInfo(
        scope=found.scope,
        types=types,
        unsubscribed=all(modes[type_] is NotificationMode.OFF for type_ in types),
        email_hint=email_hint(user.email),
    )


async def confirm(
    db: AsyncSession, settings: Settings, token: str, *, all_types: bool = False
) -> UnsubscribeInfo:
    """Turn email off for the token's scope (or every type); idempotent."""
    user, found = await _user(db, settings, token)
    scope = UnsubscribeScope.ALL if all_types else found.scope
    modes = await preferences.all_modes(db, user.id)
    types = _scope_types(scope, modes)
    await preferences.update(db, user.id, dict.fromkeys(types, NotificationMode.OFF))
    return UnsubscribeInfo(
        scope=scope, types=types, unsubscribed=True, email_hint=email_hint(user.email)
    )
