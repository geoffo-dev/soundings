"""The IdP's claims as Soundings reads them, and what sign-in group sync does with them.

One implementation for sign-in (:mod:`app.auth.login_matching`,
:mod:`app.auth.group_sync`) and the admin "test mapping" box
(``POST /admin/groups/test-mapping``, :func:`preview_group_mapping`), so the box shows
exactly what a sign-in would do (contract-phase2 sections 3.3, 3.5, 3.6 and 3.12).

Pure helpers:

* :func:`resolve_claim`: a claim by path (the whole string as a top-level name first,
  else a dotted path through nested objects).
* :func:`extract_groups`: the groups claim -> normalised, de-duplicated, sorted values.
* :func:`groups_overage`: Entra ID left the groups out (``_claim_names``).
* :func:`external_id_from_claims`, :func:`email_from_claims`,
  :func:`display_name_from_claims`: the matching inputs.
* :func:`plan_group_sync`: the section 3.6 table: given the groups the claims match
  and the user's memberships, what happens to each synced membership.

Database readers (no writes): :func:`matching_groups`, :func:`memberships_of`,
:func:`project_roles_for` and :func:`preview_group_mapping`.

Claims are personal data: nothing here logs or stores them.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.errors import ProblemError
from app.models.enums import GroupSyncMode, ProjectRole
from app.models.group import Group, GroupIdpValue, GroupMembership, ProjectGroupGrant
from app.models.project import Project, ProjectMember
from app.models.user import User
from app.schemas.admin_users import is_reserved_email
from app.schemas.base import BIDI_CONTROLS, has_tag_character
from app.schemas.groups import (
    GroupRef,
    MappingTestGroup,
    MappingTestResult,
    RoleSource,
    UserProjectRole,
    normalise_idp_value,
)
from app.schemas.projects import ProjectRef

__all__ = [
    "DISPLAY_NAME_MAX_LENGTH",
    "EMAIL_MAX_LENGTH",
    "EXTERNAL_ID_MAX_LENGTH",
    "MAX_GROUP_ELEMENTS",
    "EmailClaim",
    "GroupClaim",
    "Membership",
    "PlannedChange",
    "display_name_from_claims",
    "email_from_claims",
    "external_id_from_claims",
    "extract_groups",
    "groups_overage",
    "matching_groups",
    "memberships_of",
    "plan_group_sync",
    "preview_group_mapping",
    "project_roles_for",
    "resolve_claim",
]

MAX_GROUP_ELEMENTS: Final = 1000
"""Only the first 1,000 elements of the groups claim are considered (section 3.5)."""

EXTERNAL_ID_MAX_LENGTH: Final = 200
EMAIL_MAX_LENGTH: Final = 320
DISPLAY_NAME_MAX_LENGTH: Final = 100

_ROLE_RANK: Final = {ProjectRole.VIEWER: 1, ProjectRole.MEMBER: 2, ProjectRole.ADMIN: 3}


# --- Claims ---------------------------------------------------------------------------------
def resolve_claim(claims: Mapping[str, Any], path: str) -> tuple[bool, Any]:
    """``(found, value)`` for a claim path (section 3.5, step 1).

    The whole configured string as a top-level claim name first (names may contain
    dots: ``https://example.com/groups``), otherwise split on ``.`` and walk nested
    objects (``realm_access.roles``). A missing segment, or a non-object on the way,
    means the claim is absent. An empty path is never found.
    """
    if not path:
        return False, None
    if path in claims:
        return True, claims[path]
    node: Any = claims
    for segment in path.split("."):
        if not isinstance(node, Mapping) or segment not in node:
            return False, None
        node = node[segment]
    return True, node


@dataclass(frozen=True, slots=True)
class GroupClaim:
    """The groups claim, extracted (section 3.5)."""

    claim_found: bool
    """The claim exists in the token (even if it is null or empty)."""
    values: tuple[str, ...]
    """Normalised, de-duplicated, sorted values."""
    ignored_count: int
    """Elements ignored: not strings, empty once normalised, beyond the first 1,000,
    or a claim value that is neither a list nor a string."""


def extract_groups(claims: Mapping[str, Any], path: str) -> GroupClaim:
    """The groups claim at ``path`` (``SOUNDINGS_OIDC_GROUPS_CLAIM``; empty = sync off).

    A list gives its elements, a string one element, absent or null nothing, anything
    else nothing (one ignored). Absent means "no groups" on purpose: sync then removes
    every synced membership of managed groups (fail closed).
    """
    found, value = resolve_claim(claims, path)
    if not found or value is None:
        return GroupClaim(claim_found=found, values=(), ignored_count=0)
    if isinstance(value, str):
        elements: list[Any] = [value]
    elif isinstance(value, list):
        elements = value
    else:
        return GroupClaim(claim_found=True, values=(), ignored_count=1)
    ignored = max(0, len(elements) - MAX_GROUP_ELEMENTS)
    values: set[str] = set()
    for element in elements[:MAX_GROUP_ELEMENTS]:
        normalised = normalise_idp_value(element) if isinstance(element, str) else ""
        if normalised:
            values.add(normalised)
        else:
            ignored += 1
    return GroupClaim(claim_found=True, values=tuple(sorted(values)), ignored_count=ignored)


def groups_overage(claims: Mapping[str, Any], path: str) -> bool:
    """Entra ID group overage: group sync is on, the groups claim is absent and
    ``_claim_names`` names it (more than 200 groups; section 3.2 step 7). The sign-in
    is denied rather than read as "no groups", which would remove every managed
    membership."""
    if not path:
        return False
    found, _ = resolve_claim(claims, path)
    claim_names = claims.get("_claim_names")
    return not found and isinstance(claim_names, Mapping) and path in claim_names


def external_id_from_claims(claims: Mapping[str, Any], path: str) -> str | None:
    """The external-ID claim when usable (section 3.3): a string (trimmed, 1-200
    characters) or an integer (its decimal string). Anything else counts as absent."""
    found, value = resolve_claim(claims, path)
    if not found or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        value = value.strip()
        if 1 <= len(value) <= EXTERNAL_ID_MAX_LENGTH:
            return value
    return None


@dataclass(frozen=True, slots=True)
class EmailClaim:
    address: str | None
    """A usable address (a string of at most 320 characters with an ``@``, not under
    the reserved ``.invalid`` domain), else ``None``."""
    verified: bool
    """``address`` is set and ``email_verified`` is JSON ``true`` or ``"true"``."""


def email_from_claims(claims: Mapping[str, Any]) -> EmailClaim:
    """The ``email`` claim and whether the IdP verified it. A missing
    ``email_verified`` is *not* verified (Entra ID sends none)."""
    raw = claims.get("email")
    if not isinstance(raw, str):
        return EmailClaim(address=None, verified=False)
    address = raw.strip()
    if "@" not in address or len(address) > EMAIL_MAX_LENGTH or is_reserved_email(address):
        return EmailClaim(address=None, verified=False)
    flag = claims.get("email_verified")
    verified = flag is True or (isinstance(flag, str) and flag.strip().lower() == "true")
    return EmailClaim(address=address, verified=verified)


def display_name_from_claims(claims: Mapping[str, Any], email: str) -> str:
    """For auto-created users: ``name``, else ``preferred_username``, else the email's
    local part; on one line (control characters such as CR/LF and U+2028 become spaces
    and bidi controls are removed, as the admin API rejects them), trimmed and cut to
    100 characters (fixed, no setting)."""
    for key in ("name", "preferred_username"):
        value = claims.get(key)
        if isinstance(value, str) and (name := _one_line(value)):
            return name[:DISPLAY_NAME_MAX_LENGTH]
    return _one_line(email.split("@", 1)[0])[:DISPLAY_NAME_MAX_LENGTH] or "New user"


def _one_line(value: str) -> str:
    """``value`` with control characters and line separators as spaces, bidi controls
    and Unicode tag characters removed and runs of white space collapsed: what the admin
    API rejects (:func:`app.schemas.base.has_control`)."""
    return " ".join(
        "".join(
            ""
            if char in BIDI_CONTROLS or has_tag_character(char)
            else " "
            if unicodedata.category(char) in ("Cc", "Zl", "Zp")
            else char
            for char in value
        ).split()
    )


# --- What sync does (section 3.6) -------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Membership:
    """A user's membership of one group: added by an admin and/or by sync."""

    manual: bool
    synced: bool


Effect = Literal["add", "keep", "remove"]


@dataclass(frozen=True, slots=True)
class PlannedChange:
    """What sync does to the user's *synced* membership of one group."""

    group_id: UUID
    sync_mode: GroupSyncMode
    matched_values: tuple[str, ...]
    """Claim values that matched the group's mapping (empty: it no longer matches)."""
    effect: Effect
    before: Membership | None
    after: Membership | None
    """``None``: no membership row (deleted, or never there)."""

    @property
    def changed(self) -> bool:
        return self.before != self.after

    @property
    def added(self) -> bool:
        """``synced`` goes from false to true (a new row, or a manual member)."""
        return self.after is not None and self.after.synced and not self._was_synced

    @property
    def removed(self) -> bool:
        """``synced`` goes from true to false (row deleted, or the flag cleared)."""
        return self._was_synced and (self.after is None or not self.after.synced)

    @property
    def _was_synced(self) -> bool:
        return self.before is not None and self.before.synced


def plan_group_sync(
    *,
    matched: Mapping[UUID, tuple[GroupSyncMode, tuple[str, ...]]],
    memberships: Mapping[UUID, tuple[GroupSyncMode, Membership]],
) -> list[PlannedChange]:
    """The section 3.6 table for one user, by group id.

    ``matched``: every group whose mapping matches the claims, with its mode and the
    values that matched. ``memberships``: the user's current memberships, with each
    group's mode. Returns a change for every matched group (``add``, or ``keep`` when
    already synced) and every *synced* membership that no longer matches (``remove``
    for managed groups, ``keep`` for additive ones). Manual flags are never changed.
    """
    changes: list[PlannedChange] = []
    for group_id in sorted(set(matched) | set(memberships)):
        current = memberships.get(group_id)
        before = current[1] if current else None
        if group_id in matched:
            mode, values = matched[group_id]
            if before is not None and before.synced:
                changes.append(PlannedChange(group_id, mode, values, "keep", before, before))
            else:
                manual = before is not None and before.manual
                added = Membership(manual=manual, synced=True)
                changes.append(PlannedChange(group_id, mode, values, "add", before, added))
            continue
        if current is None or before is None or not before.synced:
            continue  # manual only: sync never touches it
        mode = current[0]
        if mode is GroupSyncMode.ADDITIVE:
            changes.append(PlannedChange(group_id, mode, (), "keep", before, before))
        else:
            remaining = Membership(manual=True, synced=False) if before.manual else None
            changes.append(PlannedChange(group_id, mode, (), "remove", before, remaining))
    return changes


# --- Database readers ---------------------------------------------------------------------------
async def matching_groups(
    db: AsyncSession, values: Collection[str], *, lock: bool = False
) -> dict[UUID, tuple[GroupSyncMode, tuple[str, ...]]]:
    """Groups with a stored IdP value equal to one of ``values`` (exact match on the
    normalised form), with their mode and the values that matched.

    ``lock``: read the groups ``FOR KEY SHARE`` (sign-in sync), so a concurrent
    ``delete_group`` either comes first (nothing to match) or waits.
    """
    if not values:
        return {}
    statement = (
        select(Group.id, Group.sync_mode, GroupIdpValue.value)
        .join(GroupIdpValue, GroupIdpValue.group_id == Group.id)
        .where(GroupIdpValue.value.in_(sorted(set(values))))
        .order_by(Group.id, GroupIdpValue.value)
    )
    if lock:
        statement = statement.with_for_update(read=True, key_share=True, of=Group)
    found: dict[UUID, tuple[GroupSyncMode, tuple[str, ...]]] = {}
    for group_id, mode, value in (await db.execute(statement)).all():
        previous = found.get(group_id, (mode, ()))[1]
        found[group_id] = (GroupSyncMode(mode), (*previous, value))
    return found


async def memberships_of(
    db: AsyncSession, user_id: UUID
) -> dict[UUID, tuple[GroupSyncMode, Membership]]:
    """The user's group memberships with each group's mode."""
    rows = await db.execute(
        select(
            GroupMembership.group_id,
            Group.sync_mode,
            GroupMembership.manual,
            GroupMembership.synced,
        )
        .join(Group, Group.id == GroupMembership.group_id)
        .where(GroupMembership.user_id == user_id)
    )
    return {
        group_id: (GroupSyncMode(mode), Membership(manual=manual, synced=synced))
        for group_id, mode, manual, synced in rows.all()
    }


async def project_roles_for(
    db: AsyncSession, *, user_id: UUID | None, group_ids: Collection[UUID]
) -> list[UserProjectRole]:
    """Effective project roles from a user's direct memberships (``user_id``) and the
    grants of ``group_ids``, with their sources (direct first, then groups by name),
    by project name. The same answer as ``project_effective_roles`` for those inputs.
    """
    sources: dict[UUID, list[tuple[tuple[int, str, str], RoleSource]]] = {}
    projects: dict[UUID, Project] = {}
    if user_id is not None:
        direct = await db.execute(
            select(Project, ProjectMember.role)
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .where(ProjectMember.user_id == user_id)
        )
        for project, role in direct.all():
            projects[project.id] = project
            source = RoleSource(kind="direct", role=ProjectRole(role), group=None)
            sources.setdefault(project.id, []).append(((0, "", ""), source))
    if group_ids:
        granted = await db.execute(
            select(Project, ProjectGroupGrant.role, Group.id, Group.name)
            .join(ProjectGroupGrant, ProjectGroupGrant.project_id == Project.id)
            .join(Group, Group.id == ProjectGroupGrant.group_id)
            .where(ProjectGroupGrant.group_id.in_(list(group_ids)))
        )
        for project, role, group_id, name in granted.all():
            projects[project.id] = project
            source = RoleSource(
                kind="group", role=ProjectRole(role), group=GroupRef(id=group_id, name=name)
            )
            key = (1, name.lower(), str(group_id))
            sources.setdefault(project.id, []).append((key, source))
    result: list[UserProjectRole] = []
    for project_id, found in sources.items():
        ordered = [source for _, source in sorted(found, key=lambda item: item[0])]
        project = projects[project_id]
        result.append(
            UserProjectRole(
                project=ProjectRef.model_validate(project),
                role=max((source.role for source in ordered), key=_ROLE_RANK.__getitem__),
                sources=ordered,
            )
        )
    return sorted(result, key=lambda item: (item.project.name.lower(), str(item.project.id)))


class UserNotFoundProblem(ProblemError):
    def __init__(self) -> None:
        super().__init__(422, "user_not_found", detail="No user with that id.")


async def preview_group_mapping(
    db: AsyncSession, settings: Settings, claims: Mapping[str, Any], user_id: UUID | None
) -> MappingTestResult:
    """The "test mapping" box (section 3.12): what a sign-in with ``claims`` would do
    to the groups (and so the project roles) of ``user_id``, or of a user with no
    memberships. Reads only; nothing is written, audited, stored or logged.

    Raises 422 ``user_not_found`` for an unknown ``user_id``. The route checks
    ``platform.manage_groups`` first.
    """
    if user_id is not None and await db.get(User, user_id) is None:
        raise UserNotFoundProblem
    path = settings.oidc_groups_claim
    extracted = extract_groups(claims, path)
    memberships = await memberships_of(db, user_id) if user_id is not None else {}
    plan: list[PlannedChange] = []
    if path:  # group sync off: sign-in changes no membership
        matched = await matching_groups(db, extracted.values)
        plan = plan_group_sync(matched=matched, memberships=memberships)

    names = dict(
        (
            await db.execute(
                select(Group.id, Group.name).where(
                    Group.id.in_([change.group_id for change in plan])
                )
            )
        ).all()
    )
    groups = sorted(
        (
            MappingTestGroup(
                group=GroupRef(id=change.group_id, name=names[change.group_id]),
                sync_mode=change.sync_mode,
                matched_values=list(change.matched_values),
                effect=change.effect,
                manual=change.before is not None and change.before.manual,
            )
            for change in plan
        ),
        key=lambda item: (item.group.name.lower(), str(item.group.id)),
    )
    after = {group_id: membership for group_id, (_, membership) in memberships.items()}
    for change in plan:
        if change.after is None:
            after.pop(change.group_id, None)
        else:
            after[change.group_id] = change.after
    project_roles = await project_roles_for(db, user_id=user_id, group_ids=list(after))
    return MappingTestResult(
        groups_claim=path or None,
        claim_found=extracted.claim_found,
        values=list(extracted.values),
        ignored_count=extracted.ignored_count,
        groups=groups,
        project_roles=project_roles,
    )
