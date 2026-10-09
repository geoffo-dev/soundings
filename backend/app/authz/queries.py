"""The policy in SQL, for lists, the board, search, sorting and counts.

List endpoints filter in the database, never per row (ADR 0010). These helpers
return SQLAlchemy expressions that agree with :func:`app.authz.policy.authorize`
(``tests/authz/test_queries.py`` checks them against each other) and read project
roles only through the ``project_effective_roles`` view.

* :func:`visible_projects`: ``WHERE`` over ``projects`` for ``project.view``.
* :func:`listed_ideas` (also :func:`viewable_ideas`): ``WHERE`` over ``ideas`` for
  every list, board, search, count, My work and the inbox: ``idea.view`` for ideas
  that are not held. A public submission held for email confirmation or moderation
  (``ideas.held_for``, contract-phase4 section 3.6) is listed nowhere, for anyone:
  admins open one held for moderation by its link or from the moderation queue, which
  the policy (c12) allows and :func:`app.services.ideas.load_idea` checks per idea.
* :func:`score_visible`: ``score.view_aggregate`` / ``evaluation.view_others`` for
  ideas already filtered by :func:`viewable_ideas`: false while the principal is a
  pending evaluator (blind evaluation), and (Phase 8b, review M1) unless the idea's
  project is one the principal can view, so a guest researcher's idea never carries a
  score. :func:`visible_aggregate_score` and :func:`visible_high_disagreement` mask the
  cached columns with it, for responses, ``sort=score`` (masked scores sort as unscored)
  and the disagreement filter.
* :func:`evaluation_visible` (Phase 8b): ``evaluation.view_own`` in SQL, the evaluation
  area of a summary (evaluator progress, ``my_evaluation``): the idea's project is
  viewable (every column that views an idea holds it; the guest researcher doesn't).
* :func:`researched_ideas` (Phase 8b): the ideas a person researches while the
  assignment is live (column R and the +Rsr overlay, c24). **Only** search and ⌘K, MCP
  ``search_ideas``, the inbox, My work's "Research to do" and Similar ideas add it to
  :func:`listed_ideas` (contract-phase8b section 4.5, review C1); every other list
  stays project-scoped.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    ColumnElement,
    ScalarSelect,
    Select,
    and_,
    case,
    exists,
    false,
    null,
    or_,
    select,
    true,
)

from app.domain.principal import Principal
from app.models.enums import (
    EvaluationStatus,
    IdeaStatus,
    ProjectRole,
    ProjectVisibility,
    ResearchStep,
)
from app.models.evaluation import Evaluation
from app.models.idea import Idea, IdeaEvaluator
from app.models.project import Project, project_effective_roles

__all__ = [
    "effective_role",
    "evaluation_visible",
    "listed_ideas",
    "pending_evaluator",
    "pending_ideas",
    "researched_ideas",
    "score_visible",
    "viewable_ideas",
    "visible_aggregate_score",
    "visible_high_disagreement",
    "visible_projects",
]

_roles = project_effective_roles


def _may_read(principal: Principal | None) -> bool:
    """Signed in, and an API key (if any) has the ``read`` scope (``project.view``)."""
    return principal is not None and principal.has_scope("read")


def effective_role(
    user_id: UUID, project_id: ColumnElement[Any] | Any = Project.id
) -> ScalarSelect[ProjectRole | None]:
    """Scalar subquery: the user's effective role in ``project_id`` (null without one)."""
    return (
        select(_roles.c.role)
        .where(_roles.c.project_id == project_id, _roles.c.user_id == user_id)
        .scalar_subquery()
    )


def visible_projects(principal: Principal | None) -> ColumnElement[bool]:
    """``project.view`` over ``projects``: every project for a platform admin; else
    projects with an effective role, plus internal ones for a person (a service account
    needs a role: contract-phase5 section 3.7); narrowed to an API key's projects."""
    if not _may_read(principal):
        return false()
    assert principal is not None  # noqa: S101 - narrowed by _may_read
    clause: ColumnElement[bool]
    has_role = exists().where(
        _roles.c.project_id == Project.id, _roles.c.user_id == principal.user_id
    )
    if principal.is_platform_admin:
        clause = true()
    elif principal.user.is_service_account:
        clause = has_role
    else:
        clause = or_(Project.visibility == ProjectVisibility.INTERNAL, has_role)
    if principal.project_ids is not None:
        clause = and_(clause, Project.id.in_(principal.project_ids))
    return clause


def listed_ideas(principal: Principal | None) -> ColumnElement[bool]:
    """The ideas a list may show: ``idea.view`` over ``ideas`` (ideas in projects the
    principal can view) for ideas that are **not held** (c12, contract-phase4 section
    3.6). Every list, board, count, search, My work, tag list and the inbox uses this,
    so a held idea appears in none of them for anyone, admins included."""
    # Not correlated: queries that also select from projects must not narrow this.
    return and_(
        Idea.held_for.is_(None),
        Idea.project_id.in_(select(Project.id).where(visible_projects(principal)).correlate(None)),
    )


def _viewable_project_ids(principal: Principal | None) -> Select[UUID]:
    """Uncorrelated: Postgres hashes it once per query."""
    return select(Project.id).where(visible_projects(principal)).correlate(None)


def researched_ideas(principal: Principal | None) -> ColumnElement[bool]:
    """Phase 8b: the ideas the principal researches with the assignment **live** (c24):
    ``researcher_id`` is them, the project's research step is on and it isn't archived,
    the idea is open and not held, inside a key's projects (the key with ``read``); never
    for a service account (c23). One index range on ``ix_ideas_researcher_id_status``.

    Add it (``listed_ideas(p) | researched_ideas(p)``) only to the lists the contract
    names (module docstring); a guest's idea carries no score there (:func:`score_visible`
    needs the project viewable)."""
    if not _may_read(principal):
        return false()
    assert principal is not None  # noqa: S101 - narrowed by _may_read
    if principal.user.is_service_account or principal.user.is_break_glass:
        return false()
    live_projects = select(Project.id).where(
        Project.research_step != ResearchStep.OFF, Project.archived_at.is_(None)
    )
    if principal.project_ids is not None:
        live_projects = live_projects.where(Project.id.in_(principal.project_ids))
    return and_(
        Idea.researcher_id == principal.user_id,
        Idea.status != IdeaStatus.CLOSED,
        Idea.held_for.is_(None),
        Idea.project_id.in_(live_projects.correlate(None)),
    )


def viewable_ideas(principal: Principal | None) -> ColumnElement[bool]:
    """The list filter, by its Phase 1 name: :func:`listed_ideas`.

    Every caller is a list, board, search, count, My work query or the inbox, so held
    ideas are left out here for everyone (c12). The one place an admin sees an idea
    held for moderation is its own page and the moderation queue: per idea through the
    policy (``idea.view``, c12), never through this filter.
    """
    return listed_ideas(principal)


def pending_ideas(principal: Principal) -> Select[UUID]:
    """Ids of the ideas the principal owes an evaluation (assigned, not submitted).

    Uncorrelated on purpose: Postgres runs it once per query and hashes it, so
    masking 10k rows costs one hash probe each. The correlated ``EXISTS`` form was
    planned as a nested-loop anti join (180 ms to count 10k ideas instead of 2 ms).
    ``idea_evaluators.idea_id`` is never null, so ``NOT IN`` over it is safe."""
    return (
        select(IdeaEvaluator.idea_id)
        .outerjoin(
            Evaluation,
            and_(
                Evaluation.idea_id == IdeaEvaluator.idea_id,
                Evaluation.evaluator_id == IdeaEvaluator.user_id,
            ),
        )
        .where(
            IdeaEvaluator.user_id == principal.user_id,
            or_(Evaluation.status.is_(None), Evaluation.status != EvaluationStatus.SUBMITTED),
        )
    )


def pending_evaluator(
    principal: Principal, idea_id: ColumnElement[Any] | Any = Idea.id
) -> ColumnElement[bool]:
    """The principal is assigned to the idea and has not submitted (none or a draft)."""
    return idea_id.in_(pending_ideas(principal))


def score_visible(
    principal: Principal | None,
    idea_id: ColumnElement[Any] | Any = Idea.id,
    project_id: ColumnElement[Any] | Any = Idea.project_id,
) -> ColumnElement[bool]:
    """``score.view_aggregate`` (and ``evaluation.view_others``) for a viewable idea.

    False for a pending evaluator, whatever their role: blind evaluation (role
    matrix section 3), for a service account everywhere (rule 9) and (Phase 8b, rule 11)
    wherever the idea's project isn't one the principal can view (a guest researcher's
    idea). Combine with :func:`viewable_ideas`.
    """
    if not _may_read(principal):
        return false()
    assert principal is not None  # noqa: S101 - narrowed by _may_read
    if principal.user.is_service_account:
        return false()  # rule 9: AI agents never see others' score data
    # NOT IN over a non-null column: a hashed subplan, evaluated once per query; the
    # project condition is one more (uncorrelated) hashed subplan.
    return and_(
        idea_id.not_in(pending_ideas(principal)),
        project_id.in_(_viewable_project_ids(principal)),
    )


def evaluation_visible(
    principal: Principal | None, project_id: ColumnElement[Any] | Any = Idea.project_id
) -> ColumnElement[bool]:
    """Phase 8b: ``evaluation.view_own`` for an idea a list shows: its evaluation area
    (evaluator progress, ``my_evaluation``) only where the idea's project is viewable, so
    never for a guest researcher (role matrix table L, section 3 rule 11)."""
    if not _may_read(principal):
        return false()
    return project_id.in_(_viewable_project_ids(principal))


def visible_aggregate_score(principal: Principal | None) -> ColumnElement[Decimal | None]:
    """``ideas.aggregate_score``, or null where hidden: select it, sort by it
    (``NULLS LAST`` puts hidden ideas with the unscored ones) and page on it, so a
    cursor never carries a raw hidden score."""
    return case((score_visible(principal), Idea.aggregate_score), else_=null())


def visible_high_disagreement(principal: Principal | None) -> ColumnElement[bool]:
    """``ideas.high_disagreement`` where the score is visible, else false (the filter
    never matches a hidden idea)."""
    return and_(score_visible(principal), Idea.high_disagreement)
