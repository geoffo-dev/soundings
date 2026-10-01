"""ORM models.

Every model module is imported here so ``Base.metadata`` is complete for Alembic
autogenerate and for the test-suite's table truncation. See docs/erd.md.
"""

from app.models.activity import ActivityEvent, AuditLog, Comment
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import (
    AuthMethod,
    EmailStatus,
    EmailType,
    EvaluationStatus,
    EvaluatorState,
    GroupSyncMode,
    IdeaStatus,
    NotificationMode,
    NotificationType,
    ProjectRole,
    ProjectVisibility,
    Recommendation,
    Resolution,
)
from app.models.evaluation import Evaluation, EvaluationScore
from app.models.group import Group, GroupIdpValue, GroupMembership, ProjectGroupGrant
from app.models.idea import Idea, IdeaEvaluator, IdeaTag, IdeaVote, IdeaWatcher
from app.models.notification import Notification, NotificationPreference, OutboundEmail
from app.models.project import (
    Project,
    ProjectMember,
    RubricCriterion,
    Tag,
    project_effective_roles,
)
from app.models.user import User, UserExternalId, UserIdentity, UserSession

__all__ = [
    "ActivityEvent",
    "AuditLog",
    "AuthMethod",
    "Base",
    "Comment",
    "EmailStatus",
    "EmailType",
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
    "Notification",
    "NotificationMode",
    "NotificationPreference",
    "NotificationType",
    "OutboundEmail",
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
