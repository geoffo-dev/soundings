"""Session dependency semantics and the model mixins, on a scratch table."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC

import httpx
import pytest
from fastapi import APIRouter, FastAPI
from sqlalchemy import MetaData, String, select
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.db import SessionDep, create_sessionmaker, session_scope
from app.errors import ConflictProblem
from app.models.base import NAMING_CONVENTION, TimestampMixin, UUIDPrimaryKeyMixin


class ScratchBase(DeclarativeBase):
    """Separate metadata so the scratch table never reaches Alembic or Base.metadata."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Widget(UUIDPrimaryKeyMixin, TimestampMixin, ScratchBase):
    __tablename__ = "test_widget"

    name: Mapped[str] = mapped_column(String(50))


@pytest.fixture
async def widgets(app: FastAPI) -> AsyncIterator[AsyncEngine]:
    engine: AsyncEngine = app.state.engine
    async with engine.begin() as connection:
        await connection.run_sync(ScratchBase.metadata.create_all)
    yield engine
    async with engine.begin() as connection:
        await connection.run_sync(ScratchBase.metadata.drop_all)


@pytest.fixture
def widget_client(
    app: FastAPI, widgets: AsyncEngine, client: httpx.AsyncClient
) -> httpx.AsyncClient:
    router = APIRouter(prefix="/api/v1/test-widgets")

    @router.post("/{name}")
    async def create_test_widget(name: str, session: SessionDep) -> dict[str, str]:
        widget = Widget(name=name)
        session.add(widget)
        await session.flush()
        if name == "conflict":
            raise ConflictProblem("nope")
        if name == "crash":
            raise RuntimeError("boom")
        return {"id": str(widget.id)}

    app.include_router(router)
    return client


async def names(engine: AsyncEngine) -> list[str]:
    async with create_sessionmaker(engine)() as session:
        return list(await session.scalars(select(Widget.name).order_by(Widget.name)))


async def test_session_commits_when_the_endpoint_succeeds(
    widget_client: httpx.AsyncClient, widgets: AsyncEngine
) -> None:
    response = await widget_client.post("/api/v1/test-widgets/kept")

    assert response.status_code == 200
    assert await names(widgets) == ["kept"]


@pytest.mark.parametrize(("name", "status"), [("conflict", 409), ("crash", 500)])
async def test_session_rolls_back_when_the_endpoint_raises(
    widget_client: httpx.AsyncClient, widgets: AsyncEngine, name: str, status: int
) -> None:
    response = await widget_client.post(f"/api/v1/test-widgets/{name}")

    assert response.status_code == status
    assert await names(widgets) == []


async def test_mixins_set_uuid_and_timezone_aware_timestamps(widgets: AsyncEngine) -> None:
    sessionmaker = create_sessionmaker(widgets)
    async with session_scope(sessionmaker) as session:
        widget = Widget(name="first")
        session.add(widget)
        await session.flush()
        assert isinstance(widget.id, uuid.UUID)
        created = widget.created_at

    async with session_scope(sessionmaker) as session:
        stored = await session.get_one(Widget, widget.id)
        assert stored.created_at.tzinfo is not None
        assert stored.created_at.utcoffset() == UTC.utcoffset(None)
        stored.name = "renamed"
        await session.flush()
        assert stored.updated_at > created


async def test_session_scope_rolls_back_on_error(widgets: AsyncEngine) -> None:
    sessionmaker = create_sessionmaker(widgets)

    async def add_then_fail() -> None:
        async with session_scope(sessionmaker) as session:
            session.add(Widget(name="lost"))
            await session.flush()
            raise RuntimeError

    with pytest.raises(RuntimeError):
        await add_then_fail()

    assert await names(widgets) == []


def test_naming_convention_is_applied() -> None:
    assert ScratchBase.metadata.tables["test_widget"].primary_key.name == "pk_test_widget"


async def test_database_errors_never_carry_bound_parameters(app: FastAPI) -> None:
    """Review nit: a failing statement's message (logged with the traceback) names its
    parameters' placeholders, never their values, which may be people's text."""
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    secret = "Zebra-7731-personal-detail"
    with pytest.raises(DBAPIError) as raised:
        async with session_scope(app.state.sessionmaker) as db:
            await db.execute(
                text("SELECT 1 / (length(:secret) - length(:secret))"), {"secret": secret}
            )

    assert "division by zero" in str(raised.value)
    assert secret not in str(raised.value)
