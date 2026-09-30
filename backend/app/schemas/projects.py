"""Projects, their settings, members and tags."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import Field

from app.models.enums import IdeaStatus, ProjectRole, ProjectVisibility, Resolution
from app.schemas.base import PROJECT_KEY_PATTERN, SLUG_PATTERN, RequestModel, ResponseModel
from app.schemas.rubric import RubricCriterion
from app.schemas.users import UserRef

__all__ = [
    "DEFAULT_STATUS_LABELS",
    "Member",
    "MemberAdd",
    "MemberUpdate",
    "Project",
    "ProjectCreate",
    "ProjectPermissions",
    "ProjectRef",
    "ProjectSummary",
    "ProjectUpdate",
    "StatusLabels",
    "StatusLabelsUpdate",
    "TagInfo",
]

DEFAULT_STATUS_LABELS: dict[IdeaStatus | Resolution, str] = {
    IdeaStatus.NEW: "New",
    IdeaStatus.EVALUATING: "Evaluating",
    IdeaStatus.SHORTLISTED: "Shortlisted",
    IdeaStatus.PROPOSAL: "Proposal",
    IdeaStatus.CLOSED: "Closed",
    Resolution.ACCEPTED: "Accepted",
    Resolution.REJECTED: "Rejected",
    Resolution.PARKED: "Parked",
}
"""Labels used when a project has no override (keys match ``projects.status_labels``)."""

Label = Annotated[str, Field(min_length=1, max_length=24)]


class ProjectRef(ResponseModel):
    """Enough to link to a project: ``/projects/{slug}``; idea keys use ``key``."""

    id: UUID
    slug: str
    key: str = Field(description='Idea-key prefix, e.g. "CUST" in CUST-12.')
    name: str


class StatusLabels(ResponseModel):
    """The label to show for every status and resolution (overrides applied).

    A closed idea shows its resolution's label (e.g. "Accepted"), not "Closed".
    """

    new: str
    evaluating: str
    shortlisted: str
    proposal: str
    closed: str
    accepted: str
    rejected: str
    parked: str


class StatusLabelsUpdate(RequestModel):
    """Rename labels. Omitted fields are unchanged; ``null`` resets to the default."""

    new: Label | None = None
    evaluating: Label | None = None
    shortlisted: Label | None = None
    proposal: Label | None = None
    closed: Label | None = None
    accepted: Label | None = None
    rejected: Label | None = None
    parked: Label | None = None


class ProjectPermissions(ResponseModel):
    """What the current user may do at project level (drives the UI; the API enforces).

    Use these, not ``my_role``: platform admins act as project admins without a role.
    """

    can_manage: bool = Field(
        description="Edit settings, rubric and members (project or platform admin)."
    )
    can_create_ideas: bool = Field(
        description=(
            "idea.create: member, admin or platform admin, and the project is not "
            "archived. Drives the submit dialog's project picker and N."
        )
    )


class ProjectSummary(ProjectRef):
    """A project in the sidebar / project list."""

    description: str
    visibility: ProjectVisibility
    my_role: ProjectRole | None = Field(
        description=(
            "Your effective project role; null without one (an internal project you "
            "don't belong to, or a platform admin who isn't a member)."
        )
    )
    idea_count: int
    member_count: int
    archived_at: datetime | None
    permissions: ProjectPermissions


class Project(ProjectSummary):
    """Full project: settings, resolved status labels and the active rubric."""

    allow_volunteer_owners: bool = Field(
        description='Members may take ownership of an unowned idea ("I\'ll own this").'
    )
    default_evaluation_days: int = Field(
        description="Evaluation due date = start of evaluation + this many days."
    )
    status_labels: StatusLabels
    rubric: list[RubricCriterion] = Field(description="Active criteria in display order.")
    created_at: datetime


class ProjectCreate(RequestModel):
    """Create a project with the default rubric and one admin (``admin_user_id``)."""

    name: str = Field(min_length=1, max_length=80)
    slug: str = Field(
        min_length=2,
        max_length=48,
        pattern=SLUG_PATTERN,
        description="URL name, e.g. customer-innovation. Cannot be changed later.",
    )
    key: str = Field(
        pattern=PROJECT_KEY_PATTERN,
        description="2-6 upper-case letters/digits for idea keys, e.g. CUST. Cannot be changed.",
    )
    description: str = Field(default="", max_length=1000)
    visibility: ProjectVisibility = ProjectVisibility.PRIVATE
    admin_user_id: UUID | None = Field(
        default=None,
        description="The project's first admin (an active user); defaults to you.",
    )


class ProjectUpdate(RequestModel):
    """Partial update; omitted fields are unchanged. ``slug`` and ``key`` are immutable."""

    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=1000)
    visibility: ProjectVisibility | None = None
    allow_volunteer_owners: bool | None = None
    default_evaluation_days: int | None = Field(default=None, ge=1, le=90)
    status_labels: StatusLabelsUpdate | None = None
    archived: bool | None = Field(
        default=None, description="true archives (read-only, hidden by default); false restores."
    )


class Member(ResponseModel):
    """A direct project member. ``email`` helps tell people apart (colleagues only)."""

    user: UserRef
    email: str
    role: ProjectRole
    joined_at: datetime


class MemberAdd(RequestModel):
    user_id: UUID
    role: ProjectRole = ProjectRole.MEMBER


class MemberUpdate(RequestModel):
    role: ProjectRole


class TagInfo(ResponseModel):
    """A tag in use in the project (filter chips, tag autocomplete).

    Tags no idea uses any more are not listed (they stay stored, so re-adding one
    keeps its first spelling).
    """

    id: UUID
    name: str
    idea_count: int = Field(ge=1, description="Ideas you can view that carry the tag.")
