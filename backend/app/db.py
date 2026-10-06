"""Database engine, sessions and the request-scoped session dependency.

Use :data:`SessionDep` in path operations::

    @router.post("/ideas")
    async def create_idea(body: IdeaCreate, session: SessionDep) -> IdeaOut:
        session.add(Idea(...))

The session commits when the path operation returns and rolls back if it raises.
The commit happens *before* the response is sent, so a failed commit becomes a
500 problem response instead of a silently lost write.

**Before-commit hooks.** Work that must happen once per unit of work, after its last
write and before commit (the notification fan-out over the activity events a request
emitted, contract-phase3 section 3.3), registers with :func:`before_commit`;
:func:`session_scope` runs the hooks just before it commits, inside the same
transaction, so the hook's writes commit or roll back with the rest. Sessions opened
by :func:`session_scope` with ``settings`` carry them for the hooks
(:func:`session_settings`).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Annotated, Final

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings

SessionMaker = async_sessionmaker[AsyncSession]

BeforeCommitHook = Callable[[AsyncSession], Awaitable[None]]

_HOOKS: Final = "soundings.before_commit"
_SETTINGS: Final = "soundings.settings"


def create_engine(settings: Settings, *, application_name: str = "soundings") -> AsyncEngine:
    """Create the async engine (psycopg 3). No connection is made until first use."""
    return create_async_engine(
        settings.sqlalchemy_url,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_pool_size,
        pool_pre_ping=True,
        # Error messages (logged with tracebacks) never show bound values: they may be
        # people's text, emails or tokens.
        hide_parameters=True,
        connect_args={"application_name": application_name},
    )


def create_sessionmaker(engine: AsyncEngine) -> SessionMaker:
    # expire_on_commit=False: objects stay usable after commit without lazy IO,
    # which async SQLAlchemy cannot do implicitly.
    return async_sessionmaker(engine, expire_on_commit=False)


def before_commit(session: AsyncSession, key: str, hook: BeforeCommitHook) -> None:
    """Run ``hook(session)`` once before this unit of work commits (registering the
    same ``key`` again keeps one hook). A rollback drops the registration."""
    hooks: dict[str, BeforeCommitHook] = session.info.setdefault(_HOOKS, {})
    hooks.setdefault(key, hook)


async def run_before_commit(session: AsyncSession) -> None:
    """Run (and clear) the registered hooks; a hook may register more, which run too."""
    while hooks := session.info.pop(_HOOKS, None):
        for hook in hooks.values():
            await hook(session)


def session_settings(session: AsyncSession) -> Settings | None:
    """The settings the session was opened with (:func:`session_scope`), if any."""
    settings = session.info.get(_SETTINGS)
    return settings if isinstance(settings, Settings) else None


@asynccontextmanager
async def session_scope(
    sessionmaker: SessionMaker, *, settings: Settings | None = None
) -> AsyncIterator[AsyncSession]:
    """A unit of work: run the before-commit hooks and commit on success, roll back on
    any exception.

    Use this outside HTTP requests (worker tasks, CLI commands).
    """
    async with sessionmaker() as session:
        if settings is not None:
            session.info[_SETTINGS] = settings
        try:
            yield session
            await run_before_commit(session)
        except BaseException:
            session.info.pop(_HOOKS, None)
            await session.rollback()
            raise
        await session.commit()


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding the request's session (see module docstring)."""
    sessionmaker: SessionMaker = request.app.state.sessionmaker
    async with session_scope(sessionmaker, settings=request.app.state.settings) as session:
        yield session


# scope="function": run the commit/rollback right after the path operation returns,
# before the response is sent. Yield-dependencies that depend on this one must also
# use scope="function" (FastAPI enforces it).
SessionDep = Annotated[AsyncSession, Depends(get_session, scope="function")]
