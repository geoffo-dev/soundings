"""SPEC Phase 5 acceptance, end to end over MCP (contract-phase5 section 3.9): an MCP
client with a key can search ideas and submit an evaluation only in permitted projects;
revoking the key cuts access immediately. (qa runs the same story against the demo data
in tests/acceptance and e2e.)"""

from __future__ import annotations

import httpx2
import pytest
from mcp import MCPError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import AuditLog
from app.models.api_key import ApiKey
from app.models.base import utcnow
from app.models.enums import EvaluatorState, IdeaStatus, ProjectRole
from app.services.scoring import recompute_aggregates
from tests.factories import add_evaluator, make_idea, make_project
from tests.mcp.conftest import Connect, MakeKey, Team, call, data, error, full_scores, headers, rpc


async def test_search_and_evaluate_only_where_the_key_reaches_then_revoke(
    connect: Connect,
    make_key: MakeKey,
    raw: httpx2.AsyncClient,
    team: Team,
    db_session: AsyncSession,
) -> None:
    carol = team.evaluators[0]
    tools_project = await make_project(
        db_session,
        slug="internal-tools",
        key="TOOLS",
        name="Internal Tools",
        members={carol: ProjectRole.MEMBER},
    )
    cust = await make_idea(db_session, team.project, title="Refunds", status=IdeaStatus.EVALUATING)
    tools = await make_idea(
        db_session, tools_project, title="Build bot", status=IdeaStatus.EVALUATING
    )
    for other in team.evaluators[1:]:
        await add_evaluator(db_session, cust, other, state=EvaluatorState.SUBMITTED)
    await add_evaluator(db_session, cust, carol)
    await add_evaluator(db_session, tools, carol)
    await recompute_aggregates(db_session, idea_ids=[cust.id])
    await db_session.commit()
    cust_key, tools_key = f"CUST-{cust.number}", f"TOOLS-{tools.number}"
    # 1. "Claude Desktop": read, evaluate, mcp; Customer Innovation only.
    secret = await make_key(
        carol, ["read", "evaluate", "mcp"], [team.project], name="Claude Desktop"
    )

    async with connect(secret) as client:
        # 2. Nine tools; only Customer Innovation; only CUST-n awaits, blind.
        assert len((await client.list_tools()).tools) == 9
        projects = data(await call(client, "list_projects"))["projects"]
        assert [p["key"] for p in projects] == ["CUST"]
        awaiting = data(await call(client, "search_ideas", awaiting_my_evaluation=True))["items"]
        assert [(i["key"], i["score_hidden"], i["score"]) for i in awaiting] == [
            (cust_key, True, None)
        ]
        # 3. Blind until submitted; then the others' evaluations and the aggregate.
        before = data(await call(client, "get_idea", idea=cust_key))["idea"]
        assert (before["evaluations"], before["aggregate"]) == ([], None)
        rubric = data(await call(client, "get_rubric", idea=cust_key))
        scores = [
            {"criterion_id": c["id"], "score": 4, "comment": "Fine."} for c in rubric["criteria"]
        ]
        submitted = data(
            await call(
                client,
                "submit_evaluation",
                idea=cust_key,
                scores=scores,
                recommendation="go",
                comment="Worth a pilot.",
            )
        )
        assert submitted["evaluation"]["state"] == "submitted"
        after = data(await call(client, "get_idea", idea=cust_key))["idea"]
        assert after["evaluation_count"] == 2
        assert after["aggregate"]["count"] == 3
        # 4. Outside the restriction: not found, although Carol may evaluate it in the app;
        # no write scope: insufficient_scope.
        assert error(await call(client, "get_idea", idea=tools_key)) == "not_found"
        outside = await call(
            client,
            "submit_evaluation",
            idea=tools_key,
            scores=full_scores(team),
            recommendation="go",
        )
        assert error(outside) == "not_found"
        created = await call(client, "create_idea", project=team.slug, title="x", summary="y")
        assert error(created) == "insufficient_scope"

        # 5. The audit log shows every call and the evaluation, through the key.
        calls = list(
            await db_session.scalars(
                select(AuditLog).where(AuditLog.action == "mcp.call").order_by(AuditLog.created_at)
            )
        )
        assert [(c.details["tool"], c.details["decision"]) for c in calls] == [
            ("list_projects", "allow"),
            ("search_ideas", "allow"),
            ("get_idea", "allow"),
            ("get_rubric", "allow"),
            ("submit_evaluation", "allow"),
            ("get_idea", "allow"),
            ("get_idea", "deny"),
            ("submit_evaluation", "deny"),
            ("create_idea", "deny"),
        ]
        evaluation = await db_session.scalar(
            select(AuditLog).where(AuditLog.action == "evaluation.submit")
        )
        assert evaluation is not None
        assert evaluation.details["api_key_id"] == calls[0].details["api_key_id"]

        # 6. Revoked in Settings: the very next call fails, and REST too.
        await db_session.execute(update(ApiKey).values(revoked_at=utcnow()))
        await db_session.commit()
        with pytest.raises(MCPError):
            await client.call_tool("list_projects", {})

    response = await raw.post("/mcp", json=rpc("tools/list"), headers=headers(secret))
    assert response.status_code == 401
    rest = await raw.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {secret}"})
    assert rest.status_code == 401
