"""ORM models.

Every model module is imported here so ``Base.metadata`` is complete for Alembic
autogenerate and for the test-suite's table truncation. See docs/erd.md.
"""

from app.models.activity import ActivityEvent, AuditLog, Comment
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import (
    AuthMethod,
    EvaluationStatus,
    EvaluatorState,
    GroupSyncMode,
    IdeaStatus,
    ProjectRole,
    ProjectVisibility,
    Recommendation,
    Resolution,
)
from app.models.evaluation import Evaluation, EvaluationScore
from app.models.group import Group, GroupIdpValue, GroupMembership, ProjectGroupGrant
from app.models.idea import Idea, IdeaEvaluator, IdeaTag, IdeaVote, IdeaWatcher
from app.models.project import (
    Project,
    ProjectMember,
    RubricCriterion,
    Tag,
    project_effective_roles,
)
from app.models.user import OidcLoginAttempt, User, UserExternalId, UserIdentity, UserSession

__all__ = [
    "ActivityEvent",
    "AuditLog",
    "AuthMethod",
    "Base",
    "Comment",
    "Evaluation",
    "EvaluationScore",
    "EvaluationStatus",
    "EvaluatorState",
    "Group",
    "GroupIdpValue",
    "GroupMembership",
    "GroupSyncMode",
    "Idea",
    "IdeaEvaluator",
    "IdeaStatus",
    "IdeaTag",
    "IdeaVote",
    "IdeaWatcher",
    "OidcLoginAttempt",
    "Project",
    "ProjectGroupGrant",
    "ProjectMember",
    "ProjectRole",
    "ProjectVisibility",
    "Recommendation",
    "Resolution",
    "RubricCriterion",
    "Tag",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
    "User",
    "UserExternalId",
    "UserIdentity",
    "UserSession",
    "project_effective_roles",
]
