"""Ideas: load by id or key, the idea page, create, edit, delete, status and owner
(contract sections 3.2 to 3.4).

Routers load the idea with :func:`load_idea` (404 unless the principal may view it,
optionally locking the row for a write), authorise the specific rule, then call a
command here. Commands record activity and audit entries in the same transaction and
the router returns :func:`idea_detail`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final
from uuid import UUID, uuid4

from sqlalchemy import delete, exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import (
    Decision,
    Resource,
    Rule,
    authorize,
    best_decision,
    effective_roles_of,
    idea_permissions,
    idea_resource,
    not_found,
    require,
    require_view,
)
from app.domain.idea_keys import IdeaKey, parse_idea_ref
from app.domain.principal import Principal
from app.errors import ProblemError
from app.models.activity import ActivityEvent
from app.models.enums import (
    EvaluationStatus,
    EvaluatorState,
    IdeaStatus,
    ProjectRole,
    ResearchStep,
)
from app.models.evaluation import Evaluation
from app.models.idea import Idea, IdeaEvaluator, IdeaTag, IdeaWatcher
from app.models.project import Project, Tag
from app.models.public import PublicSubmission
from app.models.user import User
from app.schemas.ideas import (
    AggregateScore,
    CriterionAggregate,
    IdeaCreate,
    IdeaDetail,
    IdeaUpdate,
    RecommendationCounts,
    StatusChange,
)
from app.schemas.ideas import (
    IdeaEvaluator as IdeaEvaluatorOut,
)
from app.schemas.research import crosses_gate, gated_statuses, starts_evaluation
from app.schemas.users import UserRef
from app.services import activity, audit, research
from app.services.scoring import active_criteria, idea_aggregate
from app.services.summaries import idea_row, load_context, summary_fields

__all__ = [
    "LoadedIdea",
    "assignee_roles",
    "change_status",
    "create_idea",
    "delete_idea",
    "idea_detail",
    "load_idea",
    "set_owner",
    "update_idea",
    "volunteer",
    "watch",
]

EDIT_RULES: Final = (Rule.IDEA_EDIT_OWN, Rule.IDEA_EDIT_ANY)
OWNER_CLEAR_RULES: Final = (Rule.IDEA_ASSIGN_OWNER, Rule.IDEA_RELEASE_OWNER)


@dataclass(frozen=True, slots=True)
class LoadedIdea:
    """An idea the principal may view, its project and the facts for decisions (as
    loaded: :func:`idea_detail` re-reads them after a change)."""

    idea: Idea
    project: Project
    resource: Resource


async def load_idea(
    db: AsyncSession, principal: Principal, ref: str, *, for_update: bool = False
) -> LoadedIdea:
    """The idea by UUID or key (any case); 404 when missing or not viewable.

    ``for_update`` locks the idea row until commit, so concurrent writes to one
    idea (e.g. two evaluators submitting) apply one after the other.

    Lock order: **project, then idea.** Project-wide writes (``replace_rubric``)
    lock the project row ``FOR UPDATE`` and then update every idea row, while an
    idea write that inserts a row referencing the project (an activity event) or a
    criterion (a score) needs the project row after the idea row. So ``for_update``
    first takes ``FOR KEY SHARE`` on the project row, in its own statement: idea
    writes in one project still run side by side (key-share locks don't conflict),
    but a rubric replacement waits for them and they wait for it, instead of
    deadlocking, recomputing from stale evaluations, or deleting a criterion that
    a save is scoring (tests/ideas/test_lock_order.py).
    """
    try:
        parsed = parse_idea_ref(ref)
    except ValueError:
        raise not_found() from None
    statement = select(Idea, Project).join(Project, Project.id == Idea.project_id)
    if isinstance(parsed, IdeaKey):
        statement = statement.where(Project.key == parsed.project_key, Idea.number == parsed.number)
    else:
        statement = statement.where(Idea.id == parsed)
    if for_update:
        key_share = statement.with_only_columns(Project.id).with_for_update(
            of=Project, read=True, key_share=True
        )
        if await db.scalar(key_share) is None:
            raise not_found()
        # A new statement (READ COMMITTED): it sees what a replacement we waited for wrote.
        statement = statement.with_for_update(of=Idea)
    row = (await db.execute(statement)).first()
    if row is None:
        raise not_found()
    idea, project = row
    resource = await idea_resource(db, principal, idea, project)
    require_view(principal, resource)
    return LoadedIdea(idea, project, resource)


async def assignee_roles(
    db: AsyncSession, project_id: UUID, user_ids: Sequence[UUID]
) -> dict[UUID, ProjectRole | None]:
    """Effective roles for c4; unknown and deactivated users have none."""
    roles = await effective_roles_of(db, project_id, user_ids)
    active = set(await db.scalars(select(User.id).where(User.id.in_(list(roles)), User.is_active)))
    return {user_id: role if user_id in active else None for user_id, role in roles.items()}


async def watch(db: AsyncSession, idea: Idea, user_id: UUID) -> None:
    await db.execute(
        insert(IdeaWatcher).values(idea_id=idea.id, user_id=user_id).on_conflict_do_nothing()
    )


# --- The idea page ---------------------------------------------------------------------------
async def _evaluators(db: AsyncSession, principal: Principal, idea: Idea) -> list[IdeaEvaluatorOut]:
    rows = await db.execute(
        select(IdeaEvaluator, User, Evaluation.status, Evaluation.submitted_at)
        .join(User, User.id == IdeaEvaluator.user_id)
        .outerjoin(
            Evaluation,
            (Evaluation.idea_id == IdeaEvaluator.idea_id)
            & (Evaluation.evaluator_id == IdeaEvaluator.user_id),
        )
        .where(IdeaEvaluator.idea_id == idea.id)
        .order_by(IdeaEvaluator.invited_at, func.lower(User.display_name), User.id)
    )
    evaluators = []
    for assignment, user, status, submitted_at in rows:
        submitted = status is EvaluationStatus.SUBMITTED
        if submitted:
            state = EvaluatorState.SUBMITTED
        elif status is EvaluationStatus.DRAFT and user.id == principal.user_id:
            state = EvaluatorState.DRAFT  # drafts are private to their author
        else:
            state = EvaluatorState.INVITED
        evaluators.append(
            IdeaEvaluatorOut(
                user=UserRef.model_validate(user),
                state=state,
                is_ai=user.is_service_account,
                invited_at=assignment.invited_at,
                submitted_at=submitted_at if submitted else None,
            )
        )
    return evaluators


async def _aggregate(db: AsyncSession, idea: Idea) -> AggregateScore | None:
    rubric = (await active_criteria(db, [idea.project_id])).get(idea.project_id, [])
    result = await idea_aggregate(db, idea, rubric)
    if result is None or result.overall is None:
        return None
    by_id = {criterion.id: criterion for criterion in rubric}
    return AggregateScore(
        overall=float(result.overall),
        count=result.count,
        high_disagreement=result.high_disagreement,
        criteria=[
            CriterionAggregate(
                criterion_id=stats.criterion_id,
                name=by_id[stats.criterion_id].name,
                weight=float(by_id[stats.criterion_id].weight),
                inverted=by_id[stats.criterion_id].inverted,
                mean=float(stats.mean),
                min=stats.min,
                max=stats.max,
                spread=stats.spread,
                count=stats.count,
            )
            for stats in result.criteria
        ],
        recommendations=RecommendationCounts(
            **{key.value: count for key, count in result.recommendations.items()}
        ),
    )


async def idea_detail(
    db: AsyncSession, principal: Principal, loaded: LoadedIdea, *, reread: bool = True
) -> IdeaDetail:
    """The idea page as the principal may see it (blind evaluation applied).

    After a write the principal's facts are re-read, so the flags reflect the change
    just made (a new owner, a submitted evaluation, a closed idea); a plain read
    (``reread=False``, ``GET /ideas/{idea}``) uses the facts it was loaded with
    (performance review B6: two statements fewer).
    """
    idea, project = loaded.idea, loaded.project
    resource = await idea_resource(db, principal, idea, project) if reread else loaded.resource
    visible = authorize(principal, Rule.SCORE_VIEW_AGGREGATE, resource).allowed
    row = await idea_row(db, principal, idea, score_visible=visible)
    context = await load_context(
        db,
        principal,
        [row],
        projects={project.id: project},
        roles={project.id: resource.role} if resource.role else {},
        extra_users=[idea.submitted_by_id],
    )
    fields = summary_fields(principal, row, context)
    permissions = idea_permissions(principal, resource)
    progress = context.research.get(idea.id)
    if (
        permissions.can_invite_evaluators
        and progress is not None
        and progress.required_open > 0
        and starts_evaluation(project.research_step, idea.status, row.evaluators)
    ):
        # Phase 8: the first invite would cross the research gate (409 research_incomplete).
        permissions = permissions.model_copy(update={"invite_blocked_by_research": True})
    fields["permissions"] = permissions
    watching, via_public_form = (
        await db.execute(
            select(
                exists().where(
                    IdeaWatcher.idea_id == idea.id, IdeaWatcher.user_id == principal.user_id
                ),
                exists().where(PublicSubmission.idea_id == idea.id),
            )
        )
    ).one()
    return IdeaDetail(
        **fields,
        description_md=idea.description_md,
        submitted_by=context.users.get(idea.submitted_by_id) if idea.submitted_by_id else None,
        evaluators=await _evaluators(db, principal, idea),
        evaluation_due_at=idea.evaluation_due_at,
        evaluation_closed_at=idea.evaluation_closed_at,
        evaluation_open=resource.idea is not None and resource.idea.evaluation_open,
        aggregate=await _aggregate(db, idea) if visible else None,
        watching=bool(watching),
        held_for=idea.held_for,
        via_public_form=bool(via_public_form),
    )


# --- Tags ------------------------------------------------------------------------------------
async def _resolve_tags(db: AsyncSession, project_id: UUID, names: Sequence[str]) -> list[Tag]:
    """The project's tags with these names (case-insensitive), created on first use.

    ``ON CONFLICT DO NOTHING`` on the ``lower(name)`` unique index keeps the first
    spelling and makes concurrent first uses safe.
    """
    if not names:
        return []
    await db.execute(
        insert(Tag)
        .values([{"id": uuid4(), "project_id": project_id, "name": name} for name in names])
        .on_conflict_do_nothing()
    )
    tags = await db.scalars(
        select(Tag).where(
            Tag.project_id == project_id,
            or_(*(func.lower(Tag.name) == func.lower(name) for name in names)),
        )
    )
    return list(tags)


async def _tag_ids(db: AsyncSession, idea: Idea) -> set[UUID]:
    return set(await db.scalars(select(IdeaTag.tag_id).where(IdeaTag.idea_id == idea.id)))


async def _set_tags(db: AsyncSession, idea: Idea, tags: Sequence[Tag]) -> bool:
    """Make the idea's tags exactly ``tags``; true if that changed anything."""
    wanted = {tag.id for tag in tags}
    current = await _tag_ids(db, idea)
    if wanted == current:
        return False
    if current - wanted:
        await db.execute(
            delete(IdeaTag).where(IdeaTag.idea_id == idea.id, IdeaTag.tag_id.in_(current - wanted))
        )
    if wanted - current:
        await db.execute(
            insert(IdeaTag).values(
                [{"idea_id": idea.id, "tag_id": tag_id} for tag_id in wanted - current]
            )
        )
    return True


# --- Commands --------------------------------------------------------------------------------
async def create_idea(
    db: AsyncSession, principal: Principal, project: Project, body: IdeaCreate
) -> Idea:
    """``idea.create`` (checked by the caller). The number comes from an atomic
    ``UPDATE ... RETURNING`` on the project row, which also serialises concurrent
    creates in the project: numbers are unique and never reused."""
    number = await db.scalar(
        update(Project)
        .where(Project.id == project.id)
        .values(next_idea_number=Project.next_idea_number + 1)
        .returning(Project.next_idea_number - 1)
        .execution_options(synchronize_session=False)
    )
    assert number is not None  # noqa: S101 - the project row exists (we loaded it)
    idea = Idea(
        id=uuid4(),
        project_id=project.id,
        number=number,
        title=body.title,
        summary=body.summary,
        description_md=body.description_md,
        status=IdeaStatus.NEW,
        submitted_by_id=principal.user_id,
    )
    db.add(idea)
    await db.flush()
    await _set_tags(db, idea, await _resolve_tags(db, project.id, body.tags))
    await watch(db, idea, principal.user_id)
    await activity.emit(db, idea, "idea_created", actor=principal)
    await db.flush()
    return idea


async def update_idea(
    db: AsyncSession, principal: Principal, loaded: LoadedIdea, body: IdeaUpdate
) -> None:
    """Submitter while new (c1), owner while not closed (c5), admins always; anyone
    else who can view the idea gets 403 ``not_submitter`` (contract section 3.2)."""
    decision = best_decision(authorize(principal, rule, loaded.resource) for rule in EDIT_RULES)
    if not decision.allowed:
        raise _edit_problem(decision)
    idea = loaded.idea
    changed: list[str] = []
    for field in ("title", "summary", "description_md"):
        value = getattr(body, field)
        if value is not None and value != getattr(idea, field):
            setattr(idea, field, value)
            changed.append(field)
    if body.tags is not None:
        tags = await _resolve_tags(db, loaded.project.id, body.tags)
        if await _set_tags(db, idea, tags):
            changed.append("tags")
    if changed:
        await activity.emit(db, idea, "idea_edited", actor=principal, payload={"fields": changed})
        await db.flush()


def _edit_problem(decision: Decision) -> ProblemError:
    if decision.status == 403 and decision.code == "forbidden":
        return ProblemError(
            403, "not_submitter", detail="Only the person who submitted this idea can edit it."
        )
    return decision.problem()


async def delete_idea(db: AsyncSession, principal: Principal, loaded: LoadedIdea) -> None:
    """``idea.delete``: a hard delete; the database cascades to everything under it."""
    require(principal, Rule.IDEA_DELETE, loaded.resource)
    idea = loaded.idea
    await audit.record(
        db,
        "idea.delete",
        actor=principal,
        target_type="idea",
        target_id=idea.id,
        project_id=idea.project_id,
        details={"rule": Rule.IDEA_DELETE, "number": idea.number},
    )
    await db.delete(idea)
    await db.flush()


async def _closed_from(db: AsyncSession, idea_id: UUID) -> IdeaStatus | None:
    """The status a closed idea was closed from: the ``from_status`` of its latest
    ``status_changed`` event into Closed from an open status (a re-resolution, Closed ->
    Closed, doesn't count). ``None`` when there is no such event (counts as New)."""
    payload = ActivityEvent.payload
    found = await db.scalar(
        select(payload["from_status"].astext)
        .where(
            ActivityEvent.idea_id == idea_id,
            ActivityEvent.type == "status_changed",
            payload["to_status"].astext == IdeaStatus.CLOSED.value,
            payload["from_status"].astext != IdeaStatus.CLOSED.value,
        )
        .order_by(ActivityEvent.created_at.desc(), ActivityEvent.id.desc())
        .limit(1)
    )
    try:
        return IdeaStatus(found) if found else None
    except ValueError:  # pragma: no cover - payloads hold IdeaStatus values
        return None


async def change_status(
    db: AsyncSession,
    principal: Principal,
    loaded: LoadedIdea,
    body: StatusChange,
    *,
    operation: str = "change_idea_status",
) -> None:
    """Any status of the project's lifecycle to any other; no side effects, so the inverse
    call undoes it. The only code that changes an idea's status (the API, the board, Undo,
    and ``create_proposal``'s move: ``operation`` names the request for the audit).

    Phase 8 (contract-phase8 section 3.5): ``research`` needs the project's research step
    (409 ``research_step_off``); a move that crosses the research gate
    (:func:`app.schemas.research.crosses_gate`; reopening counts from the status the idea
    was closed from, read under the idea's lock) runs the research check, which refuses
    it (409 ``research_incomplete``) while required items are open unless an admin moves
    anyway (``override_research``, audited)."""
    research.require_guarded(principal, Rule.IDEA_CHANGE_STATUS, loaded.resource, body)
    idea, step = loaded.idea, loaded.project.research_step
    if body.status is IdeaStatus.RESEARCH and step is ResearchStep.OFF:
        raise research.ResearchStepOffProblem
    before = (idea.status, idea.resolution)
    after = (body.status, body.resolution if body.status is IdeaStatus.CLOSED else None)
    if before == after:
        return
    closed_from = None
    if idea.status is IdeaStatus.CLOSED and body.status in gated_statuses(step):
        closed_from = await _closed_from(db, idea.id)
    overridden = False
    if crosses_gate(step, idea.status, body.status, closed_from=closed_from):
        overridden = await research.check_gate(
            db,
            principal,
            idea,
            loaded.resource,
            operation=operation,
            from_status=idea.status,
            to_status=body.status,
            override=body,
        )
    idea.status, idea.resolution = after
    payload: dict[str, object] = {
        "from_status": before[0],
        "from_resolution": before[1],
        "to_status": after[0],
        "to_resolution": after[1],
    }
    if overridden:
        payload["research_overridden"] = True
    if IdeaStatus.RESEARCH in (before[0], after[0]):
        # Code review L3: public tracking reads Research with the step of the time, so
        # moving the step later never rewrites a submitter's history.
        payload["research_step"] = step
    await activity.emit(db, idea, "status_changed", actor=principal, payload=payload)
    await audit.record(
        db,
        "idea.status_change",
        actor=principal,
        target_type="idea",
        target_id=idea.id,
        project_id=idea.project_id,
        details={
            "rule": Rule.IDEA_CHANGE_STATUS,
            "from_status": before[0],
            "from_resolution": before[1],
            "to_status": after[0],
            "to_resolution": after[1],
        },
    )
    await db.flush()


async def _change_owner(
    db: AsyncSession,
    principal: Principal,
    loaded: LoadedIdea,
    owner_id: UUID | None,
    *,
    rule: Rule,
    volunteered: bool = False,
) -> None:
    idea = loaded.idea
    previous = idea.owner_id
    if previous == owner_id:
        return
    idea.owner_id = owner_id
    if owner_id is not None:
        await watch(db, idea, owner_id)
    await activity.emit(
        db,
        idea,
        "owner_changed",
        actor=principal,
        payload={"from_owner_id": previous, "to_owner_id": owner_id, "volunteered": volunteered},
    )
    await audit.record(
        db,
        "idea.owner_change",
        actor=principal,
        target_type="idea",
        target_id=idea.id,
        project_id=idea.project_id,
        details={"rule": rule, "from_owner_id": previous, "to_owner_id": owner_id},
    )
    await db.flush()


async def set_owner(
    db: AsyncSession, principal: Principal, loaded: LoadedIdea, owner_id: UUID | None
) -> None:
    """Admins assign anyone eligible (c4) or clear it; the owner may only step down."""
    resource = loaded.resource
    if owner_id is None:
        decision = best_decision(authorize(principal, rule, resource) for rule in OWNER_CLEAR_RULES)
        if not decision.allowed:
            raise decision.problem()
        rule = decision.rule
    else:
        roles = await assignee_roles(db, loaded.project.id, [owner_id])
        service_account = bool(
            await db.scalar(select(User.is_service_account).where(User.id == owner_id))
        )
        rule = Rule.IDEA_ASSIGN_OWNER
        require(
            principal,
            rule,
            resource.replace(
                assignee_roles=(roles[owner_id],), assignee_service_account=service_account
            ),
        )
    await _change_owner(db, principal, loaded, owner_id, rule=rule)


async def volunteer(db: AsyncSession, principal: Principal, loaded: LoadedIdea) -> None:
    """ "I'll own this": c3 (members), c4 (a real role), c13 (unowned), c5 (not closed)."""
    require(principal, Rule.IDEA_VOLUNTEER_OWNER, loaded.resource)
    await _change_owner(
        db,
        principal,
        loaded,
        principal.user_id,
        rule=Rule.IDEA_VOLUNTEER_OWNER,
        volunteered=True,
    )
