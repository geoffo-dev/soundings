"""Every ideas, evaluations, activity and My work route: 401 without a session, 403
``csrf_failed`` for writes without the CSRF header, and the check order (a malformed
body is 422 before a hidden idea's 404)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Comment
from tests.conftest import Login
from tests.factories import make_idea
from tests.ideas.conftest import API, Team, assert_problem

# operation_id -> (method, path template, valid body)
ROUTES: dict[str, tuple[str, str, Any]] = {
    "list_ideas": ("GET", "/projects/{slug}/ideas", None),
    "get_board": ("GET", "/projects/{slug}/board", None),
    "create_idea": ("POST", "/projects/{slug}/ideas", {"title": "T", "summary": "S"}),
    "get_idea": ("GET", "/ideas/{idea}", None),
    "update_idea": ("PATCH", "/ideas/{idea}", {"title": "T"}),
    "delete_idea": ("DELETE", "/ideas/{idea}", None),
    "change_idea_status": ("POST", "/ideas/{idea}/status", {"status": "evaluating"}),
    "set_idea_owner": ("PUT", "/ideas/{idea}/owner", {"user_id": None}),
    "volunteer_as_owner": ("POST", "/ideas/{idea}/volunteer", None),
    "add_evaluators": ("POST", "/ideas/{idea}/evaluators", {"user_ids": [str(uuid4())]}),
    "remove_evaluator": ("DELETE", "/ideas/{idea}/evaluators/{user}", None),
    "set_evaluation_due_date": ("PUT", "/ideas/{idea}/evaluation/due-date", {"due_at": None}),
    "close_evaluation": ("POST", "/ideas/{idea}/evaluation/close", None),
    "reopen_evaluation": ("POST", "/ideas/{idea}/evaluation/reopen", None),
    "list_evaluations": ("GET", "/ideas/{idea}/evaluations", None),
    "get_my_evaluation": ("GET", "/ideas/{idea}/evaluations/me", None),
    "save_my_evaluation": ("PUT", "/ideas/{idea}/evaluations/me", {"scores": []}),
    "vote_idea": ("PUT", "/ideas/{idea}/vote", None),
    "unvote_idea": ("DELETE", "/ideas/{idea}/vote", None),
    "watch_idea": ("PUT", "/ideas/{idea}/watch", None),
    "unwatch_idea": ("DELETE", "/ideas/{idea}/watch", None),
    "list_idea_activity": ("GET", "/ideas/{idea}/activity", None),
    "create_comment": ("POST", "/ideas/{idea}/comments", {"body_md": "Hi"}),
    "update_comment": ("PATCH", "/comments/{comment}", {"body_md": "Hi"}),
    "delete_comment": ("DELETE", "/comments/{comment}", None),
    "get_my_work": ("GET", "/me/work", None),
    "list_my_owned_ideas": ("GET", "/me/owned-ideas", None),
}
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def test_every_route_of_the_area_is_covered() -> None:
    from tests.test_contract_routes import CONTRACT

    mine = {
        operation_id
        for _, path, operation_id in CONTRACT
        if "/ideas" in path or "/board" in path or "/comments" in path or "/me/" in path
    }
    assert mine == set(ROUTES)


@pytest.fixture
async def paths(team: Team, db_session: AsyncSession) -> dict[str, str]:
    idea = await make_idea(db_session, team.project, submitted_by=team.member)
    comment = Comment(id=uuid4(), idea_id=idea.id, author_id=team.member.id, body_md="Hi")
    db_session.add(comment)
    await db_session.commit()
    return {
        "slug": team.slug,
        "idea": str(idea.id),
        "user": str(team.evaluators[0].id),
        "comment": str(comment.id),
    }


@pytest.mark.parametrize("operation_id", sorted(ROUTES))
async def test_needs_a_session(
    client: httpx.AsyncClient, paths: dict[str, str], operation_id: str
) -> None:
    method, template, body = ROUTES[operation_id]

    response = await client.request(method, API + template.format(**paths), json=body)

    assert_problem(response, 401, "unauthorized")


@pytest.mark.parametrize("operation_id", sorted(op for op, r in ROUTES.items() if r[0] in UNSAFE))
async def test_writes_need_the_csrf_header(
    login: Login, team: Team, paths: dict[str, str], operation_id: str
) -> None:
    method, template, body = ROUTES[operation_id]
    http = await login(team.admin)
    del http.headers["X-CSRF-Token"]

    response = await http.request(method, API + template.format(**paths), json=body)

    assert_problem(response, 403, "csrf_failed")


async def test_shape_errors_come_before_not_found(
    login: Login, team: Team, paths: dict[str, str]
) -> None:
    http = await login(team.outsider)  # cannot see the idea

    body_error = await http.post(f"{API}/ideas/{paths['idea']}/status", json={"status": "x"})
    hidden = await http.post(f"{API}/ideas/{paths['idea']}/status", json={"status": "new"})
    not_json = await http.post(
        f"{API}/ideas/{paths['idea']}/status",
        content=b"{not json",
        headers={"content-type": "application/json"},
    )

    assert_problem(body_error, 422, "validation_error")
    assert_problem(hidden, 404, "not_found")
    assert_problem(not_json, 422, "validation_error")
