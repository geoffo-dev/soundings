"""Global search for the command palette (contract section 3.11).

Ideas and projects the principal can view, in non-archived projects. An exact idea
key (``cust-12`` -> ``CUST-12``) is always the first idea; then ideas whose title or
summary contains ``q`` (``pg_trgm`` indexes), most similar title first (for one or two
letters, most recently active first: :data:`SHORT_QUERY`). Projects
match on name or slug, by name. Results never carry scores. Phase 8b: the ideas a
person researches (``researched_ideas``: a guest researcher's one idea) are found too;
never their project or its other ideas.
"""

from __future__ import annotations

import re
from typing import Any, Final

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import (
    researched_ideas,
    viewable_ideas,
    visible_last_activity,
    visible_projects,
)
from app.domain.principal import Principal
from app.models.idea import Idea
from app.models.project import Project
from app.schemas.search import SearchResults
from app.services.refs import idea_ref, project_ref
from app.services.users import escape_like

__all__ = ["global_search"]

_IDEA_KEY: Final = re.compile(r"^([A-Za-z][A-Za-z0-9]{1,5})-([1-9][0-9]{0,8})$")
SHORT_QUERY: Final = 3
"""Queries shorter than this (one or two letters, as the palette searches while you
type) list the most recently active matches instead of the most similar (perf B6)."""


async def global_search(
    db: AsyncSession, principal: Principal, q: str, *, limit: int
) -> SearchResults:
    q = q.strip()
    if not q:
        return SearchResults(ideas=[], projects=[])
    pattern = f"%{escape_like(q)}%"
    ideas = (
        select(Idea, Project)
        .join(Project, Project.id == Idea.project_id)
        .where(
            or_(viewable_ideas(principal), researched_ideas(principal)),
            Project.archived_at.is_(None),
        )
    )

    found: list[tuple[Idea, Project]] = []
    key = _IDEA_KEY.match(q)
    if key:
        exact = (
            await db.execute(
                ideas.where(Project.key == key.group(1).upper(), Idea.number == int(key.group(2)))
            )
        ).first()
        if exact is not None:
            found.append((exact[0], exact[1]))
    if len(found) < limit:
        short = len(q) < SHORT_QUERY
        # A guest researcher's idea is as recently active as its guest feed (review L1).
        active = visible_last_activity(principal)
        in_title = Idea.title.ilike(pattern, escape="\\")
        matches = ideas.where(
            # One or two letters match the title only: summaries match nearly anything.
            in_title if short else or_(in_title, Idea.summary.ilike(pattern, escape="\\"))
        )
        if found:
            matches = matches.where(Idea.id != found[0][0].id)
        if short:
            # One or two letters: pg_trgm can't narrow them (trigrams need three), so
            # most ideas match and ranking them all by similarity costs ~100 ms at 10k.
            # The most recently active matches instead, read along the activity index.
            order: tuple[Any, ...] = (active.desc(), Idea.id)
        else:
            order = (func.similarity(Idea.title, q).desc(), active.desc(), Idea.id)
        rows = await db.execute(matches.order_by(*order).limit(limit - len(found)))
        found.extend((idea, project) for idea, project in rows)

    projects = await db.scalars(
        select(Project)
        .where(
            visible_projects(principal),
            Project.archived_at.is_(None),
            or_(Project.name.ilike(pattern, escape="\\"), Project.slug.ilike(pattern, escape="\\")),
        )
        .order_by(func.lower(Project.name), Project.id)
        .limit(limit)
    )
    return SearchResults(
        ideas=[idea_ref(idea, project) for idea, project in found],
        projects=[project_ref(project) for project in projects],
    )
