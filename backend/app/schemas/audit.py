"""The audit log viewer (Admin settings -> Audit log; contract-phase2 section 3.11)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from app.schemas.base import ResponseModel
from app.schemas.common import Page
from app.schemas.projects import ProjectRef
from app.schemas.users import UserRef

__all__ = ["AuditAction", "AuditEntry", "AuditPage", "AuditTargetType"]

AuditTargetType = Literal["user", "project", "idea", "group"]
"""What an audit entry is about (``audit_log.target_type``)."""


class AuditAction(StrEnum):
    """Every action the audit log records (``audit_log.action``).

    ``app.services.audit.AUDIT_ACTIONS`` must be exactly this set. Names are
    ``<area>.<what happened>``; ``details.rule`` names the role-matrix rule that
    allowed an admin action.
    """

    # Sign-in and sessions
    SESSION_SIGN_IN = "session.sign_in"
    SESSION_SIGN_IN_DENIED = "session.sign_in_denied"
    SESSION_SIGN_OUT = "session.sign_out"
    # Users and identities
    USER_CREATE = "user.create"
    USER_UPDATE = "user.update"
    USER_EXTERNAL_IDS_REPLACE = "user.external_ids_replace"
    USER_IDENTITY_LINK = "user.identity_link"
    USER_IDENTITY_UNLINK = "user.identity_unlink"
    USER_SESSIONS_END = "user.sessions_end"
    USER_GROUPS_SYNC = "user.groups_sync"
    USER_ANONYMISE = "user.anonymise"  # Phase 7: `soundings anonymise-user` (CLI only)
    # Groups
    GROUP_CREATE = "group.create"
    GROUP_UPDATE = "group.update"
    GROUP_DELETE = "group.delete"
    GROUP_MAPPING_REPLACE = "group.mapping_replace"
    GROUP_MEMBER_ADD = "group.member_add"
    GROUP_MEMBER_REMOVE = "group.member_remove"
    # Projects
    PROJECT_CREATE = "project.create"
    PROJECT_UPDATE = "project.update"
    PROJECT_MEMBER_ADD = "project.member_add"
    PROJECT_MEMBER_UPDATE = "project.member_update"
    PROJECT_MEMBER_REMOVE = "project.member_remove"
    PROJECT_GROUP_GRANT_ADD = "project.group_grant_add"
    PROJECT_GROUP_GRANT_UPDATE = "project.group_grant_update"
    PROJECT_GROUP_GRANT_REMOVE = "project.group_grant_remove"
    PROJECT_RUBRIC_REPLACE = "project.rubric_replace"
    # Phase 8: proposal templates and the research step (contract-phase8 section 5)
    PROJECT_PROPOSAL_TEMPLATE_REPLACE = "project.proposal_template_replace"
    PROJECT_RESEARCH_STEP_CHANGE = "project.research_step_change"
    PROJECT_RESEARCH_CHECKLIST_REPLACE = "project.research_checklist_replace"
    # Ideas, assignments and evaluations
    IDEA_DELETE = "idea.delete"
    IDEA_OWNER_CHANGE = "idea.owner_change"
    IDEA_STATUS_CHANGE = "idea.status_change"
    IDEA_RESEARCH_OVERRIDE = "idea.research_override"  # Phase 8: "Move anyway"
    EVALUATOR_ADD = "evaluator.add"
    EVALUATOR_REMOVE = "evaluator.remove"
    EVALUATION_SUBMIT = "evaluation.submit"
    EVALUATION_CLOSE = "evaluation.close"
    EVALUATION_REOPEN = "evaluation.reopen"
    # Email (Admin settings -> Email; contract-phase3 section 3.10)
    EMAIL_TEST_SEND = "email.test_send"
    EMAIL_RETRY = "email.retry"
    # Public submissions and branding (contract-phase4 section 3.14)
    SUBMISSION_APPROVE = "submission.approve"
    SUBMISSION_REJECT = "submission.reject"
    SUBMISSION_ERASE = "submission.erase"
    BRANDING_UPDATE = "branding.update"
    # API keys and MCP (contract-phase5 section 3.6)
    API_KEY_CREATE = "api_key.create"
    API_KEY_REVOKE = "api_key.revoke"
    MCP_CALL = "mcp.call"
    # AI assistance through kagent (contract-phase6 section 3.10)
    AI_AGENT_REGISTER = "ai_agent.register"
    AI_AGENT_UPDATE = "ai_agent.update"
    AI_RUN_REQUEST = "ai_run.request"
    AI_RUN_CANCEL = "ai_run.cancel"
    EVALUATION_INCLUDE_AI = "evaluation.include_ai"
    AI_NOTE_DELETE = "ai_note.delete"


class AuditEntry(ResponseModel):
    """One audit entry. Ids are resolved to names where the thing still exists."""

    id: UUID
    created_at: datetime
    action: str = Field(
        description="An AuditAction value (a plain string, so older entries stay readable)."
    )
    actor_id: UUID | None = Field(
        description=(
            "Who did it; null for denied sign-ins (the matched user, if any, is the "
            "target: an attempt is never pinned on the account it tried)."
        )
    )
    actor: UserRef | None = Field(description="The actor, if the user still exists.")
    target_type: AuditTargetType | None = Field(description="Null when there is no target.")
    target_id: UUID | None
    target_label: str | None = Field(
        description=(
            "Display name of the target if it still exists: a user's name, project "
            "name, idea key (CUST-12) or group name."
        )
    )
    project: ProjectRef | None = Field(description="The project it happened in, if it exists.")
    details: dict[str, Any] = Field(
        description="Action-specific ids, enum values and field names; never secrets or PII."
    )


class AuditPage(Page[AuditEntry]):
    """Newest first."""
