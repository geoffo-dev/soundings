"""Fixtures for the ideas, evaluations, activity and My work tests.

``team`` is one private project with a person in every role that matters: the
project admin, an owner-to-be and a plain member, three evaluators (members), a
viewer, an internal-style non-member and a platform admin without a role.
``api(user)`` signs a user in and returns a small helper around the client.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ProjectRole
from app.models.project import Project, RubricCriterion
from app.models.user import User
from tests.conftest import Login
from tests.factories import criteria, make_project, make_user

API = "/api/v1"


def assert_problem(response: httpx.Response, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.text
    assert response.headers["content-type"] == "application/problem+json"
    body: dict[str, Any] = response.json()
    assert body["code"] == code, body
    return body


def ok(response: httpx.Response, status: int = 200) -> Any:
    assert response.status_code == status, response.text
    return response.json() if response.content else None


@dataclass
class Team:
    project: Project
    admin: User
    owner: User
    member: User
    evaluators: list[User]
    viewer: User
    outsider: User
    platform: User
    rubric: list[RubricCriterion] = field(default_factory=list)

    @property
    def slug(self) -> str:
        return self.project.slug


@pytest.fixture
async def team(db_session: AsyncSession) -> Team:
    admin = await make_user(db_session, "Ada Admin")
    owner = await make_user(db_session, "Olive Owner")
    member = await make_user(db_session, "Max Member")
    evaluators = [await make_user(db_session, f"Eve Evaluator{n}") for n in (1, 2, 3)]
    viewer = await make_user(db_session, "Vic Viewer")
    outsider = await make_user(db_session, "Otto Outsider")
    platform = await make_user(db_session, "Pat Platform", platform_admin=True)
    project = await make_project(
        db_session,
        slug="customer-innovation",
        key="CUST",
        name="Customer Innovation",
        members={
            admin: ProjectRole.ADMIN,
            owner: ProjectRole.MEMBER,
            member: ProjectRole.MEMBER,
            **dict.fromkeys(evaluators, ProjectRole.MEMBER),
            viewer: ProjectRole.VIEWER,
        },
    )
    return Team(
        project=project,
        admin=admin,
        owner=owner,
        member=member,
        evaluators=evaluators,
        viewer=viewer,
        outsider=outsider,
        platform=platform,
        rubric=await criteria(db_session, project),
    )


class Api:
    """A signed-in client with short helpers for the idea routes."""

    def __init__(self, http: httpx.AsyncClient) -> None:
        self.http = http

    async def get(self, path: str, **params: Any) -> httpx.Response:
        return await self.http.get(API + path, params=params)

    async def post(self, path: str, body: Any = None) -> httpx.Response:
        return await self.http.post(API + path, json=body)

    async def put(self, path: str, body: Any = None) -> httpx.Response:
        return await self.http.put(API + path, json=body)

    async def patch(self, path: str, body: Any = None) -> httpx.Response:
        return await self.http.patch(API + path, json=body)

    async def delete(self, path: str) -> httpx.Response:
        return await self.http.delete(API + path)

    async def create_idea(self, slug: str, **body: Any) -> dict[str, Any]:
        body.setdefault("title", "Self-service refunds")
        body.setdefault("summary", "Let customers refund without calling us.")
        return ok(await self.post(f"/projects/{slug}/ideas", body), 201)  # type: ignore[no-any-return]


AsUser = Callable[[User], Awaitable[Api]]


@pytest.fixture
def api(login: Login) -> AsUser:
    async def sign_in(user: User) -> Api:
        return Api(await login(user))

    return sign_in


def full_scores(team: Team, value: int = 3, **by_name: int) -> list[dict[str, Any]]:
    """A score for every active criterion (``by_name`` overrides by criterion name)."""
    return [
        {"criterion_id": str(c.id), "score": by_name.get(c.name.replace(" ", "_"), value)}
        for c in team.rubric
    ]
