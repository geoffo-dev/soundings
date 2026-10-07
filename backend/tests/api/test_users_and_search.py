"""People search (``search_users``) and the command palette (``global_search``)."""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import EvaluatorState, IdeaStatus, ProjectRole, ProjectVisibility, Resolution
from app.models.idea import Idea
from tests.conftest import Login
from tests.factories import add_evaluator, make_idea, make_project, make_user


def assert_problem(response: httpx.Response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    assert response.json()["code"] == code


# --- search_users ---------------------------------------------------------------------------
async def test_search_users_by_name_or_email(login: Login, db_session: AsyncSession) -> None:
    ada = await make_user(db_session, "Ada Lovelace", email="ada@example.com")
    await make_user(db_session, "Grace Hopper", email="grace@navy.example")
    await make_user(db_session, "adam smith", email="adam@example.com")
    await make_user(db_session, "Ada Gone", active=False)
    await make_user(db_session, "Ada Agent", service_account=True)
    http = await login(ada)

    by_name = await http.get("/api/v1/users", params={"q": "ADA"})
    by_email = await http.get("/api/v1/users", params={"q": "navy"})
    everyone = await http.get("/api/v1/users")

    assert by_name.status_code == 200
    assert [u["display_name"] for u in by_name.json()["items"]] == ["Ada Lovelace", "adam smith"]
    assert by_name.json()["next_cursor"] is None
    assert by_name.json()["items"][0] == {
        "id": str(ada.id),
        "display_name": "Ada Lovelace",
        "avatar_url": None,
        "initials": "AL",
        "email": "ada@example.com",
        "project_role": None,
    }
    assert [u["display_name"] for u in by_email.json()["items"]] == ["Grace Hopper"]
    assert len(everyone.json()["items"]) == 3


async def test_search_users_treats_wildcards_literally(
    login: Login, db_session: AsyncSession
) -> None:
    ada = await make_user(db_session, "Ada 100% Lovelace")
    await make_user(db_session, "Bob Builder")
    http = await login(ada)

    percent = await http.get("/api/v1/users", params={"q": "%"})
    underscore = await http.get("/api/v1/users", params={"q": "_"})

    assert [u["display_name"] for u in percent.json()["items"]] == ["Ada 100% Lovelace"]
    assert underscore.json()["items"] == []


async def test_search_users_pages(login: Login, db_session: AsyncSession) -> None:
    names = ["Cara", "anna", "Bea", "Dan", "eve"]
    users = [await make_user(db_session, name) for name in names]
    http = await login(users[0])

    first = (await http.get("/api/v1/users", params={"limit": 2})).json()
    second = (
        await http.get("/api/v1/users", params={"limit": 2, "cursor": first["next_cursor"]})
    ).json()
    third = (
        await http.get("/api/v1/users", params={"limit": 2, "cursor": second["next_cursor"]})
    ).json()

    pages = [[u["display_name"] for u in page["items"]] for page in (first, second, third)]
    assert pages == [["anna", "Bea"], ["Cara", "Dan"], ["eve"]]
    assert third["next_cursor"] is None
    assert_problem(
        await http.get("/api/v1/users", params={"cursor": "not-a-cursor"}), 400, "invalid_cursor"
    )


async def test_search_users_in_a_project(login: Login, db_session: AsyncSession) -> None:
    admin = await make_user(db_session, "Ann Admin")
    viewer = await make_user(db_session, "Vic Viewer")
    await make_user(db_session, "Oscar Outsider")
    await make_project(
        db_session, slug="cust", members={admin: ProjectRole.ADMIN, viewer: ProjectRole.VIEWER}
    )
    await make_project(db_session, slug="secret")
    http = await login(admin)

    response = await http.get("/api/v1/users", params={"project": "cust"})
    hidden = await http.get("/api/v1/users", params={"project": "secret"})

    assert [(u["display_name"], u["project_role"]) for u in response.json()["items"]] == [
        ("Ann Admin", "admin"),
        ("Vic Viewer", "viewer"),
    ]
    assert_problem(hidden, 404, "not_found")


async def test_search_users_errors(
    client: httpx.AsyncClient, login: Login, db_session: AsyncSession
) -> None:
    http = await login(await make_user(db_session))

    assert_problem(await client.get("/api/v1/users"), 401, "unauthorized")
    assert_problem(
        await http.get("/api/v1/users", params={"project": "Bad Slug"}), 422, "validation_error"
    )
    assert_problem(await http.get("/api/v1/users", params={"limit": 0}), 422, "validation_error")


# --- global_search --------------------------------------------------------------------------
async def test_search_finds_ideas_and_projects(login: Login, db_session: AsyncSession) -> None:
    ada = await make_user(db_session)
    project = await make_project(
        db_session,
        slug="refunds",
        key="CUST",
        name="Customer refunds",
        members={ada: ProjectRole.MEMBER},
    )
    project.status_labels = {"accepted": "Go"}
    await db_session.commit()
    await make_idea(db_session, project, title="Refunds")
    await make_idea(db_session, project, title="Pricing page", summary="Fewer refund requests")
    await make_idea(
        db_session,
        project,
        title="Old refund idea",
        status=IdeaStatus.CLOSED,
        resolution=Resolution.ACCEPTED,
    )
    await make_idea(db_session, project, title="Unrelated")
    http = await login(ada)

    response = await http.get("/api/v1/search", params={"q": "refund"})

    assert response.status_code == 200
    body = response.json()
    assert body["ideas"][0]["title"] == "Refunds"  # the most similar title first
    assert {idea["title"] for idea in body["ideas"]} == {
        "Refunds",
        "Pricing page",
        "Old refund idea",
    }
    closed = next(idea for idea in body["ideas"] if idea["title"] == "Old refund idea")
    assert closed["status_label"] == "Go"
    assert closed["key"] == "CUST-3"
    assert closed["project"] == {
        "id": str(project.id),
        "slug": "refunds",
        "key": "CUST",
        "name": "Customer refunds",
    }
    assert [p["slug"] for p in body["projects"]] == ["refunds"]


async def test_one_or_two_letters_match_titles_most_recent_first(
    login: Login, db_session: AsyncSession
) -> None:
    """Performance review B6: pg_trgm can't narrow one or two letters, so the palette's
    first keystrokes match titles only and list the most recently active first, read
    along the activity index instead of ranking every match."""
    from datetime import UTC, datetime, timedelta

    ada = await make_user(db_session)
    project = await make_project(db_session, members={ada: ProjectRole.MEMBER})
    now = datetime.now(UTC)
    for n, (title, summary) in enumerate(
        [("Pricing page", ""), ("Print less", ""), ("Refunds", "Pricing problems"), ("Apron", "")]
    ):
        await make_idea(
            db_session,
            project,
            title=title,
            summary=summary,
            last_activity_at=now - timedelta(hours=n),
        )
    http = await login(ada)

    short = (await http.get("/api/v1/search", params={"q": "pr"})).json()
    longer = (await http.get("/api/v1/search", params={"q": "pri"})).json()

    assert [i["title"] for i in short["ideas"]] == ["Pricing page", "Print less", "Apron"]
    assert {i["title"] for i in longer["ideas"]} == {"Pricing page", "Print less", "Refunds"}


async def test_exact_key_comes_first(login: Login, db_session: AsyncSession) -> None:
    ada = await make_user(db_session)
    project = await make_project(db_session, key="CUST", members={ada: ProjectRole.MEMBER})
    for n in range(1, 13):
        await make_idea(db_session, project, title=f"Idea about cust-12 number {n}")
    http = await login(ada)

    response = await http.get("/api/v1/search", params={"q": "cust-12", "limit": 3})

    ideas = response.json()["ideas"]
    assert ideas[0]["key"] == "CUST-12"
    assert len(ideas) == 3
    assert len({idea["key"] for idea in ideas}) == 3


async def test_search_respects_visibility(login: Login, db_session: AsyncSession) -> None:
    ada = await make_user(db_session)
    other = await make_user(db_session)
    mine = await make_project(
        db_session, slug="mine", name="Mine", members={ada: ProjectRole.VIEWER}
    )
    secret = await make_project(
        db_session,
        slug="secret",
        key="SEC",
        name="Secret plans",
        members={other: ProjectRole.ADMIN},
    )
    internal = await make_project(
        db_session, slug="open", name="Open plans", visibility=ProjectVisibility.INTERNAL
    )
    archived = await make_project(
        db_session, slug="old", name="Old plans", members={ada: ProjectRole.MEMBER}, archived=True
    )
    await make_idea(db_session, mine, title="Plans we share")
    await make_idea(db_session, secret, title="Plans for world domination")
    await make_idea(db_session, internal, title="Plans for everyone")
    await make_idea(db_session, archived, title="Plans from last year")
    http = await login(ada)

    body = (await http.get("/api/v1/search", params={"q": "plans"})).json()
    by_key = (await http.get("/api/v1/search", params={"q": "SEC-1"})).json()

    assert {idea["title"] for idea in body["ideas"]} == {"Plans we share", "Plans for everyone"}
    assert [p["name"] for p in body["projects"]] == ["Open plans"]
    assert by_key == {"ideas": [], "projects": []}


async def test_search_never_returns_scores(login: Login, db_session: AsyncSession) -> None:
    ada = await make_user(db_session)
    bob = await make_user(db_session)
    project = await make_project(
        db_session, members={ada: ProjectRole.MEMBER, bob: ProjectRole.MEMBER}
    )
    idea = await make_idea(db_session, project, title="Scored idea")
    await add_evaluator(db_session, idea, bob, state=EvaluatorState.SUBMITTED)
    await db_session.execute(
        update(Idea)
        .where(Idea.id == idea.id)
        .values(aggregate_score=Decimal("4.2"), aggregate_count=1)
    )
    await db_session.commit()
    http = await login(ada)

    response = await http.get("/api/v1/search", params={"q": "scored"})

    [hit] = response.json()["ideas"]
    assert set(hit) == {
        "id",
        "key",
        "number",
        "project",
        "title",
        "status",
        "resolution",
        "status_label",
    }
    assert "4.2" not in response.text


@pytest.mark.parametrize("params", [{"q": ""}, {}, {"q": "x" * 201}, {"q": "a", "limit": 21}])
async def test_search_validation(
    login: Login, db_session: AsyncSession, params: dict[str, object]
) -> None:
    http = await login(await make_user(db_session))

    assert_problem(await http.get("/api/v1/search", params=params), 422, "validation_error")  # type: ignore[arg-type]


async def test_search_needs_a_session(client: httpx.AsyncClient) -> None:
    assert_problem(await client.get("/api/v1/search", params={"q": "x"}), 401, "unauthorized")


async def test_whitespace_search_finds_nothing(login: Login, db_session: AsyncSession) -> None:
    ada = await make_user(db_session)
    await make_project(db_session, name="Anything", members={ada: ProjectRole.MEMBER})
    http = await login(ada)

    assert (await http.get("/api/v1/search", params={"q": "   "})).json() == {
        "ideas": [],
        "projects": [],
    }
