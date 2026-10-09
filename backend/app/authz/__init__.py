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
* API keys route by route (:mod:`app.authz.keys`): :data:`ROUTE_KEY_ACCESS`,
  :func:`check_route_for_key`, :func:`require_session`, :func:`require_key_scope`.

Nothing else inspects roles: routes, MCP tools, jobs and emails call this package.
"""

from app.authz.guest import RESEARCH_GUEST_ACCESS, GuestAccess, guest_access, mcp_operation
from app.authz.keys import (
    ROUTE_KEY_ACCESS,
    InsufficientScopeProblem,
    KeyAccess,
    check_route_for_key,
    require_key_scope,
    require_session,
)
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
from app.authz.permissions import (
    idea_permissions,
    idea_summary_permissions,
    project_permissions,
    research_assignment_flags,
)
from app.authz.policy import (
    ASSIGNABLE_ROLES,
    FROZEN_WHILE_HELD,
    POLICY,
    Decision,
    IdeaFacts,
    NamedResearcher,
    ProjectFacts,
    Resource,
    authorize,
    best_decision,
    can,
    counted_by_default,
    is_agent,
    may_cite_sources,
    not_found,
    require,
    require_any,
    require_view,
    researcher_live,
    searches_co_members_only,
    sees_email_trouble,
    writes_as_ai,
)
from app.authz.queries import (
    effective_role,
    evaluation_visible,
    guest_activity_at,
    listed_ideas,
    pending_evaluator,
    researched_ideas,
    score_visible,
    viewable_ideas,
    visible_aggregate_score,
    visible_high_disagreement,
    visible_last_activity,
    visible_projects,
)
from app.authz.rules import RULE_SCOPES, SESSION_ONLY_RULES, Rule

__all__ = [
    "ASSIGNABLE_ROLES",
    "FROZEN_WHILE_HELD",
    "POLICY",
    "RESEARCH_GUEST_ACCESS",
    "ROUTE_KEY_ACCESS",
    "RULE_SCOPES",
    "SESSION_ONLY_RULES",
    "Decision",
    "GuestAccess",
    "IdeaFacts",
    "InsufficientScopeProblem",
    "KeyAccess",
    "NamedResearcher",
    "ProjectFacts",
    "Resource",
    "Rule",
    "admin_count",
    "authorize",
    "best_decision",
    "can",
    "check_route_for_key",
    "counted_by_default",
    "effective_role",
    "effective_role_of",
    "effective_roles_of",
    "evaluation_visible",
    "evaluator_state",
    "guest_access",
    "guest_activity_at",
    "idea_permissions",
    "idea_resource",
    "idea_summary_permissions",
    "is_agent",
    "listed_ideas",
    "load_project",
    "may_cite_sources",
    "mcp_operation",
    "not_found",
    "other_platform_admins",
    "pending_evaluator",
    "project_permissions",
    "project_resource",
    "require",
    "require_any",
    "require_key_scope",
    "require_session",
    "require_view",
    "research_assignment_flags",
    "researched_ideas",
    "researcher_live",
    "score_visible",
    "searches_co_members_only",
    "sees_email_trouble",
    "viewable_ideas",
    "visible_aggregate_score",
    "visible_high_disagreement",
    "visible_last_activity",
    "visible_projects",
    "writes_as_ai",
]
