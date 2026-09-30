"""Global search for the command palette (contract section 3.11).

Ideas and projects the principal can view, in non-archived projects. An exact idea
key (``cust-12`` -> ``CUST-12``) is always the first idea; then ideas whose title or
summary contains ``q`` (``pg_trgm`` indexes), most similar title first. Projects
match on name or slug, by name. Results never carry scores.
"""

from __future__ import annotations

import re
from typing import Final

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import viewable_ideas, visible_projects
from app.domain.principal import Principal
from app.models.idea import Idea
from app.models.project import Project
from app.schemas.search import SearchResults
from app.services.refs import idea_ref, project_ref
from app.services.users import escape_like

__all__ = ["global_search"]

_IDEA_KEY: Final = re.compile(r"^([A-Za-z][A-Za-z0-9]{1,5})-([1-9][0-9]{0,8})$")


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
        .where(viewable_ideas(principal), Project.archived_at.is_(None))
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
        matches = ideas.where(
            or_(Idea.title.ilike(pattern, escape="\\"), Idea.summary.ilike(pattern, escape="\\"))
        )
        if found:
            matches = matches.where(Idea.id != found[0][0].id)
        rows = await db.execute(
            matches.order_by(
                func.similarity(Idea.title, q).desc(), Idea.last_activity_at.desc(), Idea.id
            ).limit(limit - len(found))
        )
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
