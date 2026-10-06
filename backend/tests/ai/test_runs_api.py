"""AI runs over REST (contract-phase6 sections 2, 3.3 and 3.5): who may ask (role matrix
table J, every column and the owner overlay), c10 part by part, c5/c6/c7, holds and
archive, keys, idempotency under concurrency, the per-person limit, the queue timeout,
cancel, the run list with its permission reasons, and the evaluator assignment."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import ActivityEvent, AuditLog
from app.models.ai import AiAgent, AiRun
from app.models.api_key import ApiKey
from app.models.base import utcnow
from app.models.enums import (
    AiRunKind,
    AiRunStatus,
    HoldReason,
    IdeaStatus,
    ProjectRole,
    ProjectVisibility,
    Resolution,
)
from app.models.idea import Idea, IdeaEvaluator
from app.models.project import Project, ProjectMember
from app.models.user import User
from tests.ai.conftest import AsUser, Crew, assert_problem, ok
from tests.ai.helpers import ago, make_agent, open_run, run_row
from tests.api_keys.helpers import key_client, make_key
from tests.factories import make_idea, make_project, make_user

PATHS = {
    AiRunKind.EVALUATE: "evaluation",
    AiRunKind.RESEARCH: "research",
    AiRunKind.DRAFT_SECTION: "section-draft",
}


def _url(crew: Crew, kind: AiRunKind, ref: str | None = None) -> str:
    return f"/ideas/{ref or crew.ref}/ai-runs/{PATHS[kind]}"


def _body(crew: Crew, kind: AiRunKind, agent_id: Any = None) -> dict[str, Any]:
    body: dict[str, Any] = {"agent_id": str(agent_id or crew.agent.id)}
    if kind is AiRunKind.DRAFT_SECTION:
        body["section_key"] = "risks"
    return body


async def _ready(crew: Crew, db: AsyncSession, api: AsUser, kind: AiRunKind) -> None:
    """Make the idea fit the kind: drafts need Shortlisted and a proposal (c7)."""
    if kind is AiRunKind.DRAFT_SECTION:
        await db.execute(
            update(Idea).where(Idea.id == crew.idea.id).values(status=IdeaStatus.SHORTLISTED)
        )
        await db.commit()
        ok(await (await api(crew.team.owner)).post(f"/ideas/{crew.ref}/proposal"), 201)


# --- Who may ask (table J) ----------------------------------------------------------------
COLUMNS = {
    "platform": 201,
    "admin": 201,
    "owner": 201,
    "member": 403,
    "viewer": 403,
    "outsider": 404,
}


@pytest.mark.parametrize("kind", list(AiRunKind))
@pytest.mark.parametrize(("who", "status"), list(COLUMNS.items()))
async def test_who_may_ask(
    api: AsUser, crew: Crew, db_session: AsyncSession, kind: AiRunKind, who: str, status: int
) -> None:
    await _ready(crew, db_session, api, kind)
    user: User = getattr(crew.team, who)

    response = await (await api(user)).post(_url(crew, kind), _body(crew, kind))

    assert response.status_code == status, response.text
    if status == 201:
        assert response.json()["status"] == "queued"
        assert response.json()["requested_by"]["id"] == str(user.id)


@pytest.mark.parametrize("kind", list(AiRunKind))
async def test_anonymous_is_401_and_an_internal_non_member_403(
    client: Any, api: AsUser, db_session: AsyncSession, crew: Crew, kind: AiRunKind
) -> None:
    internal = await make_project(
        db_session,
        slug="tools",
        key="TOOLS",
        visibility=ProjectVisibility.INTERNAL,
        members={crew.team.admin: ProjectRole.ADMIN},
    )
    idea = await make_idea(db_session, internal, status=IdeaStatus.SHORTLISTED)
    agent = await make_agent(db_session, [internal], key=True, name="tools-agent")
    if kind is AiRunKind.DRAFT_SECTION:
        ok(await (await api(crew.team.admin)).post(f"/ideas/TOOLS-{idea.number}/proposal"), 201)
    url = _url(crew, kind, f"TOOLS-{idea.number}")

    anonymous = await client.post(f"/api/v1{url}", json=_body(crew, kind, agent.id))
    stranger = await (await api(crew.team.outsider)).post(url, _body(crew, kind, agent.id))

    assert_problem(anonymous, 401, "unauthorized")
    assert_problem(stranger, 403, "forbidden")


async def test_a_demoted_owner_may_not_ask(
    api: AsUser, crew: Crew, db_session: AsyncSession
) -> None:
    await db_session.execute(
        update(ProjectMember)
        .where(ProjectMember.user_id == crew.team.owner.id)
        .values(role=ProjectRole.VIEWER)
    )
    await db_session.commit()

    response = await (await api(crew.team.owner)).post(
        _url(crew, AiRunKind.EVALUATE), _body(crew, AiRunKind.EVALUATE)
    )

    assert_problem(response, 403, "forbidden")


# --- c5, c6, c7, holds, archive -----------------------------------------------------------
async def test_state_conditions(api: AsUser, crew: Crew, db_session: AsyncSession) -> None:
    owner = await api(crew.team.owner)
    await db_session.execute(
        update(Idea).where(Idea.id == crew.idea.id).values(evaluation_closed_at=utcnow())
    )
    await db_session.commit()
    closed_eval = await owner.post(_url(crew, AiRunKind.EVALUATE), _body(crew, AiRunKind.EVALUATE))
    early_draft = await owner.post(
        _url(crew, AiRunKind.DRAFT_SECTION), _body(crew, AiRunKind.DRAFT_SECTION)
    )
    await db_session.execute(
        update(Idea)
        .where(Idea.id == crew.idea.id)
        .values(status=IdeaStatus.CLOSED, resolution=Resolution.PARKED)
    )
    await db_session.commit()
    closed = await owner.post(_url(crew, AiRunKind.RESEARCH), _body(crew, AiRunKind.RESEARCH))

    assert_problem(closed_eval, 409, "evaluation_closed")
    assert_problem(early_draft, 404, "not_found")  # no proposal yet: 404 first
    assert_problem(closed, 409, "idea_closed")


async def test_a_draft_needs_shortlisted_or_proposal(
    api: AsUser, crew: Crew, db_session: AsyncSession
) -> None:
    await _ready(crew, db_session, api, AiRunKind.DRAFT_SECTION)
    await db_session.execute(
        update(Idea).where(Idea.id == crew.idea.id).values(status=IdeaStatus.EVALUATING)
    )
    await db_session.commit()

    response = await (await api(crew.team.owner)).post(
        _url(crew, AiRunKind.DRAFT_SECTION), _body(crew, AiRunKind.DRAFT_SECTION)
    )

    assert_problem(response, 409, "proposal_not_available")


async def test_holds_and_archive(api: AsUser, crew: Crew, db_session: AsyncSession) -> None:
    admin = await api(crew.team.admin)
    body = _body(crew, AiRunKind.RESEARCH)
    await db_session.execute(
        update(Idea).where(Idea.id == crew.idea.id).values(held_for=HoldReason.MODERATION)
    )
    await db_session.commit()
    moderation = await admin.post(_url(crew, AiRunKind.RESEARCH), body)
    await db_session.execute(
        update(Idea).where(Idea.id == crew.idea.id).values(held_for=HoldReason.EMAIL_VERIFICATION)
    )
    await db_session.commit()
    verification = await admin.post(_url(crew, AiRunKind.RESEARCH), body)
    await db_session.execute(update(Idea).where(Idea.id == crew.idea.id).values(held_for=None))
    await db_session.execute(
        update(Project).where(Project.id == crew.team.project.id).values(archived_at=utcnow())
    )
    await db_session.commit()
    archived = await admin.post(_url(crew, AiRunKind.RESEARCH), body)

    assert_problem(moderation, 409, "awaiting_moderation")
    assert_problem(verification, 404, "not_found")
    assert_problem(archived, 409, "project_archived")


# --- c10, part by part --------------------------------------------------------------------
async def _c10_broken(how: str, crew: Crew, db: AsyncSession) -> Any:
    agent_id = crew.agent.id
    match how:
        case "disabled":
            await db.execute(update(AiAgent).where(AiAgent.id == agent_id).values(enabled=False))
        case "wrong_purpose":
            await db.execute(
                update(AiAgent).where(AiAgent.id == agent_id).values(purposes=["research"])
            )
        case "not_served":
            other = await make_project(db, slug="other", key="OTH")
            other_agent = await make_agent(db, [other], key=True, name="elsewhere")
            agent_id = other_agent.id
        case "viewer":
            await db.execute(
                update(ProjectMember)
                .where(ProjectMember.user_id == crew.agent.user.id)
                .values(role=ProjectRole.VIEWER)
            )
        case "removed":
            await db.execute(
                delete(ProjectMember).where(ProjectMember.user_id == crew.agent.user.id)
            )
        case "inactive":
            await db.execute(
                update(User).where(User.id == crew.agent.user.id).values(is_active=False)
            )
        case "revoked":
            await db.execute(
                update(ApiKey)
                .where(ApiKey.user_id == crew.agent.user.id)
                .values(revoked_at=utcnow())
            )
        case "expired":
            await db.execute(
                update(ApiKey)
                .where(ApiKey.user_id == crew.agent.user.id)
                .values(expires_at=ago(seconds=1))
            )
        case "unknown":
            from uuid import uuid4

            agent_id = uuid4()
    await db.commit()
    return agent_id


C10 = [
    "disabled",
    "wrong_purpose",
    "not_served",
    "viewer",
    "removed",
    "inactive",
    "revoked",
    "expired",
    "unknown",
]


@pytest.mark.parametrize("how", C10)
async def test_c10_each_part(api: AsUser, crew: Crew, db_session: AsyncSession, how: str) -> None:
    agent_id = await _c10_broken(how, crew, db_session)

    response = await (await api(crew.team.owner)).post(
        _url(crew, AiRunKind.EVALUATE), _body(crew, AiRunKind.EVALUATE, agent_id)
    )
    listed = ok(await (await api(crew.team.owner)).get(f"/ideas/{crew.ref}/ai-runs"))

    assert_problem(response, 409, "ai_unavailable")
    if how not in ("not_served", "unknown"):  # those break another agent id, not the crew's
        assert listed["permissions"]["can_request_evaluation"] is False
        assert listed["permissions"]["request_evaluation_blocked_by"] == "no_agent"
        if how != "wrong_purpose":
            assert listed["agents"] == []


@pytest.mark.settings(ai_enabled=False)
async def test_c10_ai_off(api: AsUser, crew: Crew) -> None:
    owner = await api(crew.team.owner)

    response = await owner.post(_url(crew, AiRunKind.EVALUATE), _body(crew, AiRunKind.EVALUATE))
    listed = ok(await owner.get(f"/ideas/{crew.ref}/ai-runs"))

    assert_problem(response, 409, "ai_unavailable")
    assert listed["ai_enabled"] is False
    assert listed["agents"] == []
    assert listed["permissions"]["request_evaluation_blocked_by"] == "ai_off"
    # A member still hears 403 first (the rule before c10).
    member = await api(crew.team.member)
    refused = await member.post(_url(crew, AiRunKind.EVALUATE), _body(crew, AiRunKind.EVALUATE))
    assert_problem(refused, 403, "forbidden")


# --- Keys ---------------------------------------------------------------------------------
async def test_a_persons_key_needs_write(
    app: FastAPI, crew: Crew, db_session: AsyncSession
) -> None:
    read_only = await make_key(db_session, crew.team.owner, scopes=["read"])
    writer = await make_key(db_session, crew.team.owner, scopes=["write"])
    url, body = f"/api/v1{_url(crew, AiRunKind.RESEARCH)}", _body(crew, AiRunKind.RESEARCH)

    async with key_client(app, read_only) as http:
        refused = await http.post(url, json=body)
        listed = await http.get(f"/api/v1/ideas/{crew.ref}/ai-runs")
    async with key_client(app, writer) as http:
        created = await http.post(url, json=body)

    assert_problem(refused, 403, "insufficient_scope")
    assert listed.status_code == 200
    assert created.status_code == 201, created.text


async def test_an_agents_key_is_refused_on_every_rest_route(
    app: FastAPI, crew: Crew, db_session: AsyncSession
) -> None:
    run = await open_run(db_session, crew.agent, crew.idea, AiRunKind.EVALUATE)
    assert crew.agent.key is not None
    async with key_client(app, crew.agent.key) as http:
        responses = [
            await http.post(
                f"/api/v1{_url(crew, AiRunKind.EVALUATE)}", json=_body(crew, AiRunKind.EVALUATE)
            ),
            await http.get(f"/api/v1/ideas/{crew.ref}/ai-runs"),
            await http.get(f"/api/v1/ideas/{crew.ref}/ai-runs/{run.id}"),
            await http.get(f"/api/v1/ideas/{crew.ref}/ai-runs/{run.id}/events"),
            await http.get(f"/api/v1/ideas/{crew.ref}"),
            await http.put(
                f"/api/v1/ideas/{crew.ref}/evaluations/me", json={"scores": [], "submit": False}
            ),
        ]

    for response in responses:
        assert_problem(response, 403, "insufficient_scope")


# --- Idempotency, the limit, the queue timeout --------------------------------------------
async def test_a_repeated_request_returns_the_active_run(
    api: AsUser, crew: Crew, db_session: AsyncSession
) -> None:
    owner = await api(crew.team.owner)
    url, body = _url(crew, AiRunKind.EVALUATE), _body(crew, AiRunKind.EVALUATE)

    first = await owner.post(url, body)
    again = await owner.post(url, body)

    assert first.status_code == 201
    assert again.status_code == 200
    assert again.json()["id"] == first.json()["id"]
    audits = list(
        await db_session.scalars(select(AuditLog).where(AuditLog.action == "ai_run.request"))
    )
    assert len(audits) == 1
    assert audits[0].details["rule"] == "ai.request_evaluation"
    assert audits[0].details["kind"] == "evaluate"


async def test_concurrent_requests_make_one_run(
    api: AsUser, crew: Crew, db_session: AsyncSession
) -> None:
    owner, admin = await api(crew.team.owner), await api(crew.team.admin)
    url, body = _url(crew, AiRunKind.RESEARCH), _body(crew, AiRunKind.RESEARCH)

    responses = await asyncio.gather(*(who.post(url, body) for who in (owner, admin, owner, admin)))

    assert sorted(r.status_code for r in responses) == [200, 200, 200, 201]
    assert len({r.json()["id"] for r in responses}) == 1
    runs = list(await db_session.scalars(select(AiRun)))
    assert len(runs) == 1


async def test_a_finished_run_doesnt_block_a_new_one_and_sections_run_side_by_side(
    api: AsUser, crew: Crew, db_session: AsyncSession
) -> None:
    await _ready(crew, db_session, api, AiRunKind.DRAFT_SECTION)
    owner = await api(crew.team.owner)
    url = _url(crew, AiRunKind.DRAFT_SECTION)
    agent = str(crew.agent.id)

    risks = ok(await owner.post(url, {"agent_id": agent, "section_key": "risks"}), 201)
    market = ok(await owner.post(url, {"agent_id": agent, "section_key": "market"}), 201)
    ok(await owner.post(f"/ideas/{crew.ref}/ai-runs/{risks['id']}/cancel"))
    again = ok(await owner.post(url, {"agent_id": agent, "section_key": "risks"}), 201)

    assert len({risks["id"], market["id"], again["id"]}) == 3
    assert (risks["section_key"], market["section_key"]) == ("risks", "market")


async def test_twenty_requests_an_hour_per_person(
    api: AsUser, crew: Crew, db_session: AsyncSession
) -> None:
    for _ in range(19):
        await open_run(
            db_session,
            crew.agent,
            crew.idea,
            AiRunKind.RESEARCH,
            status=AiRunStatus.CANCELLED,
            requested_by=crew.team.owner,
        )
    await open_run(
        db_session,
        crew.agent,
        crew.idea,
        AiRunKind.EVALUATE,
        status=AiRunStatus.QUEUED,
        requested_by=crew.team.owner,
    )
    owner = await api(crew.team.owner)

    same = await owner.post(_url(crew, AiRunKind.EVALUATE), _body(crew, AiRunKind.EVALUATE))
    refused = await owner.post(_url(crew, AiRunKind.RESEARCH), _body(crew, AiRunKind.RESEARCH))
    other_person = await (await api(crew.team.admin)).post(
        _url(crew, AiRunKind.RESEARCH), _body(crew, AiRunKind.RESEARCH)
    )

    assert same.status_code == 200  # the active run: not counted, not refused
    assert_problem(refused, 429, "too_many_attempts")
    assert 1 <= int(refused.headers["retry-after"]) <= 3600
    assert other_person.status_code == 201


async def test_a_run_queued_past_the_queue_timeout_is_replaced(
    api: AsUser, crew: Crew, db_session: AsyncSession
) -> None:
    stale = await open_run(
        db_session,
        crew.agent,
        crew.idea,
        AiRunKind.RESEARCH,
        status=AiRunStatus.QUEUED,
        created_at=ago(minutes=31),
    )

    response = await (await api(crew.team.owner)).post(
        _url(crew, AiRunKind.RESEARCH), _body(crew, AiRunKind.RESEARCH)
    )

    assert response.status_code == 201
    assert response.json()["id"] != str(stale.id)
    old = await run_row(db_session, stale.id)
    assert (old.status, old.error_code) == (AiRunStatus.TIMED_OUT, "queue_timeout")
    assert old.error_message == "The run waited too long to start."


# --- Evaluate assigns the agent -----------------------------------------------------------
async def test_asking_to_evaluate_assigns_the_agent_once(
    api: AsUser, crew: Crew, db_session: AsyncSession
) -> None:
    owner = await api(crew.team.owner)

    created = ok(
        await owner.post(_url(crew, AiRunKind.EVALUATE), _body(crew, AiRunKind.EVALUATE)), 201
    )
    detail = ok(await owner.get(f"/ideas/{crew.ref}"))

    assignment = await db_session.get(IdeaEvaluator, (crew.idea.id, crew.agent.user.id))
    assert assignment is not None
    assert assignment.invited_by_id == crew.team.owner.id
    assert (await run_row(db_session, created["id"])).assigned_evaluator is True
    [row] = [e for e in detail["evaluators"] if e["user"]["id"] == str(crew.agent.user.id)]
    assert (row["is_ai"], row["state"]) == (True, "invited")
    events = list(
        await db_session.scalars(
            select(ActivityEvent).where(
                ActivityEvent.idea_id == crew.idea.id, ActivityEvent.type == "evaluator_added"
            )
        )
    )
    assert [(e.actor_id, e.payload["evaluator_id"]) for e in events] == [
        (crew.team.owner.id, str(crew.agent.user.id))
    ]
    [audit] = await db_session.scalars(select(AuditLog).where(AuditLog.action == "evaluator.add"))
    assert audit.details["rule"] == "ai.request_evaluation"
    # A run that ends without its evaluation takes the assignment back (no actor).
    ok(await owner.post(f"/ideas/{crew.ref}/ai-runs/{created['id']}/cancel"))
    gone = await db_session.get(
        IdeaEvaluator, (crew.idea.id, crew.agent.user.id), populate_existing=True
    )
    assert gone is None
    removed = list(
        await db_session.scalars(
            select(ActivityEvent).where(
                ActivityEvent.idea_id == crew.idea.id, ActivityEvent.type == "evaluator_removed"
            )
        )
    )
    assert [(e.actor_id, e.payload["evaluator_id"]) for e in removed] == [
        (None, str(crew.agent.user.id))
    ]
    [removal] = await db_session.scalars(
        select(AuditLog).where(AuditLog.action == "evaluator.remove")
    )
    assert removal.actor_id is None
    assert removal.details["reason"] == "ai_run_ended"
    assert removal.details["run_id"] == created["id"]
    # An assignment that existed before the run is never this run's to undo.
    db_session.expunge_all()
    db_session.add(
        IdeaEvaluator(
            idea_id=crew.idea.id, user_id=crew.agent.user.id, invited_by_id=crew.team.admin.id
        )
    )
    await db_session.commit()
    again = ok(
        await owner.post(_url(crew, AiRunKind.EVALUATE), _body(crew, AiRunKind.EVALUATE)), 201
    )
    assert (await run_row(db_session, again["id"])).assigned_evaluator is False
    ok(await owner.post(f"/ideas/{crew.ref}/ai-runs/{again['id']}/cancel"))
    kept = await db_session.get(
        IdeaEvaluator, (crew.idea.id, crew.agent.user.id), populate_existing=True
    )
    assert kept is not None


# --- Cancel -------------------------------------------------------------------------------
async def test_cancel_queued_running_and_finished(
    api: AsUser, crew: Crew, db_session: AsyncSession
) -> None:
    owner = await api(crew.team.owner)
    queued = ok(
        await owner.post(_url(crew, AiRunKind.RESEARCH), _body(crew, AiRunKind.RESEARCH)), 201
    )
    running = await open_run(db_session, crew.agent, crew.idea, AiRunKind.EVALUATE)

    cancelled = ok(await owner.post(f"/ideas/{crew.ref}/ai-runs/{queued['id']}/cancel"))
    requested = ok(await owner.post(f"/ideas/{crew.ref}/ai-runs/{running.id}/cancel"))
    again = ok(await owner.post(f"/ideas/{crew.ref}/ai-runs/{running.id}/cancel"))
    finished = await owner.post(f"/ideas/{crew.ref}/ai-runs/{queued['id']}/cancel")
    detail = ok(await owner.get(f"/ideas/{crew.ref}/ai-runs/{queued['id']}"))

    assert (cancelled["status"], cancelled["can_cancel"]) == ("cancelled", False)
    assert cancelled["cancel_requested"] is False  # ended at once: nothing left to cancel
    assert (requested["status"], requested["cancel_requested"]) == ("running", True)
    assert again["cancel_requested"] is True
    assert_problem(finished, 409, "ai_run_finished")
    assert [e["type"] for e in detail["events"]] == ["queued", "cancelled"]
    assert detail["events"][-1]["final"] is True
    run = await run_row(db_session, running.id)
    assert run.cancel_requested_by_id == crew.team.owner.id
    audits = list(
        await db_session.scalars(select(AuditLog).where(AuditLog.action == "ai_run.cancel"))
    )
    assert len(audits) == 2  # the idempotent repeat isn't audited again


async def test_cancel_rules(api: AsUser, crew: Crew, db_session: AsyncSession) -> None:
    run = await open_run(db_session, crew.agent, crew.idea, AiRunKind.RESEARCH)
    path = f"/ideas/{crew.ref}/ai-runs/{run.id}/cancel"

    assert_problem(await (await api(crew.team.member)).post(path), 403, "forbidden")
    assert_problem(await (await api(crew.team.outsider)).post(path), 404, "not_found")
    other = await make_idea(db_session, crew.team.project)
    assert_problem(
        await (await api(crew.team.owner)).post(
            f"/ideas/CUST-{other.number}/ai-runs/{run.id}/cancel"
        ),
        404,
        "not_found",
    )
    # Archived projects: cancelling only stops work, so it is allowed.
    await db_session.execute(
        update(Project).where(Project.id == crew.team.project.id).values(archived_at=utcnow())
    )
    await db_session.commit()
    ok(await (await api(crew.team.admin)).post(path))


# --- The list and its permissions ---------------------------------------------------------
async def test_the_list_says_why_each_action_is_unavailable(
    api: AsUser, crew: Crew, db_session: AsyncSession
) -> None:
    member = ok(await (await api(crew.team.member)).get(f"/ideas/{crew.ref}/ai-runs"))
    owner = ok(await (await api(crew.team.owner)).get(f"/ideas/{crew.ref}/ai-runs"))

    assert member["permissions"] == {
        "can_request_evaluation": False,
        "request_evaluation_blocked_by": "not_allowed",
        "can_research": False,
        "research_blocked_by": "not_allowed",
        "can_draft_section": False,
        "draft_section_blocked_by": "not_allowed",
        "can_cancel": False,
        "can_include_ai": False,
        "include_ai_blocked_by": "not_allowed",
    }
    assert owner["permissions"] == {
        "can_request_evaluation": True,
        "request_evaluation_blocked_by": None,
        "can_research": True,
        "research_blocked_by": None,
        "can_draft_section": False,
        "draft_section_blocked_by": "proposal_not_available",
        "can_cancel": True,
        "can_include_ai": True,
        "include_ai_blocked_by": None,
    }
    assert [a["id"] for a in owner["agents"]] == [str(crew.agent.id)]
    assert owner["agents"][0]["user_id"] == str(crew.agent.user.id)
    assert member["agents"] == owner["agents"]  # watching needs only idea.view

    await db_session.execute(
        update(Idea).where(Idea.id == crew.idea.id).values(status=IdeaStatus.SHORTLISTED)
    )
    await db_session.commit()
    no_proposal = ok(await (await api(crew.team.owner)).get(f"/ideas/{crew.ref}/ai-runs"))
    assert no_proposal["permissions"]["draft_section_blocked_by"] == "no_proposal"

    await db_session.execute(
        update(Idea).where(Idea.id == crew.idea.id).values(evaluation_closed_at=utcnow())
    )
    await db_session.commit()
    closed = ok(await (await api(crew.team.owner)).get(f"/ideas/{crew.ref}/ai-runs"))
    assert closed["permissions"]["request_evaluation_blocked_by"] == "evaluation_closed"

    await db_session.execute(
        update(Project).where(Project.id == crew.team.project.id).values(archived_at=utcnow())
    )
    await db_session.commit()
    archived = ok(await (await api(crew.team.owner)).get(f"/ideas/{crew.ref}/ai-runs"))
    assert archived["permissions"]["research_blocked_by"] == "project_archived"
    assert archived["permissions"]["include_ai_blocked_by"] == "project_archived"
    assert archived["permissions"]["can_cancel"] is True


async def test_research_only_agent_blocks_evaluation_with_no_agent(
    api: AsUser, crew: Crew, db_session: AsyncSession
) -> None:
    await db_session.execute(
        update(AiAgent).where(AiAgent.id == crew.agent.id).values(purposes=["research"])
    )
    await db_session.commit()

    listed = ok(await (await api(crew.team.owner)).get(f"/ideas/{crew.ref}/ai-runs"))

    assert listed["permissions"]["request_evaluation_blocked_by"] == "no_agent"
    assert listed["permissions"]["can_research"] is True
    assert listed["agents"][0]["purposes"] == ["research"]


async def test_runs_are_listed_newest_first_with_kind_and_limit(
    api: AsUser, crew: Crew, db_session: AsyncSession
) -> None:
    first = await open_run(
        db_session,
        crew.agent,
        crew.idea,
        AiRunKind.RESEARCH,
        status=AiRunStatus.FAILED,
        created_at=ago(minutes=3),
    )
    second = await open_run(
        db_session, crew.agent, crew.idea, AiRunKind.EVALUATE, created_at=ago(minutes=2)
    )
    third = await open_run(
        db_session, crew.agent, crew.idea, AiRunKind.RESEARCH, created_at=ago(minutes=1)
    )
    viewer = await api(crew.team.viewer)

    everything = ok(await viewer.get(f"/ideas/{crew.ref}/ai-runs"))
    research = ok(await viewer.get(f"/ideas/{crew.ref}/ai-runs", kind="research", limit=1))

    assert [r["id"] for r in everything["items"]] == [str(third.id), str(second.id), str(first.id)]
    assert [r["id"] for r in research["items"]] == [str(third.id)]
    failed = everything["items"][2]
    assert failed["error"] == {
        "code": "agent_failed",
        "message": "The agent stopped with an error.",
    }
    assert everything["items"][1]["deadline_at"] is not None
    assert everything["items"][1]["can_cancel"] is False  # a viewer
    assert_problem(
        await (await api(crew.team.outsider)).get(f"/ideas/{crew.ref}/ai-runs"), 404, "not_found"
    )


async def test_a_run_of_another_idea_is_404(
    api: AsUser, crew: Crew, db_session: AsyncSession
) -> None:
    other = await make_idea(db_session, crew.team.project)
    run = await open_run(db_session, crew.agent, other, AiRunKind.RESEARCH)
    owner = await api(crew.team.owner)

    assert_problem(await owner.get(f"/ideas/{crew.ref}/ai-runs/{run.id}"), 404, "not_found")
    ok(await owner.get(f"/ideas/CUST-{other.number}/ai-runs/{run.id}"))


async def test_service_accounts_never_request_runs(crew: Crew, db_session: AsyncSession) -> None:
    """Agents can't start runs: they are never owners or admins, and REST is refused."""
    from app.authz import Resource, Rule, authorize
    from app.authz.policy import IdeaFacts, ProjectFacts
    from app.domain.principal import Principal

    member = Principal(user=crew.agent.user)
    resource = Resource(
        project=ProjectFacts(id=crew.team.project.id, visibility=ProjectVisibility.PRIVATE),
        role=ProjectRole.MEMBER,
        idea=IdeaFacts.of(crew.idea),
        ai_available=True,
    )
    for rule in (
        Rule.AI_REQUEST_EVALUATION,
        Rule.AI_RESEARCH,
        Rule.AI_DRAFT_SECTION,
        Rule.AI_CANCEL_RUN,
    ):
        assert authorize(member, rule, resource).status == 403
    assert await make_user(db_session)  # (the database is still usable)


async def test_held_and_closed_ideas_say_why(
    api: AsUser, crew: Crew, db_session: AsyncSession
) -> None:
    await db_session.execute(
        update(Idea).where(Idea.id == crew.idea.id).values(held_for=HoldReason.MODERATION)
    )
    await db_session.commit()
    held = ok(await (await api(crew.team.admin)).get(f"/ideas/{crew.ref}/ai-runs"))
    await db_session.execute(
        update(Idea)
        .where(Idea.id == crew.idea.id)
        .values(held_for=None, status=IdeaStatus.CLOSED, resolution=Resolution.PARKED)
    )
    await db_session.commit()
    closed = ok(await (await api(crew.team.owner)).get(f"/ideas/{crew.ref}/ai-runs"))

    assert held["permissions"]["research_blocked_by"] == "awaiting_moderation"
    assert held["permissions"]["include_ai_blocked_by"] == "awaiting_moderation"
    assert closed["permissions"]["research_blocked_by"] == "idea_closed"
    assert closed["permissions"]["request_evaluation_blocked_by"] == "evaluation_closed"
