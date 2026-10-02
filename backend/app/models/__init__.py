"""ORM models.

Every model module is imported here so ``Base.metadata`` is complete for Alembic
autogenerate and for the test-suite's table truncation. See docs/erd.md.
"""

from app.models.activity import ActivityEvent, AuditLog, Comment
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.branding import BrandAsset, BrandingProfile
from app.models.enums import (
    AuthMethod,
    BrandAssetKind,
    BrandFont,
    EmailStatus,
    EmailType,
    EvaluationStatus,
    EvaluatorState,
    GroupSyncMode,
    HoldReason,
    IdeaStatus,
    NotificationMode,
    NotificationType,
    ProjectRole,
    ProjectVisibility,
    ProposalSectionKey,
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
from app.models.proposal import Proposal, ProposalComment, ProposalSection, ProposalThread
from app.models.public import AltchaUsedChallenge, ConfirmationEmailSend, PublicSubmission
from app.models.user import User, UserExternalId, UserIdentity, UserSession

__all__ = [
    "ActivityEvent",
    "AltchaUsedChallenge",
    "AuditLog",
    "AuthMethod",
    "Base",
    "BrandAsset",
    "BrandAssetKind",
    "BrandFont",
    "BrandingProfile",
    "Comment",
    "ConfirmationEmailSend",
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
    "HoldReason",
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
    "Proposal",
    "ProposalComment",
    "ProposalSection",
    "ProposalSectionKey",
    "ProposalThread",
    "PublicSubmission",
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
