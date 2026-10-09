"""Who does an idea's research (Phase 8b, product owner 2026-10-08; contract-phase8b
sections 3 and 17).

* :func:`set_assignment` (``set_research_assignment``, ``idea.assign_researcher``: the
  owner, project admins and platform admins; c5, c23, c25) and :func:`remove_researcher`
  (also ``idea.release_researcher``: the researcher's "Hand back"). The caller holds the
  idea ``FOR UPDATE`` (``load_idea(for_update=True)``: the project ``FOR KEY SHARE``
  first); once the caller may assign at all (review N2: so a viewer never takes the
  lock), a new researcher's user row is locked ``FOR SHARE`` before their eligibility
  (c23) and role (c25) are read, so a deactivation or a removal from the project that
  commits meanwhile is seen. Due dates are stored and reported in UTC (review N1, as
  evaluation due dates are).
* **Automatic clears** (:func:`clear_idea`, :func:`clear_where`): closing the idea,
  turning the project's step off, deactivating the researcher and (product owner, review
  S1 b) losing one's role in a private project (:func:`roles_before`,
  :func:`end_after_role_loss`). Nobody is assigned afterwards (the owner does the
  research), the due date and answers are kept, one ``idea.researcher_change`` audit entry
  per idea, no feed event or notification.
* :func:`assignment_out`: the Research panel's ``assignment``.

Lock order everywhere: projects ``FOR KEY SHARE`` (by id), then ideas ``FOR UPDATE`` (by
id), then a user ``FOR SHARE``; paths that change roles hold the project ``FOR UPDATE`` or
the user's sync lock first (contract-phase8b section 17).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Literal
from uuid import UUID

from sqlalchemy import ColumnElement, and_, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import NamedResearcher, Resource, Rule, effective_role_of, require, require_any
from app.domain.principal import Principal
from app.models.base import utcnow
from app.models.enums import ProjectVisibility, ResearchStep
from app.models.idea import Idea, IdeaWatcher
from app.models.project import Project, project_effective_roles
from app.models.user import User
from app.schemas.research import ResearchAssignment, ResearchAssignmentUpdate, awaits_research
from app.schemas.users import UserRef
from app.services import activity, audit

__all__ = [
    "ClearReason",
    "RoleSnapshot",
    "assignment_out",
    "clear_idea",
    "clear_where",
    "end_after_role_loss",
    "remove_researcher",
    "roles_before",
    "set_assignment",
]

ClearReason = Literal["deactivated", "closed", "step_off", "left_project"]
"""``details.reason`` of an automatic clear (contract-phase8b sections 3.5 and 17)."""

_roles = project_effective_roles

_ASSIGN_RULES: Final = (Rule.IDEA_ASSIGN_RESEARCHER, Rule.IDEA_RELEASE_RESEARCHER)


def _step_off() -> Exception:
    from app.services.research import ResearchStepOffProblem

    return ResearchStepOffProblem()


async def _named(db: AsyncSession, project: Project, user_id: UUID) -> NamedResearcher:
    """c23 and c25 for the person named: their user row locked ``FOR SHARE`` first."""
    user = await db.scalar(
        select(User)
        .where(User.id == user_id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if user is None:
        return NamedResearcher(eligible=False)
    eligible = user.is_active and not user.is_service_account and not user.is_break_glass
    return NamedResearcher(eligible=eligible, role=await effective_role_of(db, user_id, project.id))


def _same_moment(a: datetime | None, b: datetime | None) -> bool:
    return a == b  # aware datetimes compare across offsets


async def _audit(
    db: AsyncSession,
    idea: Idea,
    *,
    actor: Principal | UUID | None,
    from_user: UUID | None,
    to_user: UUID | None,
    reason: str,
    rule: Rule | None = None,
    outside_project: bool = False,
) -> None:
    details: dict[str, object] = {
        "from_user_id": from_user,
        "to_user_id": to_user,
        "reason": reason,
        "outside_project": outside_project,
    }
    if rule is not None:
        details["rule"] = rule
    await audit.record(
        db,
        "idea.researcher_change",
        actor=actor,
        target_type="idea",
        target_id=idea.id,
        project_id=idea.project_id,
        details=details,
    )


async def set_assignment(
    db: AsyncSession,
    principal: Principal,
    idea: Idea,
    project: Project,
    resource: Resource,
    body: ResearchAssignmentUpdate,
) -> None:
    """``set_research_assignment`` (contract-phase8b section 3.3): the complete new state,
    idempotent, last write wins. Checks: 403 (the rule; c25) -> 422 (c23) -> 409
    (archived, c19, c5) -> 409 ``research_step_off``."""
    changes_researcher = body.researcher_id != idea.researcher_id
    # Review N2: the rule with nobody named first (the owner or an admin), so someone who
    # may only view the idea never locks the named person's row; then c23 and c25.
    require(principal, Rule.IDEA_ASSIGN_RESEARCHER, resource)
    named = None
    if changes_researcher and body.researcher_id is not None:
        named = await _named(db, project, body.researcher_id)
        require(principal, Rule.IDEA_ASSIGN_RESEARCHER, resource.replace(researcher_named=named))
    if project.research_step is ResearchStep.OFF:
        raise _step_off()
    if changes_researcher:
        previous = idea.researcher_id
        # Review N3: the researcher (an admin, say) clearing it themselves hands it back,
        # whichever request says so.
        handed_back = body.researcher_id is None and previous == principal.user_id
        idea.researcher_id = body.researcher_id
        idea.research_assigned_at = utcnow() if body.researcher_id is not None else None
        if body.researcher_id is not None:  # a new researcher watches the idea
            await db.execute(
                insert(IdeaWatcher)
                .values(idea_id=idea.id, user_id=body.researcher_id)
                .on_conflict_do_nothing()
            )
        await activity.emit(
            db,
            idea,
            "researcher_changed",
            actor=principal,
            payload={
                "from_researcher_id": previous,
                "to_researcher_id": body.researcher_id,
                "handed_back": handed_back,
            },
        )
        reason = "assigned" if body.researcher_id is not None else "removed"
        await _audit(
            db,
            idea,
            actor=principal,
            from_user=previous,
            to_user=body.researcher_id,
            reason="handed_back" if handed_back else reason,
            rule=Rule.IDEA_ASSIGN_RESEARCHER,
            outside_project=named is not None and named.role is None,
        )
    due_at = body.due_at.astimezone(UTC) if body.due_at is not None else None  # review N1
    if not _same_moment(due_at, idea.research_due_at):
        previous_due = idea.research_due_at
        idea.research_due_at = due_at
        await activity.emit(
            db,
            idea,
            "research_due_date_changed",
            actor=principal,
            payload={"from_due_at": previous_due, "to_due_at": due_at},
        )
    await db.flush()


async def remove_researcher(
    db: AsyncSession, principal: Principal, idea: Idea, project: Project, resource: Resource
) -> None:
    """``remove_researcher``: "Remove" (``idea.assign_researcher``) or "Hand back"
    (``idea.release_researcher``, the researcher). Nobody is assigned afterwards; the due
    date is kept. 204 also when nobody was assigned (no event)."""
    rule = require_any(principal, _ASSIGN_RULES, resource)
    if project.research_step is ResearchStep.OFF:
        raise _step_off()
    previous = idea.researcher_id
    if previous is None:
        return
    handed_back = previous == principal.user_id
    idea.researcher_id = None
    idea.research_assigned_at = None
    await activity.emit(
        db,
        idea,
        "researcher_changed",
        actor=principal,
        payload={
            "from_researcher_id": previous,
            "to_researcher_id": None,
            "handed_back": handed_back,
        },
    )
    await _audit(
        db,
        idea,
        actor=principal,
        from_user=previous,
        to_user=None,
        reason="handed_back" if handed_back else "removed",
        rule=rule,
    )
    await db.flush()


# --- Automatic clears --------------------------------------------------------------------
async def clear_idea(
    db: AsyncSession, idea: Idea, *, actor: Principal | UUID | None, reason: ClearReason
) -> None:
    """Clear one idea's assignment (the caller holds the idea's lock): closing it."""
    previous = idea.researcher_id
    if previous is None:
        return
    idea.researcher_id = None
    idea.research_assigned_at = None
    await _audit(db, idea, actor=actor, from_user=previous, to_user=None, reason=reason)
    await db.flush()


async def clear_where(
    db: AsyncSession,
    condition: ColumnElement[bool],
    *,
    actor: Principal | UUID | None,
    reason: ClearReason,
) -> int:
    """Clear every assignment matching ``condition`` (over ``ideas``): their projects
    ``FOR KEY SHARE``, then the ideas ``FOR UPDATE``, each by id, re-checked under the lock.
    Returns how many were cleared."""
    wanted = and_(Idea.researcher_id.is_not(None), condition)
    project_ids = sorted(set(await db.scalars(select(Idea.project_id).where(wanted))))
    if not project_ids:
        return 0
    await db.execute(
        select(Project.id)
        .where(Project.id.in_(project_ids))
        .order_by(Project.id)
        .with_for_update(read=True, key_share=True)
    )
    ideas = list(
        await db.scalars(
            select(Idea)
            .where(wanted)
            .order_by(Idea.id)
            .with_for_update(of=Idea)
            .execution_options(populate_existing=True)
        )
    )
    for idea in ideas:
        await clear_idea(db, idea, actor=actor, reason=reason)
    return len(ideas)


# --- Losing one's role in a private project (product owner, review S1 b) ------------------
@dataclass(frozen=True, slots=True)
class RoleSnapshot:
    """Assignments in private projects whose researcher held a role there before a change:
    ``(idea id, project id, researcher id)``."""

    held: tuple[tuple[UUID, UUID, UUID], ...] = ()


async def roles_before(
    db: AsyncSession,
    *,
    user_ids: Iterable[UUID] | None = None,
    project_ids: Iterable[UUID] | None = None,
) -> RoleSnapshot:
    """Take before a change that may take roles away (the caller holds the project
    ``FOR UPDATE`` or the user's sync lock)."""
    statement = (
        select(Idea.id, Idea.project_id, Idea.researcher_id)
        .join(Project, Project.id == Idea.project_id)
        .join(
            _roles,
            and_(_roles.c.project_id == Idea.project_id, _roles.c.user_id == Idea.researcher_id),
        )
        .where(Idea.researcher_id.is_not(None), Project.visibility == ProjectVisibility.PRIVATE)
    )
    if user_ids is not None:
        users = list(user_ids)
        if not users:
            return RoleSnapshot()
        statement = statement.where(Idea.researcher_id.in_(users))
    if project_ids is not None:
        projects = list(project_ids)
        if not projects:
            return RoleSnapshot()
        statement = statement.where(Idea.project_id.in_(projects))
    rows = await db.execute(statement)
    return RoleSnapshot(
        held=tuple((idea, project, user) for idea, project, user in rows.all() if user is not None)
    )


async def end_after_role_loss(
    db: AsyncSession, before: RoleSnapshot, *, actor: Principal | UUID | None
) -> int:
    """After the change: clear the assignments of :func:`roles_before` whose researcher
    has no role in the project now (audited ``left_project``). Someone who never had a
    role there (an outsider an admin named) is never in the snapshot."""
    if not before.held:
        return 0
    await db.flush()  # the change itself, so the view sees it
    pairs = {(project, user) for _, project, user in before.held}
    still = set(
        (
            await db.execute(
                select(_roles.c.project_id, _roles.c.user_id).where(
                    tuple_(_roles.c.project_id, _roles.c.user_id).in_(sorted(pairs))
                )
            )
        ).all()
    )
    lost = sorted(
        (idea, user) for idea, project, user in before.held if (project, user) not in still
    )
    if not lost:
        return 0
    return await clear_where(
        db,
        tuple_(Idea.id, Idea.researcher_id).in_(lost),
        actor=actor,
        reason="left_project",
    )


# --- The panel ---------------------------------------------------------------------------
async def assignment_out(
    db: AsyncSession, idea: Idea, project: Project, *, required_open: int
) -> ResearchAssignment:
    """Who does the research and by when (nothing while the step is off)."""
    step = project.research_step
    if step is ResearchStep.OFF:
        return ResearchAssignment()
    researcher = None
    in_project = False
    if idea.researcher_id is not None:
        user = await db.get(User, idea.researcher_id)
        if user is not None:
            researcher = UserRef.model_validate(user)
            in_project = await effective_role_of(db, user.id, project.id) is not None
    due = idea.research_due_at
    overdue = (
        due is not None
        and due < utcnow()
        and required_open > 0
        and awaits_research(step, idea.status)
    )
    return ResearchAssignment(
        researcher=researcher,
        researcher_in_project=in_project,
        assigned_at=idea.research_assigned_at if researcher is not None else None,
        due_at=due,
        overdue=overdue,
    )


def ideas_of(users: Sequence[UUID]) -> ColumnElement[bool]:
    """The ideas these people research (deactivation)."""
    return Idea.researcher_id.in_(list(users))
