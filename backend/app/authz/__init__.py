"""Central authorisation (ADR 0010): the one place that answers "may this principal do
rule X on resource Y", for every rule in docs/role-matrix.md. Deny by default.

* :class:`Rule`: stable rule names (``idea.change_status``, ...).
* :func:`authorize` -> :class:`Decision`; :func:`can` (bool); :func:`require` raises
  the rule's problem: 401, 404 (may not know it exists), 403, 422, 409 with the
  matrix's codes; :func:`require_any` for "rule A or rule B" endpoints;
  :func:`require_view` for the implied view rule only.
* :class:`Resource` (+ :class:`ProjectFacts`, :class:`IdeaFacts`): the facts a decision
  needs; :mod:`app.authz.loaders` builds them from the database.
* SQL for lists (:mod:`app.authz.queries`): :func:`visible_projects`,
  :func:`listed_ideas` (alias :func:`viewable_ideas`: never a held idea),
  :func:`score_visible` and the masked score columns.
* ``permissions`` response objects: :mod:`app.authz.permissions`.

Nothing else inspects roles: routes, MCP tools, jobs and emails call this package.
"""

from app.authz.loaders import (
    admin_count,
    effective_role_of,
    effective_roles_of,
    evaluator_state,
    idea_resource,
    load_project,
    other_platform_admins,
    project_resource,
)
from app.authz.permissions import idea_permissions, idea_summary_permissions, project_permissions
from app.authz.policy import (
    ASSIGNABLE_ROLES,
    FROZEN_WHILE_HELD,
    POLICY,
    Decision,
    IdeaFacts,
    ProjectFacts,
    Resource,
    authorize,
    best_decision,
    can,
    not_found,
    require,
    require_any,
    require_view,
)
from app.authz.queries import (
    effective_role,
    listed_ideas,
    pending_evaluator,
    score_visible,
    viewable_ideas,
    visible_aggregate_score,
    visible_high_disagreement,
    visible_projects,
)
from app.authz.rules import RULE_SCOPES, SESSION_ONLY_RULES, Rule

__all__ = [
    "ASSIGNABLE_ROLES",
    "FROZEN_WHILE_HELD",
    "POLICY",
    "RULE_SCOPES",
    "SESSION_ONLY_RULES",
    "Decision",
    "IdeaFacts",
    "ProjectFacts",
    "Resource",
    "Rule",
    "admin_count",
    "authorize",
    "best_decision",
    "can",
    "effective_role",
    "effective_role_of",
    "effective_roles_of",
    "evaluator_state",
    "idea_permissions",
    "idea_resource",
    "idea_summary_permissions",
    "listed_ideas",
    "load_project",
    "not_found",
    "other_platform_admins",
    "pending_evaluator",
    "project_permissions",
    "project_resource",
    "require",
    "require_any",
    "require_view",
    "score_visible",
    "viewable_ideas",
    "visible_aggregate_score",
    "visible_high_disagreement",
    "visible_projects",
]
