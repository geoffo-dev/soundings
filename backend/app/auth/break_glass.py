"""The break-glass admin (contract-phase2 section 3.8): a local platform admin whose
credentials come from a K8s Secret, for the first sign-in before SSO is configured.

* Available only while ``settings.break_glass_available`` (enabled, both credentials
  set, SSO not configured); its sessions stop working as soon as it isn't.
* Credentials are compared as SHA-256 digests in constant time, username and password
  always both, so neither the timing nor the answer says which was wrong or how long
  the secret is. Nothing submitted is ever logged or audited.
* The account is the single ``users`` row with ``is_break_glass``, created at the first
  successful sign-in with the reserved address ``break-glass@soundings.invalid``.
"""

from __future__ import annotations

import hashlib
import hmac
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.enums import AuthMethod
from app.models.user import BREAK_GLASS_EMAIL, User
from app.services import audit

__all__ = ["BREAK_GLASS_DISPLAY_NAME", "break_glass_account", "credentials_match"]

BREAK_GLASS_DISPLAY_NAME = "Break-glass admin"


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


def credentials_match(settings: Settings, username: str, password: str) -> bool:
    """The submitted credentials equal the configured ones (exactly: no trimming).

    ``hmac.compare_digest`` over fixed-length digests, for both values every time.
    False when break-glass has no credentials configured.
    """
    configured_username = settings.break_glass_username
    configured_password = settings.break_glass_password
    expected_username = configured_username.get_secret_value() if configured_username else ""
    expected_password = configured_password.get_secret_value() if configured_password else ""
    username_ok = hmac.compare_digest(_digest(username), _digest(expected_username))
    password_ok = hmac.compare_digest(_digest(password), _digest(expected_password))
    return username_ok & password_ok & bool(expected_username) & bool(expected_password)


async def _find(db: AsyncSession) -> User | None:
    user: User | None = await db.scalar(select(User).where(User.is_break_glass.is_(True)))
    if user is None:
        # A row left by a downgrade (migration 0003 re-marks it on upgrade, too).
        user = await db.scalar(
            select(User).where(
                func.lower(User.email) == BREAK_GLASS_EMAIL, User.is_service_account.is_(False)
            )
        )
        if user is not None:
            user.is_break_glass = True
    return user


async def break_glass_account(db: AsyncSession) -> User:
    """The break-glass account, created (and audited) at the first successful sign-in.
    Every sign-in re-asserts ``is_platform_admin``; a deactivated account stays
    deactivated (the caller refuses it)."""
    user = await _find(db)
    if user is None:
        user = User(
            id=uuid4(),
            email=BREAK_GLASS_EMAIL,
            display_name=BREAK_GLASS_DISPLAY_NAME,
            is_platform_admin=True,
            is_active=True,
            is_break_glass=True,
        )
        try:
            async with db.begin_nested():
                db.add(user)
                await db.flush()
        except IntegrityError:  # created by a concurrent first sign-in
            found = await _find(db)
            if found is None:
                raise
            user = found
        else:
            await audit.record(
                db,
                "user.create",
                actor=user.id,
                target_type="user",
                target_id=user.id,
                details={
                    "source": "break_glass",
                    "is_platform_admin": True,
                    "external_id_kinds": [],
                    "auth_method": AuthMethod.BREAK_GLASS,
                },
            )
    user.is_platform_admin = True
    return user
