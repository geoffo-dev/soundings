"""Fixtures for the research-step tests (Phase 8, contract-phase8 section 3).

``team`` (tests/ideas/conftest.py) is "Customer Innovation" (``CUST``) with an admin, an
owner-to-be, a member, three evaluators, a viewer, an outsider and a platform admin.

* ``set_step(db, project, step, items=DEFAULT)`` turns the research step on (or off) with
  a checklist straight in the database and returns the active items (required first two,
  the third optional, like the default checklist).
* ``answer(db, idea, item, user, text)`` answers an item in the database.
* ``api(user)`` signs a user in (``Api``).
* Phase 8b: ``assign(api, key, researcher, due_at)`` calls ``set_research_assignment``;
  ``researcher_audit(db, idea)`` reads its ``idea.researcher_change`` entries;
  ``feed_types(db, idea)`` the idea's activity event types, oldest first.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import uuid4

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import ActivityEvent, AuditLog
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
from tests.mcp.conftest import as_agent, connect, make_key  # noqa: F401 - fixtures (Phase 8b)

__all__ = [
    "API",
    "DEFAULT_ITEMS",
    "Api",
    "AsUser",
    "Team",
    "answer",
    "assert_problem",
    "assign",
    "feed_types",
    "key_of",
    "ok",
    "researcher_audit",
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


# --- Phase 8b ------------------------------------------------------------------------------
async def assign(
    client: Api, key: str, researcher: User | None, due_at: str | None = None
) -> httpx.Response:
    """``PUT /ideas/{key}/research/assignment`` with the complete new state."""
    return await client.put(
        f"/ideas/{key}/research/assignment",
        {"researcher_id": str(researcher.id) if researcher else None, "due_at": due_at},
    )


async def researcher_audit(db: AsyncSession, idea: Idea) -> list[AuditLog]:
    rows = await db.scalars(
        select(AuditLog)
        .where(AuditLog.action == "idea.researcher_change", AuditLog.target_id == idea.id)
        .order_by(AuditLog.created_at, AuditLog.id)
        .execution_options(populate_existing=True)
    )
    return list(rows)


async def feed_types(db: AsyncSession, idea: Idea) -> list[str]:
    rows = await db.scalars(
        select(ActivityEvent.type)
        .where(ActivityEvent.idea_id == idea.id)
        .order_by(ActivityEvent.created_at, ActivityEvent.id)
    )
    return list(rows)
