"""Global search (the command palette)."""

from __future__ import annotations

from app.schemas.base import ResponseModel
from app.schemas.ideas import IdeaRef
from app.schemas.projects import ProjectRef

__all__ = ["SearchResults"]


class SearchResults(ResponseModel):
    """Best matches first. An exact idea key (``CUST-12``) is always the first idea.

    Never contains scores; ``IdeaRef.project`` names each idea's project.
    """

    ideas: list[IdeaRef]
    projects: list[ProjectRef]
