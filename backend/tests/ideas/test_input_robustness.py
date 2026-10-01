"""Hostile input never reaches the database as a 500 (code review F3): NUL characters
in bodies, query and path parameters, and cursors that carry them."""

from __future__ import annotations

import base64
import json
from typing import Any
from urllib.parse import quote
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from pydantic import Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import (
    activity,
    admin_audit,
    admin_groups,
    admin_sso,
    admin_users,
    auth,
    auth_sso,
    evaluations,
    groups,
    ideas,
    project_groups,
    projects,
    search,
    users,
    work,
)
from app.schemas.base import RequestModel, TagName
from app.schemas.ideas import IdeaCreate
from tests.factories import make_idea
from tests.ideas.conftest import API, AsUser, Team, assert_problem
from tests.test_contract_routes import STUBS

NUL = "a\x00b"


# --- Request bodies --------------------------------------------------------------------------
class Inner(RequestModel):
    note: str = ""


class Body(RequestModel):
    title: str = ""
    tags: list[TagName] = Field(default_factory=list)
    guidance: dict[str, str] = Field(default_factory=dict)
    inner: Inner | None = None
    optional: str | None = None


@pytest.mark.parametrize(
    ("body", "loc"),
    [
        ({"title": NUL}, ("title",)),
        ({"tags": ["ok", NUL]}, ("tags",)),
        ({"guidance": {"1": NUL}}, ("guidance",)),
        ({"guidance": {NUL: "fine"}}, ("guidance",)),
        ({"inner": {"note": NUL}}, ("inner", "note")),
        ({"optional": "\x00"}, ("optional",)),
    ],
)
def test_request_models_reject_nul_anywhere(body: dict[str, Any], loc: tuple[str, ...]) -> None:
    with pytest.raises(ValidationError) as caught:
        Body.model_validate(body)

    [error] = caught.value.errors()
    assert error["loc"][: len(loc)] == loc
    assert "NUL" in error["msg"]


def test_request_models_accept_other_control_characters_and_unicode() -> None:
    body = Body.model_validate(
        {"title": "Tabs\tand\nnew lines, é and 😀", "guidance": {"1": "x"}, "optional": None}
    )
    assert body.title == "Tabs\tand\nnew lines, é and 😀"


def test_every_request_body_is_a_request_model() -> None:
    """The NUL check lives on RequestModel: every JSON body must use it."""
    bodies = [
        param.field_info.annotation
        for module in (
            activity,
            admin_audit,
            admin_groups,
            admin_sso,
            admin_users,
            auth,
            auth_sso,
            evaluations,
            groups,
            ideas,
            project_groups,
            projects,
            search,
            users,
            work,
        )
        for route in module.router.routes
        if isinstance(route, APIRoute)
        for param in route.dependant.body_params
    ]
    assert len(bodies) >= 10
    for annotation in bodies:
        assert isinstance(annotation, type), annotation
        assert issubclass(annotation, RequestModel), annotation


async def test_nul_in_a_body_is_a_422(api: AsUser, team: Team) -> None:
    alice = await api(team.member)
    idea = {"title": "Self-service refunds", "summary": "Refund without calling us."}

    for field in ("title", "summary", "description_md"):
        response = await alice.post(f"/projects/{team.slug}/ideas", idea | {field: NUL})
        body = assert_problem(response, 422, "validation_error")
        assert body["errors"][0]["loc"] == ["body", field]
    response = await alice.post(f"/projects/{team.slug}/ideas", idea | {"tags": [NUL]})
    assert_problem(response, 422, "validation_error")
    IdeaCreate.model_validate(idea)  # the same body without NUL is fine


@pytest.mark.parametrize("bad", ["Line one\r\nBcc: x@evil.test", "Tab\there", "Bell\x07"])
async def test_control_characters_in_titles_and_display_names_are_a_422(
    api: AsUser, team: Team, db_session: AsyncSession, bad: str
) -> None:
    """Idea titles and display names go into email subjects and plain-text emails, so
    they are one line (QA K3-1); multi-line text (summary, description) is unchanged."""
    alice = await api(team.member)
    idea = {"title": "Self-service refunds", "summary": "Refund\nwithout calling us."}
    created = await alice.post(f"/projects/{team.slug}/ideas", idea | {"title": bad})
    body = assert_problem(created, 422, "validation_error")
    assert body["errors"][0]["loc"] == ["body", "title"]

    existing = await make_idea(db_session, team.project, submitted_by=team.member)
    key = f"{team.project.key}-{existing.number}"
    edited = await alice.patch(f"/ideas/{key}", {"title": bad})
    assert_problem(edited, 422, "validation_error")

    admin = await api(team.platform)
    person = {"email": f"k31.{uuid4().hex[:8]}@example.com", "display_name": bad}
    assert_problem(await admin.post("/admin/users", person), 422, "validation_error")
    assert_problem(
        await admin.patch(f"/admin/users/{team.member.id}", {"display_name": bad}),
        422,
        "validation_error",
    )
    ok_create = await alice.post(f"/projects/{team.slug}/ideas", idea)
    assert ok_create.status_code == 201, ok_create.text


# --- Query and path parameters ---------------------------------------------------------------
def _cursor(values: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(values).encode()).decode().rstrip("=")


def _string_params(app: FastAPI) -> list[tuple[str, str, str]]:
    """(path, method, parameter) for every string-typed query or path parameter of the
    implemented operations (contract stubs answer 501 until they are built)."""
    found = []
    for path, operations in app.openapi()["paths"].items():
        for method, operation in operations.items():
            if operation["operationId"] in STUBS:
                continue
            for parameter in operation.get("parameters", []):
                if parameter["in"] in ("query", "path") and "string" in json.dumps(
                    parameter["schema"]
                ):
                    found.append((path, method, parameter["name"]))
    return found


async def test_nul_in_any_query_or_path_parameter_is_never_a_500(
    app: FastAPI, api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea = await make_idea(db_session, team.project)
    admin = await api(team.platform)
    valid = {
        "slug": team.slug,
        "idea": f"{team.project.key}-{idea.number}",
        "user_id": str(team.member.id),
        "comment_id": str(uuid4()),
        "group_id": str(uuid4()),
        "identity_id": str(uuid4()),
        "notification_id": str(uuid4()),
        "email_id": str(uuid4()),
    }
    params = _string_params(app)
    assert {name for _, _, name in params} >= {"q", "tag", "cursor", "slug", "idea", "project"}

    for path, method, name in params:
        encoded = quote(NUL, safe="")  # httpx refuses a raw NUL in a URL
        url = path.format(
            **{key: encoded if key == name else value for key, value in valid.items()}
        )
        query = {} if f"{{{name}}}" in path else {name: NUL}
        response = await admin.http.request(method.upper(), url, params=query)
        assert response.status_code < 500, (method, path, name, response.text)
        assert response.status_code in (400, 404, 405, 422), (method, path, name, response.text)


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/search", {"q": NUL}),
        ("/users", {"q": NUL}),
        ("/projects/{slug}/ideas", {"q": NUL}),
        ("/projects/{slug}/ideas", {"tag": NUL}),
        ("/projects/{slug}/board", {"q": NUL}),
        ("/projects/{slug}/board", {"tag": NUL}),
    ],
)
async def test_nul_in_search_text_is_a_422(
    api: AsUser, team: Team, path: str, params: dict[str, str]
) -> None:
    alice = await api(team.member)
    response = await alice.get(path.format(slug=team.slug), **params)
    assert_problem(response, 422, "validation_error")


@pytest.mark.parametrize(
    ("path", "params", "cursor"),
    [
        (
            "/projects/{slug}/ideas",
            {"sort": "title"},
            {"sort": "title", "v": NUL, "id": str(uuid4())},
        ),
        ("/users", {}, {"n": NUL, "id": str(uuid4())}),
        ("/users", {}, {"n": "x", "id": str(uuid4()), "extra": NUL}),
    ],
)
async def test_a_cursor_carrying_nul_is_invalid(
    api: AsUser, team: Team, path: str, params: dict[str, str], cursor: dict[str, Any]
) -> None:
    alice = await api(team.member)
    response = await alice.get(path.format(slug=team.slug), **params, cursor=_cursor(cursor))
    assert_problem(response, 400, "invalid_cursor")


async def test_nul_in_a_cookie_is_just_not_signed_in(client: httpx.AsyncClient) -> None:
    client.cookies.set("soundings_session", NUL)
    response = await client.get(f"{API}/auth/me")
    assert response.status_code == 401
