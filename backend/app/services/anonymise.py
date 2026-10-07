"""``soundings anonymise-user <email>``: remove a leaver's personal data (security
review P7 L5; UK GDPR erasure for staff accounts; operator guide "What is stored about
users").

Deactivating an account (Admin settings -> Users) signs the person out, revokes their
keys and stops their notifications, but keeps their name, address and identities, so
their ideas, evaluations and comments still say who wrote them. Anonymising goes
further, once the account is deactivated:

* the name becomes "Former user <8 hex>" and the address
  ``former-user-<id>@anonymised.invalid`` (unique, never deliverable); no avatar;
* their sign-in identities (IdP issuer and subject) and external ids are deleted, so
  no sign-in matches the account again;
* keys are revoked (deactivation already did) and sessions ended;
* their inbox, email preferences and outbox rows are deleted;
* @mentions of them in comments show the placeholder (the token keeps the id);
* their ideas, evaluations, comments, votes and audit entries stay, under the
  placeholder; the audit trail keeps its ids.

It records one ``user.anonymise`` entry (no actor: an operator at the console; counts
only, never the old name or address). CLI only: no API route, no admin button. Refused
for an active account, the break-glass account and AI agents' service accounts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Comment
from app.models.api_key import ApiKey
from app.models.base import utcnow
from app.models.notification import Notification, NotificationPreference, OutboundEmail
from app.models.user import User, UserExternalId, UserIdentity, UserSession
from app.services import audit

__all__ = ["PLACEHOLDER_DOMAIN", "AnonymiseRefused", "Anonymised", "anonymise_user"]

PLACEHOLDER_DOMAIN: Final = "anonymised.invalid"
"""RFC 2606's ``.invalid``: an address that can never be delivered."""


class AnonymiseRefused(Exception):
    """The account can't be anonymised (the message says why and what to do)."""


@dataclass(frozen=True, slots=True)
class Anonymised:
    user_id: str
    display_name: str
    counts: dict[str, int]

    def summary(self) -> str:
        removed = ", ".join(f"{name} {count}" for name, count in self.counts.items())
        return f"Anonymised user {self.user_id} as {self.display_name!r} ({removed})."


def _rowcount(result: object) -> int:
    return int(getattr(result, "rowcount", 0) or 0)


async def anonymise_user(db: AsyncSession, email: str) -> Anonymised:
    """Anonymise the deactivated account with this address (case-insensitive), in the
    caller's transaction. Raises :class:`AnonymiseRefused`."""
    user = await db.scalar(
        select(User)
        .where(func.lower(User.email) == email.strip().lower())
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if user is None:
        raise AnonymiseRefused("No account has that email address.")
    if user.is_service_account:
        raise AnonymiseRefused(
            "That is an AI agent's service account: disable or delete the agent in "
            "Admin settings -> AI agents instead."
        )
    if user.is_break_glass:
        raise AnonymiseRefused("The break-glass account can't be anonymised.")
    if user.is_active:
        raise AnonymiseRefused(
            "Deactivate the account first (Admin settings -> Users), then run this again."
        )

    placeholder = f"Former user {user.id.hex[:8]}"
    now = utcnow()
    counts = {
        "identities": _rowcount(
            await db.execute(delete(UserIdentity).where(UserIdentity.user_id == user.id))
        ),
        "external_ids": _rowcount(
            await db.execute(delete(UserExternalId).where(UserExternalId.user_id == user.id))
        ),
        "api_keys": _rowcount(
            await db.execute(
                update(ApiKey)
                .where(ApiKey.user_id == user.id, ApiKey.revoked_at.is_(None))
                .values(revoked_at=now)
            )
        ),
        "sessions": _rowcount(
            await db.execute(delete(UserSession).where(UserSession.user_id == user.id))
        ),
        "notifications": _rowcount(
            await db.execute(delete(Notification).where(Notification.user_id == user.id))
        ),
        "emails": _rowcount(
            await db.execute(
                delete(OutboundEmail).where(OutboundEmail.recipient_user_id == user.id)
            )
        ),
        "mentions": await _rename_mentions(db, user, placeholder),
    }
    await db.execute(
        delete(NotificationPreference).where(NotificationPreference.user_id == user.id)
    )
    user.display_name = placeholder
    user.email = f"former-user-{user.id.hex}@{PLACEHOLDER_DOMAIN}"
    user.avatar_url = None
    user.last_seen_at = None
    await db.flush()
    await audit.record(
        db,
        "user.anonymise",
        actor=None,
        target_type="user",
        target_id=user.id,
        details=counts,
    )
    return Anonymised(user_id=str(user.id), display_name=placeholder, counts=counts)


async def _rename_mentions(db: AsyncSession, user: User, placeholder: str) -> int:
    """Rewrite the label of every ``@[Name](user:<id>)`` token for this user in
    comments; returns how many comments changed."""
    token = f"(user:{user.id})"
    pattern = re.compile(r"@\[[^\[\]\r\n]{1,100}\]\(user:" + re.escape(str(user.id)) + r"\)", re.I)
    comments = list(
        await db.scalars(select(Comment).where(func.lower(Comment.body_md).contains(token.lower())))
    )
    changed = 0
    for comment in comments:
        rewritten = pattern.sub(f"@[{placeholder}]{token}", comment.body_md)
        if rewritten != comment.body_md:
            comment.body_md = rewritten
            changed += 1
    return changed
