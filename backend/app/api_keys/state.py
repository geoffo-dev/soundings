"""What a key's row and its owner say now: the listed state, and why authentication
refuses it (contract-phase5 sections 3.1 and 3.2).

Pure functions over loaded rows, plus the same states in SQL for the admin filter.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from sqlalchemy import ColumnElement, and_, not_, or_

from app.config import Settings
from app.models.api_key import ApiKey
from app.models.user import User
from app.schemas.api_keys import API_KEY_OWNER_IDLE_LIMIT, ApiKeyState
from app.services.sessions import method_available

__all__ = ["RefusalReason", "key_state", "refusal_reason", "state_clause"]

RefusalReason = Literal[
    "malformed",
    "unknown",
    "mismatch",
    "revoked",
    "expired",
    "inactive_owner",
    "method_unavailable",
    "dormant_owner",
]
"""Why authentication refused a key: logged (``reason``), never returned, because every
refusal is the same 401 (contract-phase5 section 3.2)."""


def _expired(key: ApiKey, now: datetime) -> bool:
    """From ``expires_at`` on, the key is refused."""
    return key.expires_at is not None and key.expires_at <= now


def _dormant(owner: User, now: datetime) -> bool:
    """A person who hasn't used the app within :data:`API_KEY_OWNER_IDLE_LIMIT` (null:
    never). Service accounts never sign in and are exempt."""
    if owner.is_service_account:
        return False
    return owner.last_seen_at is None or owner.last_seen_at < now - API_KEY_OWNER_IDLE_LIMIT


def key_state(key: ApiKey, owner: User, now: datetime) -> ApiKeyState:
    """The listed state of a key that isn't revoked: ``expired`` wins over ``dormant``."""
    if _expired(key, now):
        return ApiKeyState.EXPIRED
    if _dormant(owner, now):
        return ApiKeyState.DORMANT
    return ApiKeyState.ACTIVE


def refusal_reason(
    key: ApiKey, owner: User, *, settings: Settings, now: datetime
) -> RefusalReason | None:
    """``None`` when the key may authenticate now; else why not (section 3.2 step 4):
    revoked, expired, an inactive or break-glass owner, a creating sign-in method that is
    no longer available, or a person's key while they haven't used the app for 30 days."""
    if key.revoked_at is not None:
        return "revoked"
    if _expired(key, now):
        return "expired"
    if not owner.is_active or owner.is_break_glass:
        return "inactive_owner"
    if not method_available(settings, key.created_auth_method):
        return "method_unavailable"
    if _dormant(owner, now):
        return "dormant_owner"
    return None


def state_clause(state: ApiKeyState, now: datetime) -> ColumnElement[bool]:
    """``state`` in SQL over ``api_keys`` joined to its owner (``users``)."""
    expired = and_(ApiKey.expires_at.is_not(None), ApiKey.expires_at <= now)
    dormant = and_(
        User.is_service_account.is_(False),
        or_(User.last_seen_at.is_(None), User.last_seen_at < now - API_KEY_OWNER_IDLE_LIMIT),
    )
    match state:
        case ApiKeyState.EXPIRED:
            return expired
        case ApiKeyState.DORMANT:
            return and_(not_(expired), dormant)
        case ApiKeyState.ACTIVE:
            return and_(not_(expired), not_(dormant))
