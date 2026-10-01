"""Login matching: which Soundings user an SSO sign-in is (contract-phase2 section 3.3).

The steps run in order; the first that identifies a user decides, and that outcome is
final (a match on an ineligible or conflicting account denies instead of falling
through to the next step, which could link or create a second account):

1. **Identity**: the user linked to ``(issuer, subject)``.
2. **External ID** (``SOUNDINGS_OIDC_EXTERNAL_ID_CLAIM`` set, claim usable): the user
   with an external ID of ``SOUNDINGS_OIDC_EXTERNAL_ID_KIND`` equal to the claim,
   case-insensitively. Link it.
3. **Verified email** (``SOUNDINGS_OIDC_MATCH_VERIFIED_EMAIL``): the user with that
   email, case-insensitively, unless external-ID matching is configured and the user
   has an external ID of that kind (then only step 2 may link them). Link it.
4. **Auto-create** (``SOUNDINGS_OIDC_AUTO_CREATE_USERS``, verified email, address
   not taken by anyone): a new, ordinary user with no roles. Link it.
5. Otherwise deny.

Eligible users are active, not service accounts and not the break-glass admin.
Linking and creating are audited here (``user.identity_link``, ``user.create``);
denials are returned, and the caller audits them in their own transaction
(:func:`record_denial`), never with an actor and never with claims or emails.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.group_mapping import (
    display_name_from_claims,
    email_from_claims,
    external_id_from_claims,
)
from app.config import Settings
from app.models.enums import AuthMethod
from app.models.user import User, UserExternalId, UserIdentity
from app.schemas.auth import LoginErrorCode
from app.services import audit

__all__ = [
    "DENIAL_CODES",
    "DenialReason",
    "LoginDenied",
    "LoginMatch",
    "MatchedBy",
    "eligible",
    "find_identity",
    "match_login",
    "record_denial",
]

MatchedBy = Literal["identity", "external_id", "email", "created"]

DenialReason = Literal[
    # Login matching (section 3.3)
    "account_disabled",
    "already_linked",
    "external_id_mismatch",
    "external_id_missing",
    "email_taken",
    "email_not_verified",
    "groups_overage",
    "no_match",
    # The sign-in flow (section 3.2) and break-glass (section 3.8)
    "login_expired",
    "login_cancelled",
    "sso_failed",
    "invalid_credentials",
    "too_many_attempts",
]

DENIAL_CODES: Final[Mapping[str, LoginErrorCode]] = {
    "account_disabled": LoginErrorCode.ACCOUNT_DISABLED,
    "already_linked": LoginErrorCode.IDENTITY_CONFLICT,
    "external_id_mismatch": LoginErrorCode.IDENTITY_CONFLICT,
    "external_id_missing": LoginErrorCode.IDENTITY_CONFLICT,
    "email_taken": LoginErrorCode.IDENTITY_CONFLICT,
    "email_not_verified": LoginErrorCode.NO_ACCOUNT,
    "no_match": LoginErrorCode.NO_ACCOUNT,
    "groups_overage": LoginErrorCode.SSO_FAILED,
    "login_expired": LoginErrorCode.LOGIN_EXPIRED,
    "login_cancelled": LoginErrorCode.LOGIN_CANCELLED,
    "sso_failed": LoginErrorCode.SSO_FAILED,
}
"""The coarse ``/login?error=`` code for each audited reason (section 4.2)."""


@dataclass(frozen=True, slots=True)
class LoginMatch:
    user: User
    identity: UserIdentity
    matched_by: MatchedBy


@dataclass(frozen=True, slots=True)
class LoginDenied:
    reason: DenialReason
    user_id: UUID | None = None
    """The account the attempt identified (the audit target), if any."""

    @property
    def code(self) -> LoginErrorCode:
        return DENIAL_CODES[self.reason]

    @classmethod
    def of(cls, reason: DenialReason, user: User | None = None) -> LoginDenied:
        return cls(reason=reason, user_id=user.id if user is not None else None)


def eligible(user: User) -> bool:
    """May sign in with SSO: active, not a service account, not the break-glass admin."""
    return user.is_active and not user.is_service_account and not user.is_break_glass


async def find_identity(db: AsyncSession, issuer: str, subject: str) -> UserIdentity | None:
    return await db.scalar(
        select(UserIdentity).where(UserIdentity.issuer == issuer, UserIdentity.subject == subject)
    )


async def _linked_at(db: AsyncSession, user: User, issuer: str) -> bool:
    found = await db.scalar(
        select(UserIdentity.id).where(
            UserIdentity.user_id == user.id, UserIdentity.issuer == issuer
        )
    )
    return found is not None


async def _external_id_of(db: AsyncSession, user: User, kind: str) -> str | None:
    value: str | None = await db.scalar(
        select(UserExternalId.value).where(
            UserExternalId.user_id == user.id, UserExternalId.kind == kind
        )
    )
    return value


class _Relink(Exception):
    """The identity was linked concurrently: run matching again."""


async def match_login(
    db: AsyncSession,
    settings: Settings,
    *,
    issuer: str,
    subject: str,
    claims: Mapping[str, Any],
) -> LoginMatch | LoginDenied:
    """Match a validated ID token to a user (and link or create one), or deny.

    Runs inside the caller's sign-in transaction. Linking happens in a SAVEPOINT: if
    the same person's first sign-in in another tab linked the identity a moment
    earlier, the unique violation is rolled back and matching runs once more (step 1
    then finds the identity) without losing the transaction.
    """
    try:
        return await _match(db, settings, issuer=issuer, subject=subject, claims=claims)
    except _Relink:
        return await _match(db, settings, issuer=issuer, subject=subject, claims=claims)


async def _match(
    db: AsyncSession,
    settings: Settings,
    *,
    issuer: str,
    subject: str,
    claims: Mapping[str, Any],
) -> LoginMatch | LoginDenied:
    # 1. Identity.
    identity = await find_identity(db, issuer, subject)
    if identity is not None:
        user = await db.get(User, identity.user_id)
        if user is None or not eligible(user):
            return LoginDenied.of("account_disabled", user)
        return LoginMatch(user=user, identity=identity, matched_by="identity")

    kind = settings.oidc_external_id_kind if settings.oidc_external_id_claim else ""
    external_id = external_id_from_claims(claims, settings.oidc_external_id_claim)

    # 2. External ID.
    if kind and external_id is not None:
        user = await db.scalar(
            select(User)
            .join(UserExternalId, UserExternalId.user_id == User.id)
            .where(
                UserExternalId.kind == kind,
                func.lower(UserExternalId.value) == external_id.lower(),
            )
        )
        if user is not None:
            return await _link_if_allowed(db, user, issuer, subject, "external_id")

    # 3. Verified email.
    email = email_from_claims(claims)
    if email.verified and email.address is not None and settings.oidc_match_verified_email:
        user = await _user_by_email(db, email.address)
        if user is not None:
            if not eligible(user):
                return LoginDenied.of("account_disabled", user)
            if await _linked_at(db, user, issuer):
                return LoginDenied.of("already_linked", user)
            if kind and await _external_id_of(db, user, kind) is not None:
                # Such a user is linked only by step 2, whatever the token carries.
                return LoginDenied.of(
                    "external_id_mismatch" if external_id is not None else "external_id_missing",
                    user,
                )
            identity = await _link(db, user, issuer, subject, "email")
            return LoginMatch(user=user, identity=identity, matched_by="email")

    # 4. Auto-create.
    if settings.oidc_auto_create_users and email.address is not None:
        if not email.verified:
            return LoginDenied.of("email_not_verified")
        taken = await _user_by_email(db, email.address)
        if taken is not None:
            return LoginDenied.of("email_taken", taken)
        return await _create(db, claims, email.address, issuer, subject)

    # 5. Deny.
    if email.address is not None and not email.verified:
        return LoginDenied.of("email_not_verified")
    return LoginDenied.of("no_match")


async def _user_by_email(db: AsyncSession, address: str) -> User | None:
    user: User | None = await db.scalar(
        select(User).where(func.lower(User.email) == address.lower())
    )
    return user


async def _link_if_allowed(
    db: AsyncSession, user: User, issuer: str, subject: str, matched_by: MatchedBy
) -> LoginMatch | LoginDenied:
    if not eligible(user):
        return LoginDenied.of("account_disabled", user)
    if await _linked_at(db, user, issuer):
        return LoginDenied.of("already_linked", user)
    identity = await _link(db, user, issuer, subject, matched_by)
    return LoginMatch(user=user, identity=identity, matched_by=matched_by)


async def _link(
    db: AsyncSession, user: User, issuer: str, subject: str, matched_by: MatchedBy
) -> UserIdentity:
    identity = UserIdentity(id=uuid4(), user_id=user.id, issuer=issuer, subject=subject)
    try:
        async with db.begin_nested():
            db.add(identity)
            await db.flush()
    except IntegrityError as exc:
        raise _Relink from exc
    await audit.record(
        db,
        "user.identity_link",
        actor=user.id,
        target_type="user",
        target_id=user.id,
        details={
            "identity_id": identity.id,
            "matched_by": matched_by,
            "issuer": issuer,
            "auth_method": AuthMethod.SSO,
        },
    )
    return identity


async def _create(
    db: AsyncSession, claims: Mapping[str, Any], address: str, issuer: str, subject: str
) -> LoginMatch | LoginDenied:
    user = User(
        id=uuid4(),
        email=address,
        display_name=display_name_from_claims(claims, address),
        is_platform_admin=False,
        is_active=True,
    )
    try:
        async with db.begin_nested():
            db.add(user)
            await db.flush()
    except IntegrityError as exc:  # the same address created a moment ago
        raise _Relink from exc
    await audit.record(
        db,
        "user.create",
        actor=user.id,
        target_type="user",
        target_id=user.id,
        details={
            "source": "sso",
            "is_platform_admin": False,
            "external_id_kinds": [],
            "auth_method": AuthMethod.SSO,
        },
    )
    identity = await _link(db, user, issuer, subject, "created")
    return LoginMatch(user=user, identity=identity, matched_by="created")


async def record_denial(
    db: AsyncSession,
    reason: DenialReason,
    *,
    method: AuthMethod,
    user_id: UUID | None = None,
    issuer: str | None = None,
    subject: str | None = None,
) -> None:
    """Audit a refused sign-in: no actor (an attempt is never pinned on the account
    it tried), the identified account as target, never claims, emails or usernames."""
    details: dict[str, Any] = {"method": method, "reason": reason}
    if issuer is not None:
        details["issuer"] = issuer
    if subject is not None:
        details["subject"] = subject
    await audit.record(
        db,
        "session.sign_in_denied",
        actor=None,
        target_type="user" if user_id is not None else None,
        target_id=user_id,
        details=details,
    )
