"""Rule names (docs/role-matrix.md, first column) and the API-key scope that grants each.

Code, tests, audit entries and docs refer to rules by these stable names. A rule
that is not in :data:`app.authz.policy.POLICY` is denied.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from app.domain.principal import ApiKeyScope

__all__ = ["PUBLIC_RULES", "RULE_SCOPES", "SESSION_ONLY_RULES", "Rule"]


class Rule(StrEnum):
    # A. Projects and ideas
    PROJECT_VIEW = "project.view"
    PROJECT_CREATE = "project.create"
    IDEA_VIEW = "idea.view"
    IDEA_CREATE = "idea.create"
    IDEA_EDIT_OWN = "idea.edit_own"
    IDEA_EDIT_ANY = "idea.edit_any"
    IDEA_DELETE = "idea.delete"
    # B. Collaboration
    COMMENT_CREATE = "comment.create"
    COMMENT_EDIT_OWN = "comment.edit_own"
    COMMENT_DELETE_ANY = "comment.delete_any"
    IDEA_VOTE = "idea.vote"
    IDEA_WATCH = "idea.watch"
    # C. Ownership and evaluation management
    IDEA_VOLUNTEER_OWNER = "idea.volunteer_owner"
    IDEA_RELEASE_OWNER = "idea.release_owner"
    IDEA_ASSIGN_OWNER = "idea.assign_owner"
    EVALUATOR_MANAGE = "evaluator.manage"
    IDEA_SET_DUE_DATE = "idea.set_due_date"
    EVALUATION_SUBMIT_OWN = "evaluation.submit_own"
    EVALUATION_CLOSE = "evaluation.close"
    EVALUATION_INCLUDE_AI = "evaluation.include_ai"
    IDEA_CHANGE_STATUS = "idea.change_status"
    IDEA_MODERATE = "idea.moderate"
    # D. Evaluation visibility (blind evaluation)
    EVALUATION_VIEW_OWN = "evaluation.view_own"
    EVALUATION_VIEW_OTHERS = "evaluation.view_others"
    SCORE_VIEW_AGGREGATE = "score.view_aggregate"
    # E. Proposals
    PROPOSAL_VIEW = "proposal.view"
    PROPOSAL_WRITE = "proposal.write"
    PROPOSAL_COMMENT = "proposal.comment"
    PROPOSAL_SUGGEST_SECTION = "proposal.suggest_section"
    PROPOSAL_EXPORT = "proposal.export"
    # F. Project administration
    PROJECT_MANAGE_MEMBERS = "project.manage_members"
    PROJECT_EDIT_RUBRIC = "project.edit_rubric"
    PROJECT_RENAME_STATUS_LABELS = "project.rename_status_labels"
    PROJECT_EDIT_SETTINGS = "project.edit_settings"
    PUBLIC_ERASE_SUBMITTER = "public.erase_submitter"
    # G. Public submission
    PUBLIC_SUBMIT = "public.submit"
    PUBLIC_TRACK = "public.track"
    # H. Platform administration
    PLATFORM_MANAGE_USERS = "platform.manage_users"
    PLATFORM_MANAGE_GROUPS = "platform.manage_groups"
    PLATFORM_CONFIGURE_SSO = "platform.configure_sso"
    PLATFORM_CONFIGURE_EMAIL = "platform.configure_email"
    PLATFORM_EDIT_BRANDING = "platform.edit_branding"
    PLATFORM_MANAGE_AGENTS = "platform.manage_agents"
    PLATFORM_VIEW_AUDIT_LOG = "platform.view_audit_log"
    API_KEY_MANAGE_ANY = "api_key.manage_any"
    # I. Self-service, API keys and MCP
    SELF_MANAGE_PROFILE = "self.manage_profile"
    SELF_UNSUBSCRIBE = "self.unsubscribe"
    USER_SEARCH = "user.search"
    API_KEY_MANAGE_OWN = "api_key.manage_own"
    MCP_CONNECT = "mcp.connect"
    # J. AI assistance
    AI_REQUEST_EVALUATION = "ai.request_evaluation"
    AI_RESEARCH = "ai.research"
    AI_DRAFT_SECTION = "ai.draft_section"
    AI_CANCEL_RUN = "ai.cancel_run"


_READ: Final = frozenset(
    {
        Rule.PROJECT_VIEW,
        Rule.IDEA_VIEW,
        Rule.USER_SEARCH,
        Rule.EVALUATION_VIEW_OWN,
        Rule.EVALUATION_VIEW_OTHERS,
        Rule.SCORE_VIEW_AGGREGATE,
        Rule.PROPOSAL_VIEW,
        Rule.PROPOSAL_EXPORT,
    }
)
_WRITE: Final = frozenset(
    {
        Rule.IDEA_CREATE,
        Rule.IDEA_EDIT_OWN,
        Rule.IDEA_EDIT_ANY,
        Rule.IDEA_DELETE,
        Rule.COMMENT_CREATE,
        Rule.COMMENT_EDIT_OWN,
        Rule.COMMENT_DELETE_ANY,
        Rule.IDEA_VOTE,
        Rule.IDEA_WATCH,
        Rule.IDEA_VOLUNTEER_OWNER,
        Rule.IDEA_RELEASE_OWNER,
        Rule.IDEA_ASSIGN_OWNER,
        Rule.EVALUATOR_MANAGE,
        Rule.IDEA_SET_DUE_DATE,
        Rule.EVALUATION_CLOSE,
        Rule.EVALUATION_INCLUDE_AI,
        Rule.IDEA_CHANGE_STATUS,
        Rule.IDEA_MODERATE,
        Rule.PROPOSAL_WRITE,
        Rule.PROPOSAL_COMMENT,
        Rule.PROPOSAL_SUGGEST_SECTION,
        Rule.AI_REQUEST_EVALUATION,
        Rule.AI_RESEARCH,
        Rule.AI_DRAFT_SECTION,
        Rule.AI_CANCEL_RUN,
    }
)

RULE_SCOPES: Final[dict[Rule, ApiKeyScope]] = {
    **dict.fromkeys(_READ, "read"),
    **dict.fromkeys(_WRITE, "write"),
    Rule.EVALUATION_SUBMIT_OWN: "evaluate",
    Rule.MCP_CONNECT: "mcp",
}
"""Role matrix section 5: the API-key scope that grants each rule."""

PUBLIC_RULES: Final = frozenset({Rule.PUBLIC_SUBMIT, Rule.PUBLIC_TRACK, Rule.SELF_UNSUBSCRIBE})
"""Rules decided by a token or a project setting, whoever (if anyone) is signed in."""

SESSION_ONLY_RULES: Final = frozenset(set(Rule) - set(RULE_SCOPES) - PUBLIC_RULES)
"""Never available through an API key, whatever its scopes (role matrix section 5):
project.create, project administration, public.erase_submitter, platform.*,
api_key.* and self.manage_profile."""
