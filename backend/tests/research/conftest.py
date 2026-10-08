"""Fixtures for the research-step tests (Phase 8, contract-phase8 section 3).

``team`` (tests/ideas/conftest.py) is "Customer Innovation" (``CUST``) with an admin, an
owner-to-be, a member, three evaluators, a viewer, an outsider and a platform admin.

* ``set_step(db, project, step, items=DEFAULT)`` turns the research step on (or off) with
  a checklist straight in the database and returns the active items (required first two,
  the third optional, like the default checklist).
* ``answer(db, idea, item, user, text)`` answers an item in the database.
* ``api(user)`` signs a user in (``Api``).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import utcnow
from app.models.enums import ResearchStep
from app.models.idea import Idea
from app.models.project import Project
from app.models.research import ResearchAnswer, ResearchChecklistItem
from app.models.user import User
from app.schemas.research import DEFAULT_RESEARCH_CHECKLIST
from tests.ideas.conftest import (  # noqa: F401 - fixtures
    API,
    Api,
    AsUser,
    Team,
    api,
    assert_problem,
    ok,
    team,
)

__all__ = [
    "API",
    "DEFAULT_ITEMS",
    "Api",
    "AsUser",
    "Team",
    "answer",
    "assert_problem",
    "key_of",
    "ok",
    "set_step",
]

DEFAULT_ITEMS: tuple[tuple[str, str, bool], ...] = tuple(
    (item.title, item.hint, item.required) for item in DEFAULT_RESEARCH_CHECKLIST
)


def key_of(project: Project, idea: Idea) -> str:
    return f"{project.key}-{idea.number}"


async def set_step(
    db: AsyncSession,
    project: Project,
    step: ResearchStep,
    items: Sequence[tuple[str, str, bool]] = DEFAULT_ITEMS,
) -> list[ResearchChecklistItem]:
    """The project's step and (when it has none yet) a checklist, in the database."""
    await db.execute(update(Project).where(Project.id == project.id).values(research_step=step))
    project.research_step = step
    existing = list(
        await db.scalars(
            select(ResearchChecklistItem)
            .where(
                ResearchChecklistItem.project_id == project.id,
                ResearchChecklistItem.archived_at.is_(None),
            )
            .order_by(ResearchChecklistItem.position)
        )
    )
    if not existing:
        existing = [
            ResearchChecklistItem(
                id=uuid4(),
                project_id=project.id,
                position=position,
                title=title,
                hint=hint,
                required=required,
            )
            for position, (title, hint, required) in enumerate(items)
        ]
        db.add_all(existing)
    await db.commit()
    return existing


async def answer(
    db: AsyncSession,
    idea: Idea,
    item: ResearchChecklistItem,
    user: User | None,
    text: str = "Legal (contracts team), 3 Oct: fine if we keep the standard terms.",
) -> None:
    now = utcnow()
    db.add(
        ResearchAnswer(
            idea_id=idea.id,
            item_id=item.id,
            answer=text,
            answered_by_id=user.id if user else None,
            answered_at=now,
            updated_by_id=user.id if user else None,
            updated_at=now,
        )
    )
    await db.commit()


async def answer_required(
    db: AsyncSession, idea: Idea, items: Sequence[ResearchChecklistItem], user: User
) -> None:
    for item in items:
        if item.required:
            await answer(db, idea, item, user)


def open_titles(body: dict[str, Any]) -> list[str]:
    return [item["title"] for item in body["open_items"]]
