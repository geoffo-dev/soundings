"""Group sync at each SSO sign-in (contract-phase2 section 3.6).

Runs in the sign-in transaction, after login matching, when a groups claim is
configured (``SOUNDINGS_OIDC_GROUPS_CLAIM``; never for break-glass or dev login).
The rules are :func:`app.auth.group_mapping.plan_group_sync`; this module applies
them with a fixed number of statements, whatever the number of groups:

* **managed** groups: the user's *synced* memberships become exactly the matched ones;
* **additive** groups: sync only adds;
* **manual** memberships are never touched (only admins set and clear ``manual``).

Locking: the user row ``FOR NO KEY UPDATE`` first (two sign-ins of one user, or a sign-in
and an admin's ``add_group_member`` / ``remove_group_member``, which take the same
lock, serialise), then the matched groups ``FOR KEY SHARE`` (a concurrent
``delete_group`` either comes first or waits; its cascade then removes the row).

Changes are audited as one ``user.groups_sync`` entry, only when something changed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.group_mapping import (
    extract_groups,
    matching_groups,
    memberships_of,
    plan_group_sync,
)
from app.config import Settings
from app.models.base import utcnow
from app.models.enums import AuthMethod
from app.models.group import GroupMembership
from app.models.user import User
from app.services import audit

__all__ = ["GroupSyncResult", "lock_user", "sync_groups"]


@dataclass(frozen=True, slots=True)
class GroupSyncResult:
    claim_found: bool
    added_group_ids: list[UUID]
    """``synced`` went from false to true (a new membership, or a manual member)."""
    removed_group_ids: list[UUID]
    """``synced`` went from true to false (row deleted, or the manual member stays)."""


async def lock_user(db: AsyncSession, user_id: UUID) -> None:
    """``SELECT ... FOR NO KEY UPDATE`` on the user row: serialises every change to the
    user's group memberships (sign-in sync, ``add_group_member``,
    ``remove_group_member``). It doesn't block foreign-key checks elsewhere."""
    await db.execute(select(User.id).where(User.id == user_id).with_for_update(key_share=True))


async def sync_groups(
    db: AsyncSession, user: User, claims: Mapping[str, Any], settings: Settings
) -> GroupSyncResult | None:
    """Apply section 3.6 for ``user`` from the validated ID token's ``claims``.

    ``None`` when group sync is off (no groups claim configured). The caller has
    already refused Entra ID group overage (:func:`~app.auth.group_mapping.groups_overage`).
    """
    path = settings.oidc_groups_claim
    if not path:
        return None
    extracted = extract_groups(claims, path)
    await lock_user(db, user.id)
    matched = await matching_groups(db, extracted.values, lock=True)
    current = await memberships_of(db, user.id)
    # Phase 8b (product owner, review S1 b): who the user researches for while holding a
    # role in a private project, compared after the sync (lazy import: no cycle).
    from app.services import research_assignment

    held = await research_assignment.roles_before(db, user_ids=[user.id])
    plan = plan_group_sync(matched=matched, memberships=current)

    now = utcnow()
    new_rows = [change.group_id for change in plan if change.changed and change.before is None]
    mark_synced = [
        change.group_id
        for change in plan
        if change.changed
        and change.before is not None
        and change.after is not None
        and change.after.synced
    ]
    clear_synced = [
        change.group_id
        for change in plan
        if change.changed and change.after is not None and not change.after.synced
    ]
    delete_rows = [change.group_id for change in plan if change.changed and change.after is None]

    if new_rows:
        await db.execute(
            insert(GroupMembership),
            [
                {
                    "group_id": group_id,
                    "user_id": user.id,
                    "manual": False,
                    "synced": True,
                    "created_at": now,
                    "updated_at": now,
                }
                for group_id in new_rows
            ],
        )
    for group_ids, synced in ((mark_synced, True), (clear_synced, False)):
        if group_ids:
            await db.execute(
                update(GroupMembership)
                .where(GroupMembership.user_id == user.id, GroupMembership.group_id.in_(group_ids))
                .values(synced=synced, updated_at=now)
                .execution_options(synchronize_session=False)
            )
    if delete_rows:
        await db.execute(
            delete(GroupMembership)
            .where(
                GroupMembership.user_id == user.id,
                GroupMembership.group_id.in_(delete_rows),
                # Only a synced-only row: never delete a manual membership.
                GroupMembership.manual.is_(False),
            )
            .execution_options(synchronize_session=False)
        )

    added = [change.group_id for change in plan if change.added]
    removed = [change.group_id for change in plan if change.removed]
    if added or removed:
        await audit.record(
            db,
            "user.groups_sync",
            actor=user.id,
            target_type="user",
            target_id=user.id,
            details={
                "added_group_ids": added,
                "removed_group_ids": removed,
                "claim_found": extracted.claim_found,
                "auth_method": AuthMethod.SSO,
            },
        )
    if removed:
        await research_assignment.end_after_role_loss(db, held, actor=user.id)
    return GroupSyncResult(
        claim_found=extracted.claim_found, added_group_ids=added, removed_group_ids=removed
    )
