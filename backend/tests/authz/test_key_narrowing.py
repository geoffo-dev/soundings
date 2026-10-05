"""Keys over HTTP (contract-phase5 sections 3.3 and 3.8 "Restriction", "Owner roles",
"Service accounts"): a project-restricted key reaches only its projects (404 elsewhere;
lists, the board, counts, search and My work hold only them), a platform admin's key is
narrowed the same way, a restriction to a deleted project reaches nothing, the owner's
role decides inside the scopes, nothing irreversible happens through a key, and writes
through a key are audited as such."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import AuditLog
from app.models.api_key import ApiKey
from app.models.enums import EvaluatorState, HoldReason, IdeaStatus
from app.models.idea import Idea
from app.models.project import Project
from app.services.scoring import recompute_aggregates
from tests.api_keys.helpers import API, World, key_client, key_row, make_key, problem
from tests.factories import add_evaluator, criteria, make_idea, make_project


def ok(response: httpx.Response, status: int = 200) -> Any:
    assert response.status_code == status, response.text
    return response.json() if response.content else None


class Ideas:
    """Carol's ideas: one she submitted and owns in each project she belongs to, plus
    one she is asked to evaluate in each."""

    def __init__(self, **ideas: Idea) -> None:
        self.__dict__.update(ideas)

    cust_own: Idea
    tools_own: Idea
    cust_eval: Idea
    tools_eval: Idea
    secret: Idea


@pytest.fixture
async def ideas(world: World, db_session: AsyncSession) -> Ideas:
    found = Ideas(
        cust_own=await make_idea(
            db_session,
            world.cust,
            title="Refund faster",
            submitted_by=world.carol,
            owner=world.carol,
        ),
        tools_own=await make_idea(
            db_session,
            world.tools,
            title="Refund tooling",
            submitted_by=world.carol,
            owner=world.carol,
        ),
        cust_eval=await make_idea(
            db_session, world.cust, title="Loyalty refund", status=IdeaStatus.EVALUATING
        ),
        tools_eval=await make_idea(
            db_session, world.tools, title="Refund bot", status=IdeaStatus.EVALUATING
        ),
        secret=await make_idea(db_session, world.secret, title="Secret refund"),
    )
    await add_evaluator(db_session, found.cust_eval, world.carol)
    await add_evaluator(db_session, found.tools_eval, world.carol)
    return found


def _key(idea: Idea, project: Project) -> str:
    return f"{project.key}-{idea.number}"


# --- Project restriction --------------------------------------------------------------------------
async def test_a_restricted_key_sees_only_its_projects_in_every_list(
    app: FastAPI, world: World, ideas: Ideas, db_session: AsyncSession
) -> None:
    key = await make_key(db_session, world.carol, scopes=["read"], project_ids=[world.cust.id])

    async with key_client(app, key) as http:
        projects = ok(await http.get(f"{API}/projects"))
        listed = ok(await http.get(f"{API}/projects/{world.cust.slug}/ideas"))
        board = ok(await http.get(f"{API}/projects/{world.cust.slug}/board"))
        search = ok(await http.get(f"{API}/search", params={"q": "refund"}))
        work = ok(await http.get(f"{API}/me/work"))
        owned = ok(await http.get(f"{API}/me/owned-ideas"))
        users = ok(await http.get(f"{API}/users", params={"q": "lena"}))

    assert [p["slug"] for p in projects] == ["customer-innovation"]
    assert {i["key"] for i in listed["items"]} == {
        _key(ideas.cust_own, world.cust),
        _key(ideas.cust_eval, world.cust),
    }
    on_board = {i["key"] for column in board["columns"] for i in column["items"]}
    assert on_board == {_key(ideas.cust_own, world.cust), _key(ideas.cust_eval, world.cust)}
    assert {i["key"] for i in search["ideas"]} == {
        _key(ideas.cust_own, world.cust),
        _key(ideas.cust_eval, world.cust),
    }
    assert {p["slug"] for p in search["projects"]} <= {"customer-innovation"}
    assert [e["idea"]["key"] for e in work["evaluations_due"]] == [
        _key(ideas.cust_eval, world.cust)
    ]
    assert work["counts"]["evaluations_due"] == 1
    assert work["counts"]["owned_open"] == 1
    assert {i["key"] for group in work["owned"] for i in group["ideas"]} == {
        _key(ideas.cust_own, world.cust)
    }
    assert {r["idea"]["key"] for r in work["recent"]} <= {
        _key(ideas.cust_own, world.cust),
        _key(ideas.cust_eval, world.cust),
    }
    assert [i["key"] for i in owned["items"]] == [_key(ideas.cust_own, world.cust)]
    # People aren't project data: the directory is the same for every signed-in person.
    assert [u["display_name"] for u in users["items"]] == ["Lena Lead"]


async def test_everything_outside_the_restriction_is_404(
    app: FastAPI, world: World, ideas: Ideas, db_session: AsyncSession
) -> None:
    key = await make_key(db_session, world.carol, project_ids=[world.cust.id])
    tools, idea = world.tools.slug, _key(ideas.tools_own, world.tools)
    criterion = (await criteria(db_session, world.tools))[0]

    async with key_client(app, key) as http:
        responses = {
            "project": await http.get(f"{API}/projects/{tools}"),
            "ideas": await http.get(f"{API}/projects/{tools}/ideas"),
            "board": await http.get(f"{API}/projects/{tools}/board"),
            "members": await http.get(f"{API}/projects/{tools}/members"),
            "tags": await http.get(f"{API}/projects/{tools}/tags"),
            "access": await http.get(f"{API}/projects/{tools}/access"),
            "users": await http.get(f"{API}/users", params={"q": "lena", "project": tools}),
            "idea": await http.get(f"{API}/ideas/{idea}"),
            "by_id": await http.get(f"{API}/ideas/{ideas.tools_own.id}"),
            "evaluations": await http.get(f"{API}/ideas/{idea}/evaluations"),
            "activity": await http.get(f"{API}/ideas/{idea}/activity"),
            "proposal": await http.get(f"{API}/ideas/{idea}/proposal"),
            "markdown": await http.get(f"{API}/ideas/{idea}/proposal/markdown"),
            "create": await http.post(
                f"{API}/projects/{tools}/ideas", json={"title": "T", "summary": "S"}
            ),
            "comment": await http.post(f"{API}/ideas/{idea}/comments", json={"body_md": "Hi"}),
            "evaluate": await http.put(
                f"{API}/ideas/{_key(ideas.tools_eval, world.tools)}/evaluations/me",
                json={"scores": [{"criterion_id": str(criterion.id), "score": 3}]},
            ),
            "status": await http.post(f"{API}/ideas/{idea}/status", json={"status": "evaluating"}),
        }

    for name, response in responses.items():
        assert response.status_code == 404, (name, response.text)
        assert response.json()["code"] == "not_found", name


async def test_a_platform_admins_restricted_key_is_narrowed_too(
    app: FastAPI, world: World, ideas: Ideas, db_session: AsyncSession
) -> None:
    key = await make_key(db_session, world.platform, scopes=["read"], project_ids=[world.cust.id])

    async with key_client(app, key) as http:
        projects = ok(await http.get(f"{API}/projects"))
        secret = await http.get(f"{API}/projects/{world.secret.slug}")
        idea = await http.get(f"{API}/ideas/{_key(ideas.secret, world.secret)}")
        search = ok(await http.get(f"{API}/search", params={"q": "secret"}))

    assert [p["slug"] for p in projects] == ["customer-innovation"]
    problem(secret, 404, "not_found")
    problem(idea, 404, "not_found")
    assert search["ideas"] == []


async def test_a_restriction_to_a_deleted_project_reaches_nothing(
    app: FastAPI, world: World, db_session: AsyncSession
) -> None:
    gone = await make_project(db_session, slug="gone", key="GONE", name="Gone")
    key = await make_key(db_session, world.platform, scopes=["read"], project_ids=[gone.id])
    await db_session.execute(delete(Project).where(Project.id == gone.id))
    await db_session.commit()
    assert (await key_row(db_session, key)).project_ids == [gone.id]  # never widened

    async with key_client(app, key) as http:
        projects = ok(await http.get(f"{API}/projects"))
        cust = await http.get(f"{API}/projects/{world.cust.slug}")
        work = ok(await http.get(f"{API}/me/work"))

    assert projects == []
    problem(cust, 404, "not_found")
    assert work["recent"] == []


async def test_an_unrestricted_key_reaches_every_project_its_owner_can(
    app: FastAPI, world: World, ideas: Ideas, db_session: AsyncSession
) -> None:
    key = await make_key(db_session, world.carol, scopes=["read"])

    async with key_client(app, key) as http:
        projects = ok(await http.get(f"{API}/projects"))
        secret = await http.get(f"{API}/projects/{world.secret.slug}")

    assert sorted(p["slug"] for p in projects) == ["customer-innovation", "internal-tools"]
    problem(secret, 404, "not_found")  # the owner can't see it either


# --- The owner's role inside the scopes -----------------------------------------------------------
async def test_the_owners_role_decides_within_the_scopes(
    app: FastAPI, world: World, ideas: Ideas, db_session: AsyncSession
) -> None:
    body = {"title": "Faster refunds", "summary": "Refund without a call."}
    path = f"{API}/projects/{world.cust.slug}/ideas"
    viewer = await make_key(db_session, world.vic, scopes=["write"])
    reader = await make_key(db_session, world.carol, scopes=["read"], name="Reader")
    writer = await make_key(db_session, world.carol, scopes=["write"], name="Writer")

    async with key_client(app, viewer) as as_viewer:
        problem(await as_viewer.post(path, json=body), 403, "forbidden")
    async with key_client(app, reader) as as_reader:
        problem(await as_reader.post(path, json=body), 403, "insufficient_scope")
        detail = ok(await as_reader.get(f"{API}/ideas/{_key(ideas.cust_own, world.cust)}"))
    async with key_client(app, writer) as as_writer:
        created = ok(await as_writer.post(path, json=body), 201)

    assert created["submitted_by"]["id"] == str(world.carol.id)
    # Flags are computed for the key: a read key can't edit or comment.
    assert detail["permissions"]["can_edit"] is False
    assert detail["permissions"]["can_comment"] is False
    assert detail["permissions"]["can_delete"] is False


async def test_evaluating_needs_the_evaluate_scope(
    app: FastAPI, world: World, ideas: Ideas, db_session: AsyncSession
) -> None:
    scores = [
        {"criterion_id": str(c.id), "score": 4} for c in await criteria(db_session, world.cust)
    ]
    body = {"scores": scores, "recommendation": "go", "submit": True}
    path = f"{API}/ideas/{_key(ideas.cust_eval, world.cust)}/evaluations/me"
    writer = await make_key(db_session, world.carol, scopes=["write"], name="Writer")
    evaluator = await make_key(db_session, world.carol, scopes=["evaluate"], name="Evaluator")

    async with key_client(app, writer) as http:
        problem(await http.put(path, json=body), 403, "insufficient_scope")
    async with key_client(app, evaluator) as http:
        saved = ok(await http.put(path, json=body))
        detail = ok(await http.get(f"{API}/ideas/{_key(ideas.cust_eval, world.cust)}"))

    assert saved["state"] == "submitted"
    assert detail["permissions"]["can_evaluate"] is True


async def test_a_pending_evaluators_key_gets_no_score_data(
    app: FastAPI, world: World, ideas: Ideas, db_session: AsyncSession
) -> None:
    for person in (world.lead, world.vic):
        await add_evaluator(db_session, ideas.cust_eval, person, state=EvaluatorState.SUBMITTED)
    await recompute_aggregates(db_session, idea_ids=[ideas.cust_eval.id])
    await db_session.commit()
    key = await make_key(db_session, world.carol, scopes=["read", "evaluate"])
    ref = _key(ideas.cust_eval, world.cust)

    async with key_client(app, key) as http:
        detail = ok(await http.get(f"{API}/ideas/{ref}"))
        evaluations = ok(await http.get(f"{API}/ideas/{ref}/evaluations"))
        listed = ok(await http.get(f"{API}/projects/{world.cust.slug}/ideas"))

    assert (detail["score"], detail["score_hidden"], detail["aggregate"]) == (None, True, None)
    assert (evaluations["items"], evaluations["score_hidden"]) == ([], True)
    row = next(i for i in listed["items"] if i["key"] == ref)
    assert (row["score"], row["score_hidden"]) == (None, True)


# --- Nothing irreversible through a key -----------------------------------------------------------
async def test_deleting_and_moderating_ideas_need_a_session(
    app: FastAPI, world: World, ideas: Ideas, db_session: AsyncSession
) -> None:
    held = await make_idea(db_session, world.cust, title="Held")
    await db_session.execute(
        update(Idea).where(Idea.id == held.id).values(held_for=HoldReason.MODERATION)
    )
    await db_session.commit()
    key = await make_key(db_session, world.lead)  # project admin, every scope

    async with key_client(app, key) as http:
        deleted = await http.delete(f"{API}/ideas/{_key(ideas.cust_own, world.cust)}")
        approved = await http.post(f"{API}/ideas/{held.id}/submission/approve")
        rejected = await http.post(f"{API}/ideas/{held.id}/submission/reject", json={})
        queue = await http.get(f"{API}/projects/{world.cust.slug}/moderation")

    for response in (deleted, approved, rejected, queue):
        problem(response, 403, "insufficient_scope")
    assert await db_session.get(Idea, ideas.cust_own.id) is not None


# --- Service accounts (contract-phase5 section 3.7) -----------------------------------------------
async def test_a_service_account_never_volunteers_as_owner(
    app: FastAPI, world: World, db_session: AsyncSession
) -> None:
    idea = await make_idea(db_session, world.cust, status=IdeaStatus.NEW)
    key = await make_key(db_session, world.bot, scopes=["read", "write"])

    async with key_client(app, key) as http:
        response = await http.post(f"{API}/ideas/{idea.id}/volunteer")

    problem(response, 403, "forbidden")


# --- Writes through a key are audited as such -----------------------------------------------------
async def test_writes_through_a_key_are_audited_with_the_key(
    app: FastAPI, world: World, ideas: Ideas, db_session: AsyncSession
) -> None:
    key = await make_key(db_session, world.lead, scopes=["write"])
    key_id = str((await key_row(db_session, key)).id)

    async with key_client(app, key) as http:
        ok(
            await http.post(
                f"{API}/ideas/{_key(ideas.cust_own, world.cust)}/status",
                json={"status": "evaluating"},
            )
        )

    entry = await db_session.scalar(select(AuditLog).where(AuditLog.action == "idea.status_change"))
    assert entry is not None
    assert entry.actor_id == world.lead.id
    assert entry.details["auth"] == "api_key"
    assert entry.details["api_key_id"] == key_id
    assert "auth_method" not in entry.details
    stored = await db_session.scalar(select(ApiKey.secret_hash))
    assert stored is not None
    assert key not in str(entry.details)
    assert stored not in str(entry.details)
