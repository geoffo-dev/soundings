"""Groups, their IdP mappings and members, the mapping test, and project roles granted
to groups (contract-phase2 sections 3.5-3.7)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import AfterValidator, Field

from app.models.enums import GroupSyncMode, ProjectRole
from app.schemas.base import RequestModel, ResponseModel
from app.schemas.common import Page
from app.schemas.projects import ProjectRef
from app.schemas.users import UserRef

__all__ = [
    "MAX_IDP_VALUES",
    "Group",
    "GroupCreate",
    "GroupMappingUpdate",
    "GroupMember",
    "GroupMemberAdd",
    "GroupMemberPage",
    "GroupPage",
    "GroupProjectGrant",
    "GroupRef",
    "GroupSearchResult",
    "GroupSummary",
    "GroupUpdate",
    "MappingEffect",
    "MappingTestGroup",
    "MappingTestRequest",
    "MappingTestResult",
    "ProjectAccessEntry",
    "ProjectAccessPage",
    "ProjectGroupGrant",
    "ProjectGroupGrantAdd",
    "ProjectGroupGrantUpdate",
    "RoleSource",
    "UserProjectRole",
    "normalise_idp_value",
]

MAX_IDP_VALUES = 50
"""IdP values per group."""


def normalise_idp_value(value: str) -> str:
    """The one form IdP group values are stored and compared in (section 3.5).

    Trim whitespace, strip ``/`` at both ends, trim again, lower-case:
    ``"/Innovation/Admins "`` -> ``"innovation/admins"`` (a Keycloak full path matches
    a mapping typed with or without the leading slash). Inner slashes stay, so
    ``"admins"`` does not match ``"/innovation/admins"`` (and a subgroup never
    inherits its parent's mapping). Lower-casing means two IdP groups that differ only
    in case are the same value. ``""`` means "ignore". Used for both the mapping (on
    save) and the claim (at sign-in and in the test).
    """
    return value.strip().strip("/").strip().lower()


def _normalised_values(values: list[str]) -> list[str]:
    normalised: list[str] = []
    for value in values:
        cleaned = normalise_idp_value(value)
        if not cleaned:
            raise ValueError(f"IdP value {value!r} is empty once slashes are stripped")
        if len(cleaned) > 255:
            raise ValueError("IdP values are at most 255 characters")
        if cleaned not in normalised:
            normalised.append(cleaned)
    return sorted(normalised)


IdpValues = Annotated[
    list[Annotated[str, Field(min_length=1, max_length=255)]],
    Field(max_length=MAX_IDP_VALUES),
    AfterValidator(_normalised_values),
]
"""IdP group values as typed by an admin: normalised, de-duplicated and sorted."""

GroupName = Annotated[str, Field(min_length=1, max_length=80)]
GroupDescription = Annotated[str, Field(max_length=500)]


# --- References ----------------------------------------------------------------------
class GroupRef(ResponseModel):
    """Enough to show and link a group."""

    id: UUID
    name: str


class GroupSearchResult(GroupRef):
    """A group in a picker (granting a group a project role)."""

    description: str
    member_count: int = Field(
        description="Active members, manual or synced (deactivated users don't count)."
    )


class RoleSource(ResponseModel):
    """One reason a user holds a project role."""

    kind: Literal["direct", "group"] = Field(
        description="direct: project membership; group: a grant to a group the user is in."
    )
    role: ProjectRole
    group: GroupRef | None = Field(description="The group (kind group), else null.")


class UserProjectRole(ResponseModel):
    """A user's effective role in a project and where it comes from."""

    project: ProjectRef
    role: ProjectRole = Field(description="Effective role: the highest of the sources.")
    sources: list[RoleSource] = Field(description="Direct first, then groups by name.")


# --- Admin: groups -------------------------------------------------------------------
class GroupSummary(GroupSearchResult):
    """A row in Admin settings -> Groups."""

    sync_mode: GroupSyncMode = Field(
        description=(
            "managed: sign-in sync adds and removes synced memberships; additive: it "
            "only adds. Manual memberships are never touched by sync."
        )
    )
    idp_values: list[str] = Field(
        description="Mapped IdP group values, normalised and sorted. Empty: not mapped."
    )
    project_count: int = Field(description="Projects that grant this group a role.")
    created_at: datetime
    updated_at: datetime


class GroupProjectGrant(ResponseModel):
    """A project role granted to the group (seen from the group)."""

    project: ProjectRef
    role: ProjectRole


class Group(GroupSummary):
    """A group with its counts by provenance and project grants (members: paged)."""

    manual_member_count: int = Field(
        description="Active members added by an admin (some also synced)."
    )
    synced_member_count: int = Field(description="Active members added by sign-in sync.")
    project_grants: list[GroupProjectGrant] = Field(description="By project name.")


class GroupCreate(RequestModel):
    name: GroupName
    description: GroupDescription = ""
    sync_mode: GroupSyncMode = GroupSyncMode.MANAGED
    idp_values: IdpValues = Field(default_factory=list)


class GroupUpdate(RequestModel):
    """Rename or describe a group; omitted or null fields are unchanged. The mapping
    has its own endpoint (``PUT .../mapping``)."""

    name: GroupName | None = None
    description: GroupDescription | None = None


class GroupMappingUpdate(RequestModel):
    """The complete IdP mapping. Takes effect for each user at their next sign-in."""

    sync_mode: GroupSyncMode
    idp_values: IdpValues


class GroupPage(Page[GroupSummary]):
    """Groups by name."""


class GroupMember(ResponseModel):
    """A group member with provenance. A user can be both manual and synced.
    Deactivated members are listed (``is_active`` false) but grant no access."""

    user: UserRef
    email: str
    is_active: bool
    manual: bool = Field(description="Added by an admin; sign-in sync never changes it.")
    synced: bool = Field(description="Added by sign-in sync from the IdP claim.")
    joined_at: datetime = Field(description="When the membership started.")


class GroupMemberPage(Page[GroupMember]):
    """Members by display name."""


class GroupMemberAdd(RequestModel):
    """Add a manual member (or mark a synced member manual too)."""

    user_id: UUID


# --- Admin: test mapping ---------------------------------------------------------------
class MappingTestRequest(RequestModel):
    """A claim set pasted by an admin (e.g. a decoded ID token), and optionally a user
    whose current memberships the effects are computed against."""

    claims: dict[str, Any] = Field(
        description="The token's claims as a JSON object. Nothing is stored or logged."
    )
    user_id: UUID | None = Field(
        default=None,
        description="Compute effects for this user's memberships; null: a user with none.",
    )


MappingEffect = Literal["add", "keep", "remove"]
"""What sign-in sync would do to the user's *synced* membership of a group."""


class MappingTestGroup(ResponseModel):
    """One group the claim set matches or, with a user, one of their synced groups
    that it no longer matches."""

    group: GroupRef
    sync_mode: GroupSyncMode
    matched_values: list[str] = Field(
        description="Normalised claim values that matched; empty when none did."
    )
    effect: MappingEffect = Field(
        description=(
            "add: becomes a synced member; keep: stays a synced member (already synced "
            "and matched, or an additive group that no longer matches: matched_values "
            "empty); remove: the synced membership ends (managed group, nothing matched)."
        )
    )
    manual: bool = Field(
        description="The user is a manual member (unaffected by sync, stays a member)."
    )


class MappingTestResult(ResponseModel):
    """What a sign-in with these claims would do (section 3.6)."""

    groups_claim: str | None = Field(
        description="The configured claim path (SOUNDINGS_OIDC_GROUPS_CLAIM); null: sync off."
    )
    claim_found: bool = Field(description="The claim exists in the pasted claims.")
    values: list[str] = Field(description="Extracted values, normalised, de-duplicated, sorted.")
    ignored_count: int = Field(
        description="Entries ignored: not strings, or empty once normalised."
    )
    groups: list[MappingTestGroup] = Field(
        description=(
            "Every matched group, and every synced group of the user's that no longer "
            "matches (remove, or keep for additive groups), by name."
        )
    )
    project_roles: list[UserProjectRole] = Field(
        description=(
            "The user's effective project roles after the sync: direct roles (with a "
            "user), manual groups and the synced groups that result. By project name."
        )
    )


# --- Projects: group grants and everyone with access -------------------------------------
class ProjectGroupGrant(ResponseModel):
    """A project role granted to every member of a group (seen from the project)."""

    group: GroupSearchResult
    role: ProjectRole
    granted_at: datetime


class ProjectGroupGrantAdd(RequestModel):
    group_id: UUID
    role: ProjectRole = ProjectRole.MEMBER


class ProjectGroupGrantUpdate(RequestModel):
    role: ProjectRole


class ProjectAccessEntry(ResponseModel):
    """Someone with an effective role in the project, and why."""

    user: UserRef
    email: str
    role: ProjectRole = Field(description="Effective role (the highest source).")
    sources: list[RoleSource] = Field(description="Direct first, then groups by name.")


class ProjectAccessPage(Page[ProjectAccessEntry]):
    """Everyone with access, by display name."""
