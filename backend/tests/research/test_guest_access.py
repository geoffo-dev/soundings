"""Phase 8b: a guest researcher (role matrix column R, table L; contract-phase8b section 4)
through the real routes and MCP tools.

The scene: a private project with its research step on; an idea with two submitted
evaluations and an AI agent's evaluation (aggregate cached), an evaluation due date, a
proposal, a member's comment, an AI research note and the evaluation events in its feed;
an outsider (no role in the project) asked by the project admin to research it.

* Every idea route of table L as the guest: ``view`` 2xx, ``rule`` 403 or allowed,
  ``hidden`` 404; the same requests as the outsider before the assignment: 404; every
  project route: 404.
* No score data on any path: the idea, the feed (none of the evaluation events), search,
  My work, Similar ideas, the inbox, MCP ``get_idea`` / ``search_ideas``.
* Access ends at once: handing back, reassigning, closing, the step off, archiving,
  deleting, deactivating; REST and MCP and the inbox.
* API keys: key ∩ person ∩ policy (an unrestricted key reads as R; a restricted key
  reaches the idea only when its projects allow it, then only as R).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import RESEARCH_GUEST_ACCESS, GuestAccess
from app.models.activity import ActivityEvent
from app.models.base import utcnow
from app.models.enums import (
    EvaluatorState,
    IdeaStatus,
    NotificationMode,
    NotificationType,
    ProjectRole,
    ResearchStep,
)
from app.models.idea import Idea
from app.models.notification import Notification
from app.models.project import Project
from app.models.proposal import Proposal
from app.models.research import ResearchChecklistItem
from app.models.user import User
from app.schemas.activity import EVALUATION_ACTIVITY_TYPES, RESEARCH_GUEST_ACTIVITY_TYPES
from app.services.scoring import recompute_aggregates
from tests.factories import add_evaluator, add_member, make_idea, make_project, make_user
from tests.mcp.conftest import AsAgent
from tests.research.conftest import (
    API,
    AsUser,
    Team,
    assert_problem,
    assign,
    key_of,
    ok,
    set_step,
)
from tests.test_contract_routes import CONTRACT

DUE = "2026-12-11T17:00:00+00:00"
READ = ["read", "mcp"]
WRITE = ["read", "write", "mcp"]


@dataclass
class Scene:
    idea: Idea
    key: str
    items: list[ResearchChecklistItem]
    comment_id: str
    note_id: UUID
    agent: User
    guest: User


@pytest.fixture
async def scene(api: AsUser, team: Team, db_session: AsyncSession) -> Scene:
    items = await set_step(db_session, team.project, ResearchStep.BEFORE_PROPOSAL)
    idea = await make_idea(
        db_session,
        team.project,
        owner=team.owner,
        status=IdeaStatus.EVALUATING,
        title="Self-service refunds portal",
        summary="Customers refund small orders themselves.",
    )
    key = key_of(team.project, idea)
    agent = await make_user(db_session, "Idea evaluator", service_account=True)
    high = {c.name: 5 for c in team.rubric}
    low = {c.name: 1 for c in team.rubric}
    await add_evaluator(
        db_session, idea, team.evaluators[0], state=EvaluatorState.SUBMITTED, scores=high
    )
    await add_evaluator(
        db_session, idea, team.evaluators[1], state=EvaluatorState.SUBMITTED, scores=low
    )
    await add_evaluator(
        db_session, idea, agent, state=EvaluatorState.SUBMITTED, include_in_aggregate=False
    )
    await recompute_aggregates(db_session, idea_ids=[idea.id])
    await db_session.execute(
        update(Idea).where(Idea.id == idea.id).values(evaluation_due_at=utcnow())
    )
    db_session.add(Proposal(id=uuid4(), idea_id=idea.id, created_by_id=team.owner.id))
    note_id = uuid4()
    for type_, payload, actor in (
        ("evaluator_added", {"evaluator_id": str(team.evaluators[0].id)}, team.owner.id),
        ("evaluation_submitted", {"evaluator_id": str(agent.id)}, agent.id),
        ("due_date_changed", {"from_due_at": None, "to_due_at": utcnow().isoformat()}, None),
        (
            "ai_research_note",
            {"run_id": str(uuid4()), "agent_id": str(uuid4()), "body_md": "Found two vendors."},
            agent.id,
        ),
    ):
        db_session.add(
            ActivityEvent(
                id=note_id if type_ == "ai_research_note" else uuid4(),
                project_id=team.project.id,
                idea_id=idea.id,
                actor_id=actor,
                type=type_,
                payload={**payload, "sources": []} if type_ == "ai_research_note" else payload,
            )
        )
    await db_session.commit()
    comment = ok(
        await (await api(team.member)).post(f"/ideas/{key}/comments", {"body_md": "Nice one."}),
        201,
    )
    ok(await assign(await api(team.admin), key, team.outsider, DUE))
    return Scene(
        idea=idea,
        key=key,
        items=items,
        comment_id=comment["comment"]["id"],
        note_id=note_id,
        agent=agent,
        guest=team.outsider,
    )


# --- Every idea route ----------------------------------------------------------------------
X = str(uuid4())  # a sub-resource nobody has
# operation -> (method, path, body, the guest's outcome: "ok" | 403 | 404)
ROUTES: dict[str, tuple[str, str, Any, object]] = {
    # view
    "get_idea": ("GET", "/ideas/{key}", None, "ok"),
    "list_idea_activity": ("GET", "/ideas/{key}/activity", None, "ok"),
    "watch_idea": ("PUT", "/ideas/{key}/watch", None, "ok"),
    "unwatch_idea": ("DELETE", "/ideas/{key}/watch", None, "ok"),
    "get_idea_research": ("GET", "/ideas/{key}/research", None, "ok"),
    "list_similar_ideas": ("GET", "/ideas/{key}/similar-ideas", None, "ok"),
    "get_research_note": ("GET", "/ideas/{key}/research-notes/{note}", None, "ok"),
    # rule: the researcher overlay grants these
    "create_comment": ("POST", "/ideas/{key}/comments", {"body_md": "Asked Legal."}, "ok"),
    "answer_research_item": (
        "PUT",
        "/ideas/{key}/research/items/{item}",
        {"answer": "Legal (contracts team), 3 Oct: fine."},
        "ok",
    ),
    "clear_research_item": ("DELETE", "/ideas/{key}/research/items/{item}", None, "ok"),
    "remove_researcher": ("DELETE", "/ideas/{key}/research/assignment", None, "ok"),
    # rule: R's cells say 403
    "update_comment": ("PATCH", "/comments/{comment}", {"body_md": "Edited"}, 403),
    "delete_comment": ("DELETE", "/comments/{comment}", None, 403),
    "update_idea": ("PATCH", "/ideas/{key}", {"title": "Mine now"}, 403),
    "delete_idea": ("DELETE", "/ideas/{key}", None, 403),
    "change_idea_status": ("POST", "/ideas/{key}/status", {"status": "shortlisted"}, 403),
    "set_idea_owner": ("PUT", "/ideas/{key}/owner", {"user_id": None}, 403),
    "volunteer_as_owner": ("POST", "/ideas/{key}/volunteer", None, 403),
    "vote_idea": ("PUT", "/ideas/{key}/vote", None, 403),
    "unvote_idea": ("DELETE", "/ideas/{key}/vote", None, 403),
    "set_research_assignment": (
        "PUT",
        "/ideas/{key}/research/assignment",
        {"researcher_id": None, "due_at": None},
        403,
    ),
    "delete_research_note": ("DELETE", "/ideas/{key}/research-notes/{note}", None, 403),
    # hidden: the evaluation area
    "add_evaluators": ("POST", "/ideas/{key}/evaluators", {"user_ids": [X]}, 404),
    "remove_evaluator": ("DELETE", "/ideas/{key}/evaluators/{evaluator}", None, 404),
    "set_evaluation_due_date": (
        "PUT",
        "/ideas/{key}/evaluation/due-date",
        {"due_at": None},
        404,
    ),
    "close_evaluation": ("POST", "/ideas/{key}/evaluation/close", None, 404),
    "reopen_evaluation": ("POST", "/ideas/{key}/evaluation/reopen", None, 404),
    "list_evaluations": ("GET", "/ideas/{key}/evaluations", None, 404),
    "get_my_evaluation": ("GET", "/ideas/{key}/evaluations/me", None, 404),
    "save_my_evaluation": ("PUT", "/ideas/{key}/evaluations/me", {"scores": []}, 404),
    "set_evaluation_inclusion": (
        "PUT",
        f"/ideas/{{key}}/evaluations/{X}/include-in-aggregate",
        {"include": True},
        404,
    ),
    # hidden: the proposal
    "get_proposal": ("GET", "/ideas/{key}/proposal", None, 404),
    "create_proposal": ("POST", "/ideas/{key}/proposal", None, 404),
    "update_proposal_section": (
        "PUT",
        "/ideas/{key}/proposal/sections/summary",
        {"body_md": "x", "base_version": 1},
        404,
    ),
    "export_proposal_markdown": ("GET", "/ideas/{key}/proposal/markdown", None, 404),
    "export_proposal_pdf": ("GET", "/ideas/{key}/proposal/pdf", None, 404),
    "list_proposal_threads": ("GET", "/ideas/{key}/proposal/threads", None, 404),
    "create_proposal_thread": (
        "POST",
        "/ideas/{key}/proposal/threads",
        {"section_key": "summary", "body_md": "Source?"},
        404,
    ),
    "reply_to_proposal_thread": (
        "POST",
        f"/ideas/{{key}}/proposal/threads/{X}/comments",
        {"body_md": "Here."},
        404,
    ),
    "resolve_proposal_thread": ("PUT", f"/ideas/{{key}}/proposal/threads/{X}/resolved", None, 404),
    "reopen_proposal_thread": (
        "DELETE",
        f"/ideas/{{key}}/proposal/threads/{X}/resolved",
        None,
        404,
    ),
    "delete_proposal_comment": (
        "DELETE",
        f"/ideas/{{key}}/proposal/threads/{X}/comments/{X}",
        None,
        404,
    ),
    "list_proposal_suggestions": ("GET", "/ideas/{key}/proposal/suggestions", None, 404),
    "create_proposal_suggestion": (
        "POST",
        "/ideas/{key}/proposal/suggestions",
        {"section_key": "summary", "body_md": "x", "base_version": 1},
        404,
    ),
    "accept_proposal_suggestion": (
        "POST",
        f"/ideas/{{key}}/proposal/suggestions/{X}/accept",
        {"base_version": 1},
        404,
    ),
    "discard_proposal_suggestion": (
        "POST",
        f"/ideas/{{key}}/proposal/suggestions/{X}/discard",
        None,
        404,
    ),
    # hidden: the submission panel
    "get_idea_submission": ("GET", "/ideas/{key}/submission", None, 404),
    "approve_submission": ("POST", "/ideas/{key}/submission/approve", None, 404),
    "reject_submission": ("POST", "/ideas/{key}/submission/reject", None, 404),
    "erase_submitter": ("POST", "/ideas/{key}/submission/erase", None, 404),
    # hidden: the AI panel and its stream
    "list_idea_ai_runs": ("GET", "/ideas/{key}/ai-runs?kind=evaluate", None, 404),
    "request_ai_evaluation": ("POST", "/ideas/{key}/ai-runs/evaluation", {"agent_id": X}, 404),
    "request_ai_research": ("POST", "/ideas/{key}/ai-runs/research", {"agent_id": X}, 404),
    "request_ai_section_draft": (
        "POST",
        "/ideas/{key}/ai-runs/section-draft",
        {"agent_id": X, "section_key": "summary"},
        404,
    ),
    "get_ai_run": ("GET", f"/ideas/{{key}}/ai-runs/{X}", None, 404),
    "cancel_ai_run": ("POST", f"/ideas/{{key}}/ai-runs/{X}/cancel", None, 404),
    "stream_ai_run_events": ("GET", f"/ideas/{{key}}/ai-runs/{X}/events", None, 404),
}


def test_every_idea_route_of_the_guest_table_is_covered() -> None:
    rest = {
        operation
        for operation, access in RESEARCH_GUEST_ACCESS.items()
        if not operation.startswith("mcp.") and access is not GuestAccess.LIST
    }
    assert set(ROUTES) == rest
    for operation, (_, _, _, outcome) in ROUTES.items():
        access = RESEARCH_GUEST_ACCESS[operation]
        if access is GuestAccess.HIDDEN:
            assert outcome == 404, operation
        elif access is GuestAccess.VIEW:
            assert outcome == "ok", operation


def _url(scene: Scene, team: Team, path: str) -> str:
    return API + path.format(
        key=scene.key,
        note=scene.note_id,
        item=scene.items[0].id,
        comment=scene.comment_id,
        evaluator=team.evaluators[0].id,
    )


async def _send(
    client: httpx.AsyncClient, scene: Scene, team: Team, operation: str
) -> httpx.Response:
    method, path, body, _ = ROUTES[operation]
    return await client.request(method, _url(scene, team, path), json=body)


@pytest.mark.parametrize("operation", sorted(ROUTES))
async def test_the_guest_on_every_idea_route(
    api: AsUser, team: Team, scene: Scene, operation: str
) -> None:
    guest = await api(scene.guest)
    if operation == "clear_research_item":
        ok(
            await guest.put(
                f"/ideas/{scene.key}/research/items/{scene.items[0].id}", {"answer": "Done."}
            )
        )

    response = await _send(guest.http, scene, team, operation)

    outcome = ROUTES[operation][3]
    if outcome == "ok":
        assert response.status_code < 300, response.text
    else:
        assert response.status_code == outcome, response.text
        if outcome == 404:
            assert response.json()["code"] == "not_found"


@pytest.mark.parametrize("operation", sorted(ROUTES))
async def test_an_outsider_who_isnt_the_researcher_gets_404(
    api: AsUser, team: Team, scene: Scene, operation: str, db_session: AsyncSession
) -> None:
    stranger = await make_user(db_session, "Sam Stranger")

    response = await _send((await api(stranger)).http, scene, team, operation)

    assert_problem(response, 404, "not_found")


@pytest.mark.parametrize(
    "operation",
    [
        "list_evaluations",
        "get_proposal",
        "export_proposal_markdown",
        "list_proposal_threads",
        "list_proposal_suggestions",
    ],
)
async def test_the_hidden_routes_exist_for_the_owner(
    api: AsUser, team: Team, scene: Scene, operation: str
) -> None:
    response = await _send((await api(team.owner)).http, scene, team, operation)

    assert response.status_code != 404, response.text


_PROJECT_GETS = sorted(
    (path, operation)
    for method, path, operation in CONTRACT
    if method == "GET" and "{slug}" in path and "/public/" not in path
)


@pytest.mark.parametrize(("path", "operation"), _PROJECT_GETS)
async def test_every_project_route_is_404_for_the_guest(
    api: AsUser, team: Team, scene: Scene, path: str, operation: str
) -> None:
    response = await (await api(scene.guest)).http.get(path.replace("{slug}", team.slug))

    assert_problem(response, 404, "not_found")


async def test_the_guest_edits_and_deletes_only_their_own_comments(
    api: AsUser, team: Team, scene: Scene
) -> None:
    """+Rsr: comment.edit_own (c2) for their own comments; a member's stays 403."""
    guest = await api(scene.guest)
    mine = ok(await guest.post(f"/ideas/{scene.key}/comments", {"body_md": "Asked Legal."}), 201)
    comment = mine["comment"]["id"]

    edited = ok(await guest.patch(f"/comments/{comment}", {"body_md": "Asked Legal, Tue."}))
    deleted = await guest.delete(f"/comments/{comment}")

    assert edited["comment"]["body_md"] == "Asked Legal, Tue."
    assert deleted.status_code == 204
    assert (await guest.patch(f"/comments/{scene.comment_id}", {"body_md": "x"})).status_code == 403


# --- The guest shape and no score data on any path ----------------------------------------
async def test_the_guest_shape(api: AsUser, team: Team, scene: Scene) -> None:
    guest = ok(await (await api(scene.guest)).get(f"/ideas/{scene.key}"))
    member = ok(await (await api(team.member)).get(f"/ideas/{scene.key}"))

    assert member["score"] is not None
    assert member["evaluators"]
    assert member["evaluator_progress"]["total"] == 3
    expected: dict[str, object] = {
        "score": None,
        "aggregate": None,
        "score_hidden": True,
        "high_disagreement": False,
        "evaluators": [],
        "evaluator_progress": {"submitted": 0, "total": 0},
        "evaluation_due_at": None,
        "evaluation_closed_at": None,
        "evaluation_open": False,
        "held_for": None,
    }
    for field, value in expected.items():
        assert guest[field] == value, field
    assert guest["title"] == "Self-service refunds portal"
    assert guest["project"]["name"] == "Customer Innovation"
    assert guest["owner"]["id"] == str(team.owner.id)
    assert guest["researcher"]["id"] == str(scene.guest.id)
    assert guest["research_due_at"] is not None
    permissions = guest["permissions"]
    granted = {name for name, value in permissions.items() if value is True}
    assert granted == {"can_comment", "can_answer_research", "can_hand_back_research"}
    assert permissions["can_view_project"] is False
    research = ok(await (await api(scene.guest)).get(f"/ideas/{scene.key}/research"))
    assert research["permissions"] == {
        "can_answer": True,
        "can_override": False,
        "can_assign": False,
        "can_assign_outside_researcher": False,
        "can_hand_back": True,
    }
    assert research["gate_status_label"] == "Proposal"
    assert research["assignment"]["researcher_in_project"] is False


async def test_the_feed_leaves_out_the_evaluation_events(
    api: AsUser, team: Team, scene: Scene
) -> None:
    guest = ok(await (await api(scene.guest)).get(f"/ideas/{scene.key}/activity"))["items"]
    owner = ok(await (await api(team.owner)).get(f"/ideas/{scene.key}/activity"))["items"]

    guest_types = {item["type"] for item in guest}
    owner_types = {item["type"] for item in owner}
    assert {"evaluator_added", "evaluation_submitted", "due_date_changed"} <= owner_types
    assert guest_types <= RESEARCH_GUEST_ACTIVITY_TYPES
    assert not guest_types & EVALUATION_ACTIVITY_TYPES
    assert {"comment", "researcher_changed", "ai_research_note"} <= guest_types


async def test_the_feed_pages_over_the_filtered_events(
    api: AsUser, team: Team, scene: Scene
) -> None:
    guest = await api(scene.guest)
    seen: list[str] = []
    cursor = None
    for _ in range(10):
        params = {"limit": 1} | ({"cursor": cursor} if cursor else {})
        page = ok(await guest.get(f"/ideas/{scene.key}/activity", **params))
        seen += [item["type"] for item in page["items"]]
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert seen
    assert not set(seen) & EVALUATION_ACTIVITY_TYPES


async def test_search_finds_the_idea_never_its_project(
    api: AsUser, team: Team, scene: Scene, db_session: AsyncSession
) -> None:
    other = await make_idea(db_session, team.project, title="Refunds without receipts")

    found = ok(await (await api(scene.guest)).get("/search", q="refunds"))

    keys = [idea["key"] for idea in found["ideas"]]
    assert keys == [scene.key]
    assert key_of(team.project, other) not in keys
    assert found["projects"] == []
    assert "score" not in found["ideas"][0]


async def test_my_work_lists_it_as_research_to_do_only(
    api: AsUser, team: Team, scene: Scene
) -> None:
    work = ok(await (await api(scene.guest)).get("/me/work"))

    (item,) = work["research_to_do"]
    assert item["idea"]["key"] == scene.key
    assert item["can_view_project"] is False
    assert item["as_owner"] is False
    assert item["progress"]["required_open"] == 2
    assert work["owned"] == []
    assert work["evaluations_due"] == []
    assert work["counts"]["research_to_do"] == 1
    counts = ok(await (await api(scene.guest)).get("/me/work/counts"))
    assert (counts["research_to_do"], counts["research_overdue"]) == (1, 0)


async def test_similar_ideas_only_from_ideas_the_guest_could_see(
    api: AsUser, team: Team, scene: Scene, db_session: AsyncSession
) -> None:
    hidden = await make_idea(db_session, team.project, title="Self-service refunds portal v2")
    theirs = await make_project(db_session, key="OWN", members={scene.guest: ProjectRole.MEMBER})
    shared = await make_idea(db_session, theirs, title="Self-service refunds portal for shops")

    similar = ok(await (await api(scene.guest)).get(f"/ideas/{scene.key}/similar-ideas"))
    owner_view = ok(await (await api(team.owner)).get(f"/ideas/{scene.key}/similar-ideas"))

    keys = [item["key"] for item in similar["items"]]
    assert key_of(theirs, shared) in keys
    assert key_of(team.project, hidden) not in keys
    assert key_of(team.project, hidden) in [item["key"] for item in owner_view["items"]]


async def test_the_inbox_holds_only_the_guest_types(
    api: AsUser, team: Team, scene: Scene, db_session: AsyncSession
) -> None:
    """Review S5: an older evaluator item about the idea stays hidden from its guest."""
    db_session.add(
        Notification(
            id=uuid4(),
            user_id=scene.guest.id,
            type=NotificationType.EVALUATOR_INVITED,
            idea_id=scene.idea.id,
            payload={},
            dedupe_key=f"old:{uuid4()}",
            email_mode=NotificationMode.OFF,
        )
    )
    await db_session.commit()
    guest = await api(scene.guest)

    items = ok(await guest.get("/me/notifications"))["items"]
    summary = ok(await guest.get("/me/notifications/summary"))

    assert [item["type"] for item in items] == ["researcher_assigned"]
    assert items[0]["idea"]["key"] == scene.key
    assert summary["unread_count"] == 1


# --- MCP ----------------------------------------------------------------------------------
async def test_mcp_as_the_guest(as_agent: AsAgent, team: Team, scene: Scene) -> None:
    agent = await as_agent(scene.guest, WRITE)

    got = (await agent.ok("get_idea", idea=scene.key))["idea"]
    found = await agent.ok("search_ideas", query="refunds")

    assert got["research_guest"] is True
    assert got["score"] is None
    assert got["score_hidden"] is True
    assert got["has_proposal"] is False
    assert got["evaluations"] == []
    assert got["my_evaluation"] is None
    assert got["evaluator_progress"] == {"submitted": 0, "total": 0}
    assert got["research"]["researcher"]["id"] == str(scene.guest.id)
    assert got["research"]["due_at"] is not None
    assert got["permissions"]["can_comment"] is True
    assert got["permissions"]["can_evaluate"] is False
    (summary,) = found["items"]
    assert summary["key"] == scene.key
    assert summary["score"] is None
    assert summary["score_hidden"] is True
    assert summary["evaluator_progress"] == {"submitted": 0, "total": 0}
    assert (await agent.ok("list_projects"))["projects"] == []
    for tool, arguments in (
        ("get_rubric", {"idea": scene.key}),
        ("get_rubric", {"project": team.slug}),
        ("get_proposal", {"idea": scene.key}),
        (
            "propose_proposal_section",
            {"idea": scene.key, "section_key": "summary", "body_md": "x", "base_version": 1},
        ),
        ("create_idea", {"project": team.slug, "title": "T", "summary": "S"}),
        ("submit_evaluation", {"idea": scene.key, "scores": [], "submit": False}),
    ):
        assert await agent.fails(tool, **arguments) == "not_found", tool
    comment = await agent.ok("add_comment", idea=scene.key, body_md="Asked Legal today.")
    assert comment["comment"]["body_md"] == "Asked Legal today."


async def test_a_member_sees_the_researcher_in_mcp(
    as_agent: AsAgent, team: Team, scene: Scene
) -> None:
    got = (await (await as_agent(team.member, READ)).ok("get_idea", idea=scene.key))["idea"]

    assert got["research_guest"] is False
    assert got["has_proposal"] is True
    assert got["research"]["researcher"]["display_name"] == scene.guest.display_name


# --- Access ends at once -------------------------------------------------------------------
async def _end(how: str, api: AsUser, team: Team, scene: Scene, db: AsyncSession) -> None:
    admin = await api(team.admin)
    if how == "hand_back":
        response = await (await api(scene.guest)).delete(f"/ideas/{scene.key}/research/assignment")
        assert response.status_code == 204
    elif how == "removed":
        assert (await admin.delete(f"/ideas/{scene.key}/research/assignment")).status_code == 204
    elif how == "reassigned":
        ok(await assign(admin, scene.key, team.member))
    elif how == "closed":
        ok(
            await admin.post(
                f"/ideas/{scene.key}/status", {"status": "closed", "resolution": "parked"}
            )
        )
    elif how == "step_off":
        ok(await admin.put(f"/projects/{team.slug}/research", {"step": "off", "items": []}))
    elif how == "archived":
        await db.execute(
            update(Project).where(Project.id == team.project.id).values(archived_at=utcnow())
        )
        await db.commit()
    elif how == "deleted":
        await db.execute(delete(Idea).where(Idea.id == scene.idea.id))
        await db.commit()
    else:  # pragma: no cover
        raise AssertionError(how)


@pytest.mark.parametrize(
    "how", ["hand_back", "removed", "reassigned", "closed", "step_off", "archived", "deleted"]
)
async def test_access_ends_at_once(
    api: AsUser,
    as_agent: AsAgent,
    team: Team,
    scene: Scene,
    db_session: AsyncSession,
    how: str,
) -> None:
    guest = await api(scene.guest)
    agent = await as_agent(scene.guest, WRITE)
    ok(await guest.get(f"/ideas/{scene.key}"))
    assert ok(await guest.get("/me/notifications"))["items"]

    await _end(how, api, team, scene, db_session)

    assert_problem(await guest.get(f"/ideas/{scene.key}"), 404, "not_found")
    assert_problem(await guest.get(f"/ideas/{scene.key}/research"), 404, "not_found")
    assert_problem(await guest.get(f"/ideas/{scene.key}/activity"), 404, "not_found")
    assert await agent.fails("get_idea", idea=scene.key) == "not_found"
    assert (await agent.ok("search_ideas", query="refunds"))["items"] == []
    assert ok(await guest.get("/me/notifications"))["items"] == []
    assert ok(await guest.get("/search", q="refunds"))["ideas"] == []
    work = ok(await guest.get("/me/work"))
    assert work["research_to_do"] == []
    assert work["counts"]["research_to_do"] == 0


async def test_deactivation_ends_it_and_the_key(
    api: AsUser, as_agent: AsAgent, team: Team, scene: Scene
) -> None:
    agent = await as_agent(scene.guest, READ)
    ok(
        await (await api(team.platform)).patch(
            f"/admin/users/{scene.guest.id}", {"is_active": False}
        )
    )

    with pytest.raises(BaseException):  # noqa: B017, PT011 - the key is revoked: 401
        await agent.call("get_idea", idea=scene.key)


# --- API keys -----------------------------------------------------------------------------
async def test_an_unrestricted_key_reads_as_the_guest(
    app: FastAPI, team: Team, scene: Scene, db_session: AsyncSession
) -> None:
    from tests.api_keys.helpers import key_client
    from tests.api_keys.helpers import make_key as issue

    read = await issue(db_session, scene.guest, scopes=("read",))
    write = await issue(db_session, scene.guest, scopes=("write",))
    async with key_client(app, read) as http:
        got = await http.get(f"{API}/ideas/{scene.key}")
        refused = await http.put(
            f"{API}/ideas/{scene.key}/research/items/{scene.items[0].id}", json={"answer": "x"}
        )
        hidden = await http.get(f"{API}/ideas/{scene.key}/evaluations")
    async with key_client(app, write) as http:
        answered = await http.put(
            f"{API}/ideas/{scene.key}/research/items/{scene.items[0].id}",
            json={"answer": "Legal, 3 Oct: fine."},
        )

    assert got.status_code == 200
    assert got.json()["score"] is None
    assert got.json()["permissions"]["can_view_project"] is False
    assert refused.status_code == 403
    assert hidden.status_code == 404
    assert answered.status_code == 200, answered.text


async def test_a_restricted_key_reaches_the_idea_only_as_r_does(
    app: FastAPI, api: AsUser, team: Team, scene: Scene, db_session: AsyncSession
) -> None:
    """Review C2: a key restricted to another project never reaches it; one restricted to
    this project, made while its owner was a member, reaches it only as R."""
    from tests.api_keys.helpers import key_client
    from tests.api_keys.helpers import make_key as issue

    other = await make_project(db_session, key="OTH", members={scene.guest: ProjectRole.MEMBER})
    elsewhere = await issue(db_session, scene.guest, scopes=("read",), project_ids=[other.id])
    async with key_client(app, elsewhere) as http:
        assert (await http.get(f"{API}/ideas/{scene.key}")).status_code == 404

    former = await make_user(db_session, "Fran Former")
    await add_member(db_session, team.project, former, ProjectRole.MEMBER)
    restricted = await issue(db_session, former, scopes=("read",), project_ids=[team.project.id])
    from app.models.project import ProjectMember

    await db_session.execute(
        delete(ProjectMember).where(
            ProjectMember.project_id == team.project.id, ProjectMember.user_id == former.id
        )
    )
    await db_session.commit()
    async with key_client(app, restricted) as http:
        assert (await http.get(f"{API}/ideas/{scene.key}")).status_code == 404
    ok(await assign(await api(team.admin), scene.key, former))
    async with key_client(app, restricted) as http:
        got = await http.get(f"{API}/ideas/{scene.key}")
        hidden = await http.get(f"{API}/ideas/{scene.key}/proposal")

    assert got.status_code == 200
    assert got.json()["score"] is None
    assert got.json()["evaluators"] == []
    assert hidden.status_code == 404


async def test_an_agent_is_never_a_guest(
    api: AsUser, team: Team, scene: Scene, db_session: AsyncSession
) -> None:
    """c23: an agent can't be named; even a stored row grants a service account nothing."""
    assert_problem(
        await assign(await api(team.admin), scene.key, scene.agent), 422, "researcher_not_eligible"
    )
    await db_session.execute(
        update(Idea).where(Idea.id == scene.idea.id).values(researcher_id=scene.agent.id)
    )
    await db_session.commit()
    from app.authz import researched_ideas
    from app.domain.principal import Principal

    agent = await db_session.get(User, scene.agent.id)
    assert agent is not None
    found = await db_session.scalars(select(Idea.id).where(researched_ideas(Principal(user=agent))))
    assert list(found) == []
