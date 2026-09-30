"""Users as they appear in the API."""

from __future__ import annotations

from uuid import UUID

from pydantic import Field, computed_field

from app.models.enums import ProjectRole
from app.schemas.base import ResponseModel
from app.schemas.common import Page

__all__ = ["UserPage", "UserRef", "UserSearchResult", "initials_for"]


def initials_for(display_name: str) -> str:
    """Up to two upper-case initials: first letters of the first and last words.

    ``"Ada Lovelace"`` -> ``"AL"``, ``"Cher"`` -> ``"C"``, ``""`` -> ``"?"``.
    """
    words = [word for word in display_name.split() if word[:1].isalnum()]
    if not words:
        return "?"
    letters = words[0][0] + (words[-1][0] if len(words) > 1 else "")
    return letters.upper()


class UserRef(ResponseModel):
    """A user shown next to content: avatar, name.

    Carries no email; only people pickers (``UserSearchResult``), member lists
    (``Member``) and your own ``CurrentUser`` add it, for signed-in colleagues.
    """

    id: UUID
    display_name: str
    avatar_url: str | None = None

    @computed_field(description="One or two letters for the avatar fallback.")  # type: ignore[prop-decorator]
    @property
    def initials(self) -> str:
        return initials_for(self.display_name)


class UserSearchResult(UserRef):
    """A user in a people picker (add member, assign owner, invite evaluators)."""

    email: str
    project_role: ProjectRole | None = Field(
        default=None,
        description=(
            "The user's role in the project given as ?project=, null if not a member "
            "(or no project was given). Only member/admin can be owner or evaluator."
        ),
    )


class UserPage(Page[UserSearchResult]):
    """A page of users, ordered by display name."""
