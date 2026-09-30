"""Small reference shapes shared by every area: ``ProjectRef`` and ``IdeaRef``."""

from __future__ import annotations

from app.domain.labels import status_label
from app.models.idea import Idea
from app.models.project import Project
from app.schemas.ideas import IdeaRef
from app.schemas.projects import ProjectRef

__all__ = ["idea_key", "idea_ref", "project_ref"]


def project_ref(project: Project) -> ProjectRef:
    return ProjectRef(id=project.id, slug=project.slug, key=project.key, name=project.name)


def idea_key(idea: Idea, project: Project) -> str:
    return f"{project.key}-{idea.number}"


def idea_ref(idea: Idea, project: Project) -> IdeaRef:
    """Link and label an idea (no score data, so safe for every surface)."""
    return IdeaRef(
        id=idea.id,
        key=idea_key(idea, project),
        number=idea.number,
        project=project_ref(project),
        title=idea.title,
        status=idea.status,
        resolution=idea.resolution,
        status_label=status_label(project.status_labels, idea.status, idea.resolution),
    )
