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
  pending evaluator (blind evaluation). :func:`visible_aggregate_score` and
  :func:`visible_high_disagreement` mask the cached columns with it, for responses,
  ``sort=score`` (masked scores sort as unscored) and the disagreement filter.
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
from app.models.enums import EvaluationStatus, ProjectRole, ProjectVisibility
from app.models.evaluation import Evaluation
from app.models.idea import Idea, IdeaEvaluator
from app.models.project import Project, project_effective_roles

__all__ = [
    "effective_role",
    "listed_ideas",
    "pending_evaluator",
    "pending_ideas",
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
    projects with an effective role, plus internal ones; narrowed to an API key's
    projects."""
    if not _may_read(principal):
        return false()
    assert principal is not None  # noqa: S101 - narrowed by _may_read
    clause: ColumnElement[bool]
    if principal.is_platform_admin:
        clause = true()
    else:
        clause = or_(
            Project.visibility == ProjectVisibility.INTERNAL,
            exists().where(
                _roles.c.project_id == Project.id, _roles.c.user_id == principal.user_id
            ),
        )
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
    principal: Principal | None, idea_id: ColumnElement[Any] | Any = Idea.id
) -> ColumnElement[bool]:
    """``score.view_aggregate`` (and ``evaluation.view_others``) for a viewable idea.

    False for a pending evaluator, whatever their role: blind evaluation (role
    matrix section 3). Combine with :func:`viewable_ideas`; this does not re-check view.
    """
    if not _may_read(principal):
        return false()
    assert principal is not None  # noqa: S101 - narrowed by _may_read
    # NOT IN over a non-null column: a hashed subplan, evaluated once per query.
    return idea_id.not_in(pending_ideas(principal))


def visible_aggregate_score(principal: Principal | None) -> ColumnElement[Decimal | None]:
    """``ideas.aggregate_score``, or null where hidden: select it, sort by it
    (``NULLS LAST`` puts hidden ideas with the unscored ones) and page on it, so a
    cursor never carries a raw hidden score."""
    return case((score_visible(principal), Idea.aggregate_score), else_=null())


def visible_high_disagreement(principal: Principal | None) -> ColumnElement[bool]:
    """``ideas.high_disagreement`` where the score is visible, else false (the filter
    never matches a hidden idea)."""
    return and_(score_visible(principal), Idea.high_disagreement)
