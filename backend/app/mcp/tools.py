"""The MCP tools (contract-phase5 section 4.3, and Phase 6's ``add_research_note``), each a
thin adapter over the services the REST endpoints use.

Every tool gets a :class:`ToolContext` (the unit of work, the key's principal, the
settings and the audit target) and its validated ``*Input`` model, and returns its
``*Output`` model. Authorisation, blind evaluation, holds, conditions and locks are the
REST API's by construction: the tools load ideas with :func:`app.services.ideas.load_idea`
(404 unless the owner may see it and the key reaches its project), check the tool's rule
through the policy (the key's scopes: ``insufficient_scope`` after the 404s), and build
results from the REST builders' output (``idea_detail``, ``list_evaluations``,
``my_evaluation``, the summary builder), which already mask scores for a pending
evaluator. Two things are stricter than REST, on purpose:

* **Held ideas are not found**, for everyone (:func:`_idea`): no tool moderates, and
  text waiting for review must not reach an agent.
* **Results are bounded** (the latest comments and evaluations, long texts cut with
  ``truncated``) and carry no public submitter's name.
* **AI agents act only inside their runs** (c22, :mod:`app.ai.scope`): after the idea is
  found (``not_found`` first), an agent's call must target the idea of one of its open
  runs (``ai_run_not_active``), lists show only those ideas, and its only write is the
  run kind's tool, whose result is attached to the run (:mod:`app.ai.results`).
  ``create_idea`` and ``add_comment`` are ``forbidden`` for agents. Rule 9: agents see
  no other evaluator's score data (the policy treats them as pending evaluators).

The write tools pass their input model, a subclass of the REST request model, to the
REST service as its body, so limits and cross-field rules can't drift.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Final
from urllib.parse import quote
from uuid import UUID

from sqlalchemy import ColumnElement, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import notes as ai_notes
from app.ai import results as ai_results
from app.ai import scope as ai_scope
from app.authz import (
    ASSIGNABLE_ROLES,
    Decision,
    Rule,
    authorize,
    can,
    listed_ideas,
    load_project,
    not_found,
    require,
)
from app.authz.queries import pending_ideas
from app.config import Settings
from app.domain.idea_keys import parse_idea_key
from app.domain.principal import Principal
from app.mcp.audit import AuditTarget
from app.models.activity import Comment
from app.models.enums import (
    AiRunKind,
    EvaluationStatus,
    EvaluatorState,
    IdeaStatus,
    Recommendation,
    SuggestionSource,
)
from app.models.evaluation import Evaluation, EvaluationScore
from app.models.idea import Idea
from app.models.project import Project, RubricCriterion, project_effective_roles
from app.models.public import PublicSubmission
from app.models.user import User
from app.proposals import service as proposal_service
from app.proposals import suggestions
from app.schemas.evaluations import MyEvaluation
from app.schemas.ideas import IdeaRef
from app.schemas.mcp import (
    MCP_EVALUATIONS_MAX,
    MCP_TEXT_LIMIT,
    AddCommentInput,
    AddCommentOutput,
    AddResearchNoteInput,
    AddResearchNoteOutput,
    CreateIdeaInput,
    CreateIdeaOutput,
    GetIdeaInput,
    GetIdeaOutput,
    GetProposalInput,
    GetProposalOutput,
    GetRubricInput,
    GetRubricOutput,
    ListProjectsInput,
    ListProjectsOutput,
    McpCitation,
    McpComment,
    McpEvaluation,
    McpEvaluator,
    McpIdeaDetail,
    McpIdeaPermissions,
    McpIdeaRef,
    McpIdeaSummary,
    McpMyEvaluation,
    McpOutput,
    McpProject,
    McpProjectRef,
    McpProposal,
    McpProposalSuggestion,
    McpRubricCriterion,
    McpScore,
    McpScoreEntry,
    McpUser,
    ProposeProposalSectionInput,
    ProposeProposalSectionOutput,
    SearchIdeasInput,
    SearchIdeasOutput,
    SubmitEvaluationInput,
    SubmitEvaluationOutput,
)
from app.services import comments, evaluations, ideas, projects
from app.services.board import Sort, fetch_page
from app.services.ideas import LoadedIdea
from app.services.refs import idea_ref
from app.services.scoring import active_criteria
from app.services.summaries import load_context, summary_fields
from app.services.users import escape_like

__all__ = ["TOOLS", "ToolContext", "ToolFunction", "cut"]


@dataclass(slots=True)
class ToolContext:
    """One ``tools/call``: its unit of work, the key's principal, the settings, and what
    the call is about (for its ``mcp.call`` entry)."""

    db: AsyncSession
    principal: Principal
    settings: Settings
    target: AuditTarget = field(default_factory=AuditTarget)
    recorded: list[tuple[UUID, AiRunKind]] = field(default_factory=list)
    """Runs this call attached a result to (an agent's write): the dispatcher adds their
    ``result_recorded`` events after the transaction."""


ToolFunction = Callable[[ToolContext, Any], Awaitable[McpOutput]]


# --- Shared pieces ------------------------------------------------------------------------
def cut(text: str, limit: int = MCP_TEXT_LIMIT) -> tuple[str, bool]:
    """``text`` cut to ``limit`` characters, and whether it was."""
    return (text[:limit], True) if len(text) > limit else (text, False)


def _require_read(principal: Principal, rule: Rule) -> None:
    """Tools that list check their scope first (contract-phase5 section 4.2): a key
    without ``read`` lists nothing and says why."""
    if not principal.has_scope("read"):
        raise Decision(rule, False, 403, "insufficient_scope").problem()


async def _idea(ctx: ToolContext, ref: str, *, for_update: bool = False) -> LoadedIdea:
    """The idea as REST loads it (404 unless the owner may view it and the key reaches
    its project), then **not found while held** for everyone, admins included."""
    loaded = await ideas.load_idea(ctx.db, ctx.principal, ref, for_update=for_update)
    ctx.target.idea(loaded.idea.id, loaded.project.id)
    if loaded.idea.held_for is not None:
        raise not_found()
    return loaded


async def _users(db: AsyncSession, ids: Iterable[UUID | None]) -> dict[UUID, McpUser]:
    wanted = {user_id for user_id in ids if user_id is not None}
    if not wanted:
        return {}
    rows = await db.execute(
        select(User.id, User.display_name, User.is_service_account).where(User.id.in_(wanted))
    )
    return {
        user_id: McpUser(id=user_id, display_name=name, is_ai=is_ai)
        for user_id, name, is_ai in rows
    }


def _url(settings: Settings, key: str) -> str:
    """The idea's page, from the configured base URL (never the ``Host`` header)."""
    return f"{settings.public_base_url}/ideas/{quote(key)}"


def _project_ref(ref: Any) -> McpProjectRef:
    return McpProjectRef(id=ref.id, slug=ref.slug, key=ref.key, name=ref.name)


def _ref_out(ref: IdeaRef, settings: Settings) -> McpIdeaRef:
    return McpIdeaRef(
        id=ref.id,
        key=ref.key,
        title=ref.title,
        project=_project_ref(ref.project),
        status=ref.status,
        resolution=ref.resolution,
        status_label=ref.status_label,
        url=_url(settings, ref.key),
    )


def _idea_ref(ctx: ToolContext, loaded: LoadedIdea) -> McpIdeaRef:
    return _ref_out(idea_ref(loaded.idea, loaded.project), ctx.settings)


async def _criteria(db: AsyncSession, project_id: UUID) -> list[RubricCriterion]:
    return (await active_criteria(db, [project_id])).get(project_id, [])


async def _public_ideas(db: AsyncSession, idea_ids: Iterable[UUID]) -> set[UUID]:
    wanted = list(idea_ids)
    if not wanted:
        return set()
    found = await db.scalars(
        select(PublicSubmission.idea_id).where(PublicSubmission.idea_id.in_(wanted))
    )
    return set(found)


def _citations(stored: object) -> list[McpCitation]:
    if not isinstance(stored, list):
        return []
    return [
        McpCitation(title=str(item.get("title", "")), url=str(item.get("url", "")))
        for item in stored
        if isinstance(item, dict)
    ]


async def _own_sources(
    db: AsyncSession, principal: Principal, idea_id: UUID
) -> dict[UUID, list[McpCitation]]:
    """An AI evaluator's own cited sources per criterion (people cite none)."""
    if not ai_scope.is_agent(principal):
        return {}
    rows = await db.execute(
        select(EvaluationScore.criterion_id, EvaluationScore.sources)
        .join(Evaluation, Evaluation.id == EvaluationScore.evaluation_id)
        .where(Evaluation.idea_id == idea_id, Evaluation.evaluator_id == principal.user_id)
    )
    return {criterion_id: _citations(sources) for criterion_id, sources in rows}


def _my_out(
    mine: MyEvaluation,
    names: dict[UUID, str],
    sources: dict[UUID, list[McpCitation]] | None = None,
) -> McpMyEvaluation:
    sources = sources or {}
    return McpMyEvaluation(
        state=mine.state,
        editable=mine.editable,
        due_at=mine.due_at,
        recommendation=mine.recommendation,
        comment=mine.comment,
        scores=[
            McpScoreEntry(
                criterion_id=score.criterion_id,
                criterion=names.get(score.criterion_id, ""),
                score=score.score,
                comment=score.comment,
                sources=sources.get(score.criterion_id, []),
            )
            for score in mine.scores
        ],
        submitted_at=mine.submitted_at,
        updated_at=mine.updated_at,
    )


# --- list_projects ------------------------------------------------------------------------
async def list_projects(ctx: ToolContext, args: ListProjectsInput) -> ListProjectsOutput:
    """``project.view`` as a filter: the owner's projects inside the key's restriction,
    by name, with the counts and flags REST's ``list_projects`` computes."""
    _require_read(ctx.principal, Rule.PROJECT_VIEW)
    found = await projects.list_projects(
        ctx.db, ctx.principal, include_archived=args.include_archived
    )
    if ai_scope.is_agent(ctx.principal):  # c22: only its open runs' projects
        allowed = set(await ctx.db.scalars(ai_scope.open_run_projects(ctx.principal)))
        found = [project for project in found if project.id in allowed]
    return ListProjectsOutput(
        projects=[
            McpProject(
                id=project.id,
                slug=project.slug,
                key=project.key,
                name=project.name,
                description=project.description,
                visibility=project.visibility,
                my_role=project.my_role,
                archived=project.archived_at is not None,
                idea_count=project.idea_count,
                can_create_ideas=project.permissions.can_create_ideas,
            )
            for project in found
        ]
    )


# --- search_ideas -------------------------------------------------------------------------
def _text_matches(query: str) -> ColumnElement[bool]:
    """REST's ``q``: the title or summary contains it (any case), or it is a key."""
    pattern = f"%{escape_like(query)}%"
    matches: list[ColumnElement[bool]] = [
        Idea.title.ilike(pattern, escape="\\"),
        Idea.summary.ilike(pattern, escape="\\"),
    ]
    key = parse_idea_key(query)
    if key is not None:
        matches.append(
            and_(
                Idea.number == key.number,
                Idea.project_id.in_(select(Project.id).where(Project.key == key.project_key)),
            )
        )
    return or_(*matches)


def _awaiting(principal: Principal) -> list[ColumnElement[bool]]:
    """My work's "Evaluations due": assigned, not submitted, evaluation open, with the
    member or admin role, in a project that isn't archived."""
    roles = project_effective_roles
    return [
        Idea.id.in_(pending_ideas(principal)),
        Idea.evaluation_closed_at.is_(None),
        Idea.status != IdeaStatus.CLOSED,
        Idea.project_id.in_(
            select(roles.c.project_id).where(
                roles.c.user_id == principal.user_id, roles.c.role.in_(list(ASSIGNABLE_ROLES))
            )
        ),
        Idea.project_id.in_(select(Project.id).where(Project.archived_at.is_(None))),
    ]


async def search_ideas(ctx: ToolContext, args: SearchIdeasInput) -> SearchIdeasOutput:
    """``idea.view`` as a filter (:func:`app.authz.listed_ideas`: never a held idea, only
    the key's projects), REST's sorts and keyset cursors, scores masked for a pending
    evaluator by the summary builder."""
    principal = ctx.principal
    _require_read(principal, Rule.IDEA_VIEW)
    where: list[ColumnElement[bool]] = [listed_ideas(principal)]
    if ai_scope.is_agent(principal):  # c22: only its open runs' ideas
        where.append(Idea.id.in_(ai_scope.open_run_ideas(principal)))
    if args.project is not None:
        project, _ = await load_project(ctx.db, principal, args.project)
        ctx.target.project(project.id)
        where.append(Idea.project_id == project.id)
    if args.status:
        where.append(Idea.status.in_(list(args.status)))
    if args.owner == "me":
        where.append(Idea.owner_id == principal.user_id)
    elif args.owner == "none":
        where.append(Idea.owner_id.is_(None))
    if args.awaiting_my_evaluation:
        where.extend(_awaiting(principal))
    if args.query is not None:
        where.append(_text_matches(args.query))
    rows, next_cursor = await fetch_page(
        ctx.db, principal, where, Sort(args.sort), cursor=args.cursor, limit=args.limit
    )
    context = await load_context(ctx.db, principal, rows)
    public = await _public_ideas(ctx.db, (row.idea.id for row in rows))
    users = await _users(ctx.db, (row.idea.owner_id for row in rows))
    items = []
    for row in rows:
        fields = summary_fields(principal, row, context)
        items.append(
            McpIdeaSummary(
                id=fields["id"],
                key=fields["key"],
                title=fields["title"],
                project=_project_ref(fields["project"]),
                status=fields["status"],
                resolution=fields["resolution"],
                status_label=fields["status_label"],
                url=_url(ctx.settings, fields["key"]),
                summary=fields["summary"],
                via_public_form=row.idea.id in public,
                owner=users.get(row.idea.owner_id) if row.idea.owner_id else None,
                tags=fields["tags"],
                evaluator_progress=fields["evaluator_progress"],
                my_evaluation_state=row.my_state,
                score=(
                    McpScore(overall=fields["score"].overall, count=fields["score"].count)
                    if fields["score"] is not None
                    else None
                ),
                score_hidden=fields["score_hidden"],
                high_disagreement=fields["high_disagreement"],
                vote_count=fields["vote_count"],
                comment_count=fields["comment_count"],
                created_at=fields["created_at"],
                last_activity_at=fields["last_activity_at"],
            )
        )
    return SearchIdeasOutput(items=items, next_cursor=next_cursor)


# --- get_idea -----------------------------------------------------------------------------
async def _evaluations_out(
    ctx: ToolContext, loaded: LoadedIdea, names: dict[UUID, str]
) -> tuple[list[McpEvaluation], int]:
    """Other people's submitted evaluations (``evaluation.view_others``; your own is
    ``my_evaluation``): none while the principal owes their own (blind), else the latest
    :data:`MCP_EVALUATIONS_MAX` and how many there are."""
    if not authorize(ctx.principal, Rule.EVALUATION_VIEW_OTHERS, loaded.resource).allowed:
        return [], 0
    found = await evaluations.list_evaluations(ctx.db, ctx.principal, loaded)
    others = [item for item in found.items if item.evaluator.id != ctx.principal.user_id]
    latest = others[-MCP_EVALUATIONS_MAX:]
    out = []
    for evaluation in latest:
        comment, truncated = cut(evaluation.comment)
        out.append(
            McpEvaluation(
                evaluator=McpUser(
                    id=evaluation.evaluator.id,
                    display_name=evaluation.evaluator.display_name,
                    is_ai=evaluation.is_ai,
                ),
                recommendation=evaluation.recommendation,
                comment=comment,
                truncated=truncated,
                scores=[
                    McpScoreEntry(
                        criterion_id=score.criterion_id,
                        criterion=names.get(score.criterion_id, ""),
                        score=score.score,
                        comment=score.comment,
                        sources=[
                            McpCitation(title=source.title, url=source.url)
                            for source in score.sources
                        ],
                    )
                    for score in evaluation.scores
                ],
                submitted_at=evaluation.submitted_at,
                edited_at=evaluation.edited_at,
                include_in_aggregate=evaluation.include_in_aggregate,
            )
        )
    return out, len(others)


async def _comments_out(db: AsyncSession, idea: Idea, limit: int) -> list[McpComment]:
    """The latest ``limit`` comments that aren't deleted, oldest first among them."""
    if limit == 0:
        return []
    rows = list(
        await db.scalars(
            select(Comment)
            .where(Comment.idea_id == idea.id, Comment.deleted_at.is_(None))
            .order_by(Comment.created_at.desc(), Comment.id.desc())
            .limit(limit)
        )
    )
    rows.reverse()
    authors = await _users(db, (row.author_id for row in rows))
    out = []
    for row in rows:
        body, truncated = cut(row.body_md)
        out.append(
            McpComment(
                id=row.id,
                author=authors.get(row.author_id) if row.author_id else None,
                body_md=body,
                truncated=truncated,
                created_at=row.created_at,
                edited_at=row.edited_at,
            )
        )
    return out


async def get_idea(ctx: ToolContext, args: GetIdeaInput) -> GetIdeaOutput:
    """REST ``get_idea`` + ``list_evaluations`` + ``get_my_evaluation`` + the latest
    comments, bounded; no public submitter's name."""
    db, principal = ctx.db, ctx.principal
    loaded = await _idea(ctx, args.idea)
    await ai_scope.require_open_run(db, principal, loaded.idea.id)
    require(principal, Rule.IDEA_VIEW, loaded.resource)  # the key's read scope
    detail = await ideas.idea_detail(db, principal, loaded)
    names = {c.id: c.name for c in await _criteria(db, loaded.project.id)}
    mine = await evaluations.my_evaluation(db, principal, loaded)
    others, evaluation_count = await _evaluations_out(ctx, loaded, names)
    has_proposal = await proposal_service.find_proposal(db, loaded.idea.id) is not None
    users = await _users(
        db,
        [
            detail.owner.id if detail.owner else None,
            detail.submitted_by.id if detail.submitted_by else None,
        ],
    )
    summary = detail.score
    return GetIdeaOutput(
        idea=McpIdeaDetail(
            id=detail.id,
            key=detail.key,
            title=detail.title,
            project=_project_ref(detail.project),
            status=detail.status,
            resolution=detail.resolution,
            status_label=detail.status_label,
            url=_url(ctx.settings, detail.key),
            summary=detail.summary,
            via_public_form=detail.via_public_form,
            owner=users.get(detail.owner.id) if detail.owner else None,
            tags=detail.tags,
            evaluator_progress=detail.evaluator_progress,
            my_evaluation_state=mine.state if mine else None,
            score=McpScore(overall=summary.overall, count=summary.count) if summary else None,
            score_hidden=detail.score_hidden,
            high_disagreement=detail.high_disagreement,
            vote_count=detail.vote_count,
            comment_count=detail.comment_count,
            created_at=detail.created_at,
            last_activity_at=detail.last_activity_at,
            description_md=detail.description_md,
            submitted_by=users.get(detail.submitted_by.id) if detail.submitted_by else None,
            evaluation_open=detail.evaluation_open,
            evaluation_due_at=detail.evaluation_due_at,
            evaluation_closed_at=detail.evaluation_closed_at,
            evaluators=[
                McpEvaluator(
                    user=McpUser(
                        id=evaluator.user.id,
                        display_name=evaluator.user.display_name,
                        is_ai=evaluator.is_ai,
                    ),
                    state=evaluator.state,
                    submitted_at=evaluator.submitted_at,
                )
                for evaluator in detail.evaluators
            ],
            my_evaluation=(
                _my_out(mine, names, await _own_sources(db, principal, loaded.idea.id))
                if mine
                else None
            ),
            aggregate=detail.aggregate,
            evaluation_count=evaluation_count,
            evaluations=others,
            comments=await _comments_out(db, loaded.idea, args.comment_limit),
            has_proposal=has_proposal,
            permissions=McpIdeaPermissions(
                can_comment=detail.permissions.can_comment,
                can_evaluate=detail.permissions.can_evaluate,
                can_suggest_proposal_section=has_proposal
                and can(principal, Rule.PROPOSAL_SUGGEST_SECTION, loaded.resource),
            ),
        )
    )


# --- get_rubric ---------------------------------------------------------------------------
async def get_rubric(ctx: ToolContext, args: GetRubricInput) -> GetRubricOutput:
    """``project.view``: the active criteria of a project, or of an idea's project."""
    if args.project is not None:
        if ai_scope.is_agent(ctx.principal):
            # c22 before the rule: an agent reads only the rubric of an open run's project.
            project, _ = await load_project(ctx.db, ctx.principal, args.project, None)
            ctx.target.project(project.id)
            await ai_scope.require_open_run_in_project(ctx.db, ctx.principal, project.id)
        project, _ = await load_project(ctx.db, ctx.principal, args.project)
        ctx.target.project(project.id)
    else:
        assert args.idea is not None  # noqa: S101 - the input model needs one of the two
        loaded = await _idea(ctx, args.idea)
        await ai_scope.require_open_run(ctx.db, ctx.principal, loaded.idea.id)
        require(ctx.principal, Rule.PROJECT_VIEW, loaded.resource)
        project = loaded.project
    criteria = await _criteria(ctx.db, project.id)
    return GetRubricOutput(
        project=McpProjectRef(id=project.id, slug=project.slug, key=project.key, name=project.name),
        criteria=[McpRubricCriterion.model_validate(criterion) for criterion in criteria],
        recommendations=list(Recommendation),
    )


# --- get_proposal -------------------------------------------------------------------------
async def get_proposal(ctx: ToolContext, args: GetProposalInput) -> GetProposalOutput:
    """``proposal.view``: the proposal (null until started; no margin comments, no
    score line) and whether suggesting works now."""
    loaded = await _idea(ctx, args.idea)
    await ai_scope.require_open_run(ctx.db, ctx.principal, loaded.idea.id)
    view = await proposal_service.proposal_view(ctx.db, ctx.principal, loaded)
    proposal = view.proposal
    return GetProposalOutput(
        idea=_idea_ref(ctx, loaded),
        proposal=(
            McpProposal(
                id=proposal.id,
                sections=proposal.sections,
                created_at=proposal.created_at,
                updated_at=proposal.updated_at,
            )
            if proposal is not None
            else None
        ),
        can_suggest=proposal is not None
        and can(ctx.principal, Rule.PROPOSAL_SUGGEST_SECTION, loaded.resource),
    )


# --- create_idea --------------------------------------------------------------------------
async def create_idea(ctx: ToolContext, args: CreateIdeaInput) -> CreateIdeaOutput:
    """Exactly REST ``create_idea``: ``idea.create`` on the project, New, the creator
    watches it, activity and notifications as in the app."""
    if ai_scope.is_agent(ctx.principal):  # c22: agents never create ideas
        project, _ = await load_project(ctx.db, ctx.principal, args.project, None)
        ctx.target.project(project.id)
        raise ai_scope.refuse_agent_write()
    project, _ = await load_project(ctx.db, ctx.principal, args.project, Rule.IDEA_CREATE)
    ctx.target.project(project.id)
    idea = await ideas.create_idea(ctx.db, ctx.principal, project, args)
    ctx.target.idea(idea.id, project.id)
    return CreateIdeaOutput(idea=_ref_out(idea_ref(idea, project), ctx.settings))


# --- add_comment --------------------------------------------------------------------------
async def add_comment(ctx: ToolContext, args: AddCommentInput) -> AddCommentOutput:
    """Exactly REST ``create_comment`` (the idea's lock, @mentions, watching,
    notifications)."""
    loaded = await _idea(ctx, args.idea, for_update=True)
    if ai_scope.is_agent(ctx.principal):  # c22: agents never comment (nor @mention)
        raise ai_scope.refuse_agent_write()
    item = await comments.create_comment(ctx.db, ctx.principal, loaded, args)
    body, truncated = cut(item.comment.body_md)
    author = (await _users(ctx.db, [ctx.principal.user_id])).get(ctx.principal.user_id)
    return AddCommentOutput(
        idea=_idea_ref(ctx, loaded),
        comment=McpComment(
            id=item.comment.id,
            author=author,
            body_md=body,
            truncated=truncated,
            created_at=item.created_at,
            edited_at=item.comment.edited_at,
        ),
    )


# --- submit_evaluation --------------------------------------------------------------------
async def submit_evaluation(
    ctx: ToolContext, args: SubmitEvaluationInput
) -> SubmitEvaluationOutput:
    """Exactly REST ``save_my_evaluation`` under the idea's lock: the arguments replace
    what was saved; ``submit`` (default true here) submits."""
    loaded = await _idea(ctx, args.idea, for_update=True)
    run = await ai_scope.write_run(ctx.db, ctx.principal, "submit_evaluation", loaded.idea.id)
    mine = await evaluations.save_my_evaluation(ctx.db, ctx.principal, loaded, args)
    if run is not None and args.submit and mine.state is EvaluatorState.SUBMITTED:
        evaluation_id = await ctx.db.scalar(
            select(Evaluation.id).where(
                Evaluation.idea_id == loaded.idea.id,
                Evaluation.evaluator_id == ctx.principal.user_id,
                Evaluation.status == EvaluationStatus.SUBMITTED,
            )
        )
        if evaluation_id is not None and await ai_results.attach(
            ctx.db, run, evaluation_id=evaluation_id
        ):
            ctx.recorded.append((run.id, run.kind))
    names = {c.id: c.name for c in await _criteria(ctx.db, loaded.project.id)}
    sources = await _own_sources(ctx.db, ctx.principal, loaded.idea.id)
    return SubmitEvaluationOutput(
        idea=_idea_ref(ctx, loaded), evaluation=_my_out(mine, names, sources)
    )


# --- propose_proposal_section -------------------------------------------------------------
async def propose_proposal_section(
    ctx: ToolContext, args: ProposeProposalSectionInput
) -> ProposeProposalSectionOutput:
    """Exactly REST ``create_proposal_suggestion`` with ``source`` ``mcp`` (``ai`` for a
    service account)."""
    loaded = await _idea(ctx, args.idea, for_update=True)
    run = await ai_scope.write_run(
        ctx.db, ctx.principal, "propose_proposal_section", loaded.idea.id, args.section_key
    )
    created = await suggestions.create_suggestion(
        ctx.db, ctx.principal, loaded, args, channel=SuggestionSource.MCP
    )
    if run is not None and await ai_results.attach(
        ctx.db, run, suggestion_id=created.suggestion.id
    ):
        ctx.recorded.append((run.id, run.kind))
    return ProposeProposalSectionOutput(
        idea=_idea_ref(ctx, loaded),
        suggestion=McpProposalSuggestion.model_validate(created.suggestion.model_dump()),
        replaced_suggestion_id=created.replaced_id,
    )


# --- add_research_note (Phase 6) -------------------------------------------------------------
async def add_research_note(ctx: ToolContext, args: AddResearchNoteInput) -> AddResearchNoteOutput:
    """An agent's research note for its open research run on the idea (c22; people:
    ``forbidden``), stored as an ``ai_research_note`` activity item and attached to the
    run; calling it again in the same run replaces the note."""
    loaded = await _idea(ctx, args.idea, for_update=True)
    run = await ai_scope.write_run(ctx.db, ctx.principal, "add_research_note", loaded.idea.id)
    if run is None:  # pragma: no cover - write_run refuses people for this tool
        raise ai_scope.refuse_agent_write()
    note_id, replaced = await ai_notes.write_note(
        ctx.db, ctx.principal, loaded, run, body_md=args.body_md, sources=args.sources
    )
    ctx.recorded.append((run.id, run.kind))
    return AddResearchNoteOutput(idea=_idea_ref(ctx, loaded), note_id=note_id, replaced=replaced)


TOOLS: Final[dict[str, ToolFunction]] = {
    "list_projects": list_projects,
    "search_ideas": search_ideas,
    "get_idea": get_idea,
    "get_rubric": get_rubric,
    "get_proposal": get_proposal,
    "create_idea": create_idea,
    "add_comment": add_comment,
    "submit_evaluation": submit_evaluation,
    "propose_proposal_section": propose_proposal_section,
    "add_research_note": add_research_note,
}
"""Each catalogue tool (:data:`app.schemas.mcp.MCP_TOOLS`) and its implementation."""
