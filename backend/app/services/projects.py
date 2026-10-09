"""Projects: list, create, settings, members, rubric and tags (contract section 3.1).

Routers authorise first (``app.authz.load_project`` + ``require``); these functions
apply the change, write the audit entry, and build the response.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import (
    Resource,
    Rule,
    admin_count,
    effective_role,
    project_permissions,
    project_resource,
    require,
    viewable_ideas,
    visible_projects,
)
from app.authz.policy import ProjectFacts
from app.domain.labels import apply_label_changes, resolved_labels
from app.domain.principal import Principal
from app.domain.rubric_defaults import default_rubric_criteria
from app.domain.template_defaults import default_template_sections
from app.errors import ConflictProblem, NotFoundProblem, ProblemError
from app.models.base import utcnow
from app.models.enums import HoldReason, ProjectRole
from app.models.evaluation import EvaluationScore
from app.models.idea import Idea, IdeaTag
from app.models.project import (
    Project,
    ProjectMember,
    RubricCriterion,
    Tag,
    project_effective_roles,
)
from app.models.user import User
from app.schemas.projects import (
    Member,
    MemberAdd,
    MemberUpdate,
    ProjectCreate,
    ProjectSummary,
    ProjectUpdate,
    StatusLabels,
    TagInfo,
)
from app.schemas.projects import Project as ProjectOut
from app.schemas.research import lifecycle
from app.schemas.rubric import Rubric, RubricUpdate
from app.schemas.rubric import RubricCriterion as RubricCriterionOut
from app.schemas.users import UserRef
from app.services import audit, research_assignment
from app.services.scoring import recompute_aggregates
from app.services.sql import require_unique_lower
from app.services.users import active_user

__all__ = [
    "add_member",
    "create_project",
    "list_members",
    "list_projects",
    "list_tags",
    "project_detail",
    "remove_member",
    "replace_rubric",
    "update_member",
    "update_project",
]


_roles = project_effective_roles
"""``member_count`` counts *active* users with an effective role (direct or through a
group): the people ``list_project_access`` lists (contract-phase2 section 3.7)."""


class UserNotFoundProblem(ProblemError):
    def __init__(self) -> None:
        super().__init__(422, "user_not_found", detail="No active user with that id.")


# --- Reading ---------------------------------------------------------------------------
def _summary(
    principal: Principal,
    project: Project,
    role: ProjectRole | None,
    idea_count: int,
    member_count: int,
    held_count: int,
) -> ProjectSummary:
    from app.services.moderation import may_moderate  # moderation builds on ideas

    resource = Resource(project=ProjectFacts.of(project), role=role)
    return ProjectSummary(
        id=project.id,
        slug=project.slug,
        key=project.key,
        name=project.name,
        description=project.description,
        visibility=project.visibility,
        my_role=role,
        idea_count=idea_count,
        member_count=member_count,
        archived_at=project.archived_at,
        research_step=project.research_step,
        lifecycle=list(lifecycle(project.research_step)),
        permissions=project_permissions(principal, resource),
        pending_moderation_count=held_count if may_moderate(principal, resource) else None,
    )


async def list_projects(
    db: AsyncSession, principal: Principal, *, include_archived: bool
) -> list[ProjectSummary]:
    """Projects the principal can view, by name, with counts and permissions."""
    ideas = (
        select(Idea.project_id, func.count().label("n"))
        .where(viewable_ideas(principal))
        .group_by(Idea.project_id)
        .subquery()
    )
    members = (
        select(_roles.c.project_id, func.count().label("n"))
        .join(User, User.id == _roles.c.user_id)
        .where(User.is_active)
        .group_by(_roles.c.project_id)
        .subquery()
    )
    held = (  # the moderation queues' totals (partial index on held ideas)
        select(Idea.project_id, func.count().label("n"))
        .where(Idea.held_for == HoldReason.MODERATION)
        .group_by(Idea.project_id)
        .subquery()
    )
    statement = (
        select(
            Project,
            effective_role(principal.user_id).label("role"),
            func.coalesce(ideas.c.n, 0),
            func.coalesce(members.c.n, 0),
            func.coalesce(held.c.n, 0),
        )
        .outerjoin(ideas, ideas.c.project_id == Project.id)
        .outerjoin(members, members.c.project_id == Project.id)
        .outerjoin(held, held.c.project_id == Project.id)
        .where(visible_projects(principal))
        .order_by(func.lower(Project.name), Project.id)
    )
    if not include_archived:
        statement = statement.where(Project.archived_at.is_(None))
    rows = await db.execute(statement)
    return [
        _summary(principal, project, role, int(idea_count), int(member_count), int(held_count))
        for project, role, idea_count, member_count, held_count in rows
    ]


def _criterion_out(criterion: RubricCriterion) -> RubricCriterionOut:
    return RubricCriterionOut.model_validate(criterion)


async def _active_criteria(db: AsyncSession, project_id: UUID) -> list[RubricCriterion]:
    rows = await db.scalars(
        select(RubricCriterion)
        .where(RubricCriterion.project_id == project_id, RubricCriterion.archived_at.is_(None))
        .order_by(RubricCriterion.position, RubricCriterion.id)
    )
    return list(rows)


async def project_detail(
    db: AsyncSession, principal: Principal, project: Project, resource: Resource
) -> ProjectOut:
    """The full project: settings, resolved labels, active rubric, permissions."""
    counted = await db.execute(
        select(
            func.count().filter(viewable_ideas(principal)),
            func.count().filter(Idea.held_for == HoldReason.MODERATION),
        )
        .select_from(Idea)
        .where(Idea.project_id == project.id)
    )
    idea_count, held_count = counted.one()
    member_count = await db.scalar(
        select(func.count())
        .select_from(_roles)
        .join(User, User.id == _roles.c.user_id)
        .where(_roles.c.project_id == project.id, User.is_active)
    )
    summary = _summary(
        principal,
        project,
        resource.role,
        int(idea_count or 0),
        int(member_count or 0),
        int(held_count or 0),
    )
    return ProjectOut(
        **summary.model_dump(),
        allow_volunteer_owners=project.allow_volunteer_owners,
        default_evaluation_days=project.default_evaluation_days,
        status_labels=StatusLabels(**resolved_labels(project.status_labels)),
        rubric=[_criterion_out(criterion) for criterion in await _active_criteria(db, project.id)],
        created_at=project.created_at,
    )


# --- Create and settings -----------------------------------------------------------------
async def create_project(db: AsyncSession, principal: Principal, body: ProjectCreate) -> ProjectOut:
    """``project.create`` (checked by the caller): default rubric and one admin."""
    admin = await active_user(db, body.admin_user_id or principal.user_id)
    if admin is None:
        raise UserNotFoundProblem
    if await db.scalar(select(Project.id).where(Project.slug == body.slug)):
        raise ConflictProblem("That URL name is taken.", code="slug_taken")
    if await db.scalar(select(Project.id).where(Project.key == body.key)):
        raise ConflictProblem("That idea key prefix is taken.", code="key_taken")

    project = Project(
        id=uuid4(),
        slug=body.slug,
        key=body.key,
        name=body.name,
        description=body.description,
        visibility=body.visibility,
    )
    db.add(project)
    db.add_all(default_rubric_criteria(project.id))
    db.add_all(default_template_sections(project.id))  # Phase 8: the built-in eight
    db.add(ProjectMember(project_id=project.id, user_id=admin.id, role=ProjectRole.ADMIN))
    try:
        await db.flush()
    except IntegrityError as exc:  # a concurrent create took the slug or key
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", "") or ""
        code = "key_taken" if "key" in constraint else "slug_taken"
        raise ConflictProblem("That project already exists.", code=code) from exc
    await db.refresh(project)
    await audit.record(
        db,
        "project.create",
        actor=principal,
        target_type="project",
        target_id=project.id,
        project_id=project.id,
        details={"rule": Rule.PROJECT_CREATE, "admin_user_id": admin.id},
    )
    return await project_detail(
        db, principal, project, await project_resource(db, principal, project)
    )


async def update_project(
    db: AsyncSession,
    principal: Principal,
    project: Project,
    resource: Resource,
    body: ProjectUpdate,
) -> ProjectOut:
    """PATCH semantics: omitted or null fields are unchanged; ``status_labels`` entries
    set to null reset the label. ``project.edit_settings`` is checked by the caller;
    renaming labels also needs ``project.rename_status_labels``."""
    if body.status_labels is not None:
        require(principal, Rule.PROJECT_RENAME_STATUS_LABELS, resource)
    changed: list[str] = []
    for field in ("name", "description", "visibility", "allow_volunteer_owners"):
        value = getattr(body, field)
        if value is not None and value != getattr(project, field):
            setattr(project, field, value)
            changed.append(field)
    if (
        body.default_evaluation_days is not None
        and body.default_evaluation_days != project.default_evaluation_days
    ):
        project.default_evaluation_days = body.default_evaluation_days
        changed.append("default_evaluation_days")
    if body.status_labels is not None:
        labels = {
            key: getattr(body.status_labels, key) for key in body.status_labels.model_fields_set
        }
        overrides = apply_label_changes(project.status_labels, labels)
        if overrides != project.status_labels:
            project.status_labels = overrides  # a new dict, so the JSONB change is saved
            changed.append("status_labels")
    if body.archived is not None and body.archived != (project.archived_at is not None):
        project.archived_at = utcnow() if body.archived else None
        changed.append("archived")

    if changed:
        await db.flush()
        await audit.record(
            db,
            "project.update",
            actor=principal,
            target_type="project",
            target_id=project.id,
            project_id=project.id,
            details={"rule": Rule.PROJECT_EDIT_SETTINGS, "fields": changed},
        )
    resource = resource.replace(project=ProjectFacts.of(project))
    return await project_detail(db, principal, project, resource)


# --- Members -----------------------------------------------------------------------------
def _member_out(member: ProjectMember, user: User) -> Member:
    return Member(
        user=UserRef.model_validate(user),
        email=user.email,
        role=member.role,
        joined_at=member.created_at,
    )


async def list_members(db: AsyncSession, project: Project) -> list[Member]:
    """Direct members: admins first, then by name."""
    rows = await db.execute(
        select(ProjectMember, User)
        .join(User, User.id == ProjectMember.user_id)
        .where(ProjectMember.project_id == project.id)
        .order_by(
            case((ProjectMember.role == ProjectRole.ADMIN, 0), else_=1),
            func.lower(User.display_name),
            User.id,
        )
    )
    return [_member_out(member, user) for member, user in rows]


async def _direct_member(db: AsyncSession, project: Project, user_id: UUID) -> ProjectMember:
    member = await db.get(ProjectMember, (project.id, user_id))
    if member is None:
        raise NotFoundProblem("Not a member of this project.")
    return member


async def _require_an_admin_left(
    db: AsyncSession, principal: Principal, project: Project, resource: Resource
) -> None:
    """c11 after the change (flushed): the project still has an effective admin."""
    await db.flush()
    remaining = await admin_count(db, project.id)
    require(principal, Rule.PROJECT_MANAGE_MEMBERS, resource.replace(admins_after_change=remaining))


def _refuse_admin_service_account(user: User, role: ProjectRole) -> None:
    """A service account (an AI agent) is never a project admin: a person stays
    accountable (contract-phase5 section 3.7; groups never contain service accounts)."""
    if user.is_service_account and role is ProjectRole.ADMIN:
        raise ConflictProblem(
            "AI agents can be members or viewers, not admins.", code="system_account"
        )


async def add_member(
    db: AsyncSession, principal: Principal, project: Project, body: MemberAdd
) -> Member:
    # Service accounts (AI agents, Phase 6) must be members of the projects they work in.
    user = await active_user(db, body.user_id, allow_service_accounts=True)
    if user is None:
        raise UserNotFoundProblem
    if await db.get(ProjectMember, (project.id, user.id)) is not None:
        raise ConflictProblem("Already a member of this project.", code="already_member")
    _refuse_admin_service_account(user, body.role)
    member = ProjectMember(project_id=project.id, user_id=user.id, role=body.role)
    db.add(member)
    await db.flush()
    await audit.record(
        db,
        "project.member_add",
        actor=principal,
        target_type="user",
        target_id=user.id,
        project_id=project.id,
        details={"rule": Rule.PROJECT_MANAGE_MEMBERS, "role": body.role},
    )
    return _member_out(member, user)


async def update_member(
    db: AsyncSession,
    principal: Principal,
    project: Project,
    resource: Resource,
    user_id: UUID,
    body: MemberUpdate,
) -> Member:
    member = await _direct_member(db, project, user_id)
    user = await db.get(User, user_id)
    assert user is not None  # noqa: S101 - the membership's foreign key
    previous = member.role
    if body.role != previous:
        _refuse_admin_service_account(user, body.role)
        member.role = body.role
        await _require_an_admin_left(db, principal, project, resource)
        await audit.record(
            db,
            "project.member_update",
            actor=principal,
            target_type="user",
            target_id=user_id,
            project_id=project.id,
            details={"rule": Rule.PROJECT_MANAGE_MEMBERS, "from_role": previous, "role": body.role},
        )
    return _member_out(member, user)


async def remove_member(
    db: AsyncSession, principal: Principal, project: Project, resource: Resource, user_id: UUID
) -> None:
    """Remove a direct membership. Owner/evaluator assignments are kept (they grant
    nothing without a member/admin role)."""
    member = await _direct_member(db, project, user_id)
    previous = member.role
    held = await research_assignment.roles_before(db, user_ids=[user_id], project_ids=[project.id])
    await db.delete(member)
    await _require_an_admin_left(db, principal, project, resource)
    await audit.record(
        db,
        "project.member_remove",
        actor=principal,
        target_type="user",
        target_id=user_id,
        project_id=project.id,
        details={"rule": Rule.PROJECT_MANAGE_MEMBERS, "from_role": previous},
    )
    # Phase 8b (product owner, review S1 b): leaving a private project ends one's research
    # assignments there (unless a group still gives a role).
    await research_assignment.end_after_role_loss(db, held, actor=principal)


# --- Rubric --------------------------------------------------------------------------------
def _weight(value: float) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


async def replace_rubric(
    db: AsyncSession, principal: Principal, project: Project, body: RubricUpdate
) -> Rubric:
    """Make the active rubric exactly ``body.criteria``, in order.

    Removed criteria are archived if scored (old evaluations keep them), else deleted.
    Active names are unique in the database (case-insensitively, not deferrable), so
    removals and renames are flushed before new criteria are inserted, and renamed
    criteria pass through a temporary name so two can swap names. Every idea's
    aggregate is recomputed.

    The caller holds the project row ``FOR UPDATE`` (``load_project(for_update=True)``)
    and idea writes hold ``FOR KEY SHARE`` on it before they lock their idea
    (:func:`app.services.ideas.load_idea`), so this runs strictly before or after
    every evaluation save in the project, never interleaved with one.
    """
    await require_unique_lower(
        db,
        [item.name for item in body.criteria],
        field="criteria",
        message="criterion names must be unique",
    )
    active = await _active_criteria(db, project.id)
    by_id = {criterion.id: criterion for criterion in active}
    unknown = [item.id for item in body.criteria if item.id is not None and item.id not in by_id]
    if unknown:
        raise ProblemError(
            422, "unknown_criterion", detail="A criterion id is not in this project's rubric."
        )
    kept = {item.id for item in body.criteria if item.id is not None}
    removed = [criterion for criterion in active if criterion.id not in kept]
    scored = set(
        await db.scalars(
            select(EvaluationScore.criterion_id)
            .where(EvaluationScore.criterion_id.in_([criterion.id for criterion in removed]))
            .distinct()
        )
    )
    now = utcnow()
    archived: list[UUID] = []
    deleted: list[UUID] = []
    for criterion in removed:
        if criterion.id in scored:
            criterion.archived_at = now
            archived.append(criterion.id)
        else:
            await db.delete(criterion)
            deleted.append(criterion.id)
    renamed = [
        by_id[item.id]
        for item in body.criteria
        if item.id is not None and by_id[item.id].name != item.name
    ]
    for criterion in renamed:
        criterion.name = f"~{criterion.id.hex}"  # unique, frees the old name
    await db.flush()

    criteria: list[RubricCriterion] = []
    added: list[UUID] = []
    for position, item in enumerate(body.criteria):
        values: dict[str, Any] = {
            "position": position,
            "name": item.name,
            "description": item.description,
            "weight": _weight(item.weight),
            "inverted": item.inverted,
            "guidance": dict(item.guidance),
        }
        if item.id is not None:
            criterion = by_id[item.id]
            for field, value in values.items():
                setattr(criterion, field, value)
        else:
            criterion = RubricCriterion(id=uuid4(), project_id=project.id, **values)
            added.append(criterion.id)
        criteria.append(criterion)
    await db.flush()  # updates of kept criteria first
    db.add_all(criterion for criterion in criteria if criterion.id in added)
    await db.flush()

    await recompute_aggregates(db, project_id=project.id)
    await audit.record(
        db,
        "project.rubric_replace",
        actor=principal,
        target_type="project",
        target_id=project.id,
        project_id=project.id,
        details={
            "rule": Rule.PROJECT_EDIT_RUBRIC,
            "criteria": [criterion.id for criterion in criteria],
            "added": added,
            "archived": archived,
            "deleted": deleted,
        },
    )
    return Rubric(criteria=[_criterion_out(criterion) for criterion in criteria])


# --- Tags ----------------------------------------------------------------------------------
async def list_tags(db: AsyncSession, principal: Principal, project: Project) -> list[TagInfo]:
    """Tags on at least one idea the principal can view, by name. ``idea_tags`` holds a
    tag once per idea, so ``count(*)`` counts ideas; the viewable ideas of *this*
    project are a hashed semi-join (performance review B6: 29 ms instead of 127 ms for
    a pending evaluator in a 10k-idea project, where the join probed every tagged idea)."""
    viewable = select(Idea.id).where(Idea.project_id == project.id, viewable_ideas(principal))
    rows = await db.execute(
        select(Tag.id, Tag.name, func.count())
        .join(IdeaTag, IdeaTag.tag_id == Tag.id)
        .where(Tag.project_id == project.id, IdeaTag.idea_id.in_(viewable))
        .group_by(Tag.id, Tag.name)
        .order_by(func.lower(Tag.name), Tag.id)
    )
    return [TagInfo(id=tag_id, name=name, idea_count=count) for tag_id, name, count in rows]
