"""Database engine, sessions and the request-scoped session dependency.

Use :data:`SessionDep` in path operations::

    @router.post("/ideas")
    async def create_idea(body: IdeaCreate, session: SessionDep) -> IdeaOut:
        session.add(Idea(...))

The session commits when the path operation returns and rolls back if it raises.
The commit happens *before* the response is sent, so a failed commit becomes a
500 problem response instead of a silently lost write.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings

SessionMaker = async_sessionmaker[AsyncSession]


def create_engine(settings: Settings, *, application_name: str = "soundings") -> AsyncEngine:
    """Create the async engine (psycopg 3). No connection is made until first use."""
    return create_async_engine(
        settings.sqlalchemy_url,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_pool_size,
        pool_pre_ping=True,
        connect_args={"application_name": application_name},
    )


def create_sessionmaker(engine: AsyncEngine) -> SessionMaker:
    # expire_on_commit=False: objects stay usable after commit without lazy IO,
    # which async SQLAlchemy cannot do implicitly.
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def session_scope(sessionmaker: SessionMaker) -> AsyncIterator[AsyncSession]:
    """A unit of work: commit on success, roll back on any exception.

    Use this outside HTTP requests (worker tasks, CLI commands).
    """
    async with sessionmaker() as session:
        try:
            yield session
        except BaseException:
            await session.rollback()
            raise
        await session.commit()


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding the request's session (see module docstring)."""
    sessionmaker: SessionMaker = request.app.state.sessionmaker
    async with session_scope(sessionmaker) as session:
        yield session


# scope="function": run the commit/rollback right after the path operation returns,
# before the response is sent. Yield-dependencies that depend on this one must also
# use scope="function" (FastAPI enforces it).
SessionDep = Annotated[AsyncSession, Depends(get_session, scope="function")]
