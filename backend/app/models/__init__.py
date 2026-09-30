"""ORM models.

Every model module is imported here so ``Base.metadata`` is complete for Alembic
autogenerate and for the test-suite's table truncation. See docs/erd.md.
"""

from app.models.activity import ActivityEvent, AuditLog, Comment
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import (
    EvaluationStatus,
    EvaluatorState,
    IdeaStatus,
    ProjectRole,
    ProjectVisibility,
    Recommendation,
    Resolution,
)
from app.models.evaluation import Evaluation, EvaluationScore
from app.models.idea import Idea, IdeaEvaluator, IdeaTag, IdeaVote, IdeaWatcher
from app.models.project import (
    Project,
    ProjectMember,
    RubricCriterion,
    Tag,
    project_effective_roles,
)
from app.models.user import User, UserSession

__all__ = [
    "ActivityEvent",
    "AuditLog",
    "Base",
    "Comment",
    "Evaluation",
    "EvaluationScore",
    "EvaluationStatus",
    "EvaluatorState",
    "Idea",
    "IdeaEvaluator",
    "IdeaStatus",
    "IdeaTag",
    "IdeaVote",
    "IdeaWatcher",
    "Project",
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
    "UserSession",
    "project_effective_roles",
]
