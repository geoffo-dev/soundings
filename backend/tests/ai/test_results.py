"""What agents write and how it is matched (contract-phase6 sections 3.4, 3.7, 3.8 and 4):
rationale and sources, exclusion from the aggregate by default and the include toggle,
the reset on a changed re-submission, research notes (write, replace, read, delete),
and the ``tool_called`` / ``result_recorded`` events."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import AuditLog
from app.models.base import utcnow
from app.models.enums import AiRunKind, EvaluatorState
from app.models.idea import Idea
from app.models.project import Project
from tests.ai.conftest import AsUser, Crew, McpAs, assert_problem, evaluation_args, ok
from tests.ai.helpers import events, open_run, run_row
from tests.factories import add_evaluator, make_idea
from tests.mcp.conftest import MakeKey


async def _evaluated(crew: Crew, db: AsyncSession) -> None:
    """Two people submitted (scores 2 and 4 on every criterion); the agent is assigned."""
    for evaluator, score in zip(crew.team.evaluators[:2], (2, 4), strict=True):
        await add_evaluator(
            db,
            crew.idea,
            evaluator,
            state=EvaluatorState.SUBMITTED,
            scores={c.name: score for c in crew.team.rubric},
        )
    from app.services.scoring import recompute_aggregates

    await recompute_aggregates(db, idea_ids=[crew.idea.id])
    await db.commit()
    await add_evaluator(db, crew.idea, crew.agent.user)


async def _submit(crew: Crew, mcp_as: McpAs, *, score: int = 4, **changes: Any) -> dict[str, Any]:
    assert crew.agent.key is not None
    agent = mcp_as(crew.agent.key)
    rubric = await agent.ok("get_rubric", idea=crew.ref)
    args = evaluation_args(crew, rubric, score=score) | changes
    return await agent.ok("submit_evaluation", **args)


async def _score(api: AsUser, crew: Crew) -> tuple[float | None, int]:
    detail = ok(await (await api(crew.team.owner)).get(f"/ideas/{crew.ref}"))
    aggregate = detail["aggregate"]
    return (aggregate["overall"], aggregate["count"]) if aggregate else (None, 0)


async def _first_mean(api: AsUser, crew: Crew) -> float:
    detail = ok(await (await api(crew.team.owner)).get(f"/ideas/{crew.ref}"))
    mean: float = detail["aggregate"]["criteria"][0]["mean"]
    return mean


# --- Excluded by default; the toggle ------------------------------------------------------
async def test_an_ai_evaluation_is_left_out_until_someone_includes_it(
    api: AsUser, crew: Crew, db_session: AsyncSession, mcp_as: McpAs
) -> None:
    await _evaluated(crew, db_session)
    await open_run(db_session, crew.agent, crew.idea, AiRunKind.EVALUATE)
    before = await _score(api, crew)

    await _submit(crew, mcp_as, score=5)
    listed = ok(await (await api(crew.team.owner)).get(f"/ideas/{crew.ref}/evaluations"))
    [ai] = [e for e in listed["items"] if e["is_ai"]]
    left_out = await _score(api, crew)
    owner = await api(crew.team.owner)
    path = f"/ideas/{crew.ref}/evaluations/{ai['id']}/include-in-aggregate"
    included = ok(await owner.put(path, {"include": True}))
    counted = await _score(api, crew)
    counted_mean = await _first_mean(api, crew)
    ok(await owner.put(path, {"include": True}))  # idempotent
    excluded = ok(await owner.put(path, {"include": False}))
    back = await _score(api, crew)

    assert before == left_out == back == (3.0, 2)
    assert ai["include_in_aggregate"] is False
    assert included["include_in_aggregate"] is True
    assert included["is_ai"] is True
    assert counted[1] == 3
    assert counted_mean == pytest.approx((2 + 4 + 5) / 3, abs=0.05)  # rounded to 0.1
    assert await _first_mean(api, crew) == 3.0
    assert excluded["include_in_aggregate"] is False
    # Rationale and sources reach REST (plain ASCII URLs, the host shown).
    first = ai["scores"][0]
    assert first["comment"].startswith("RATIONALE")
    assert [s["host"] for s in first["sources"]] == ["example.org", "example.org"]
    people = [e for e in listed["items"] if not e["is_ai"]]
    assert all(score["sources"] == [] for e in people for score in e["scores"])
    audits = list(
        await db_session.scalars(select(AuditLog).where(AuditLog.action == "evaluation.include_ai"))
    )
    assert [(a.details["include"], a.details["evaluator_id"]) for a in audits] == [
        (True, str(crew.agent.user.id)),
        (False, str(crew.agent.user.id)),
    ]


async def test_a_changed_re_submission_leaves_the_aggregate_again(
    api: AsUser, crew: Crew, db_session: AsyncSession, mcp_as: McpAs
) -> None:
    await _evaluated(crew, db_session)
    await open_run(db_session, crew.agent, crew.idea, AiRunKind.EVALUATE)
    await _submit(crew, mcp_as, score=5)
    listed = ok(await (await api(crew.team.owner)).get(f"/ideas/{crew.ref}/evaluations"))
    [ai] = [e for e in listed["items"] if e["is_ai"]]
    path = f"/ideas/{crew.ref}/evaluations/{ai['id']}/include-in-aggregate"
    owner = await api(crew.team.owner)
    ok(await owner.put(path, {"include": True}))

    text_only = await _submit(crew, mcp_as, score=5, comment="A clearer summary.")
    still = ok(await owner.get(f"/ideas/{crew.ref}/evaluations"))
    changed = await _submit(crew, mcp_as, score=3)
    reset = ok(await owner.get(f"/ideas/{crew.ref}/evaluations"))
    ok(await owner.put(path, {"include": True}))
    recommendation = await _submit(crew, mcp_as, score=3, recommendation="no")
    reset_again = ok(await owner.get(f"/ideas/{crew.ref}/evaluations"))

    assert text_only["evaluation"]["state"] == changed["evaluation"]["state"] == "submitted"
    assert recommendation["evaluation"]["recommendation"] == "no"
    assert [e["include_in_aggregate"] for e in still["items"] if e["is_ai"]] == [True]
    assert [e["include_in_aggregate"] for e in reset["items"] if e["is_ai"]] == [False]
    assert [e["include_in_aggregate"] for e in reset_again["items"] if e["is_ai"]] == [False]
    assert await _score(api, crew) == (3.0, 2)
    resets = [
        a
        for a in await db_session.scalars(
            select(AuditLog).where(AuditLog.action == "evaluation.submit")
        )
        if a.details.get("include_reset")
    ]
    assert len(resets) == 2


async def test_the_toggle_refusals(
    api: AsUser, crew: Crew, db_session: AsyncSession, mcp_as: McpAs
) -> None:
    await _evaluated(crew, db_session)
    await open_run(db_session, crew.agent, crew.idea, AiRunKind.EVALUATE)
    await _submit(crew, mcp_as)
    owner = await api(crew.team.owner)
    listed = ok(await owner.get(f"/ideas/{crew.ref}/evaluations"))
    ai = next(e for e in listed["items"] if e["is_ai"])
    person = next(e for e in listed["items"] if not e["is_ai"])

    def path(evaluation_id: str, ref: str | None = None) -> str:
        return f"/ideas/{ref or crew.ref}/evaluations/{evaluation_id}/include-in-aggregate"

    assert_problem(await owner.put(path(person["id"]), {"include": True}), 409, "not_ai_evaluation")
    assert_problem(
        await (await api(crew.team.member)).put(path(ai["id"]), {"include": True}), 403, "forbidden"
    )
    assert_problem(
        await (await api(crew.team.outsider)).put(path(ai["id"]), {"include": True}),
        404,
        "not_found",
    )
    other = await make_idea(db_session, crew.team.project, owner=crew.team.owner)
    assert_problem(
        await owner.put(path(ai["id"], f"CUST-{other.number}"), {"include": True}), 404, "not_found"
    )
    # An admin who is a pending evaluator sees no evaluation: 404, not 403.
    await add_evaluator(db_session, crew.idea, crew.team.admin)
    assert_problem(
        await (await api(crew.team.admin)).put(path(ai["id"]), {"include": True}), 404, "not_found"
    )
    # Archived: read-only.
    await db_session.execute(
        update(Project).where(Project.id == crew.team.project.id).values(archived_at=utcnow())
    )
    await db_session.commit()
    assert_problem(await owner.put(path(ai["id"]), {"include": True}), 409, "project_archived")


async def test_a_draft_ai_evaluation_is_404_for_the_toggle(
    api: AsUser, crew: Crew, db_session: AsyncSession, mcp_as: McpAs
) -> None:
    await add_evaluator(db_session, crew.idea, crew.agent.user)
    await open_run(db_session, crew.agent, crew.idea, AiRunKind.EVALUATE)
    assert crew.agent.key is not None
    await mcp_as(crew.agent.key).ok("submit_evaluation", idea=crew.ref, scores=[], submit=False)
    from app.models.evaluation import Evaluation

    draft = await db_session.scalar(
        select(Evaluation).where(Evaluation.evaluator_id == crew.agent.user.id)
    )
    assert draft is not None

    response = await (await api(crew.team.owner)).put(
        f"/ideas/{crew.ref}/evaluations/{draft.id}/include-in-aggregate", {"include": True}
    )

    assert_problem(response, 404, "not_found")


# --- Rationale and sources ------------------------------------------------------------------
async def test_an_ai_evaluator_must_give_a_rationale_for_every_score(
    crew: Crew, db_session: AsyncSession, mcp_as: McpAs
) -> None:
    await add_evaluator(db_session, crew.idea, crew.agent.user)
    await open_run(db_session, crew.agent, crew.idea, AiRunKind.EVALUATE)
    assert crew.agent.key is not None
    agent = mcp_as(crew.agent.key)
    rubric = await agent.ok("get_rubric", idea=crew.ref)
    args = evaluation_args(crew, rubric)
    args["scores"][0]["comment"] = "   "

    result = await agent.call("submit_evaluation", **args)

    assert result.is_error
    assert result.structured_content["code"] == "evaluation_incomplete"
    assert f"scores.{args['scores'][0]['criterion_id']}.comment" in result.content[0].text  # type: ignore[union-attr]


async def test_people_never_cite_sources(
    crew: Crew, db_session: AsyncSession, mcp_as: McpAs, make_key: MakeKey
) -> None:
    evaluator = crew.team.evaluators[0]
    await add_evaluator(db_session, crew.idea, evaluator)
    person = mcp_as(await make_key(evaluator))
    rubric = await person.ok("get_rubric", idea=crew.ref)
    args = evaluation_args(crew, rubric)

    result = await person.call("submit_evaluation", **args)

    assert result.is_error
    assert result.structured_content["code"] == "validation_error"
    assert "Only AI evaluators cite sources." in result.content[0].text  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("url", "stored"),
    [
        ("https://bücher.example/straße?q=ä", "https://xn--bcher-kva.example/stra%C3%9Fe?q=%C3%A4"),
        ("HTTPS://Example.ORG/A", "https://example.org/A"),
    ],
)
async def test_sources_are_stored_as_plain_ascii(
    api: AsUser, crew: Crew, db_session: AsyncSession, mcp_as: McpAs, url: str, stored: str
) -> None:
    await add_evaluator(db_session, crew.idea, crew.agent.user)
    await open_run(db_session, crew.agent, crew.idea, AiRunKind.EVALUATE)
    assert crew.agent.key is not None
    agent = mcp_as(crew.agent.key)
    rubric = await agent.ok("get_rubric", idea=crew.ref)
    args = evaluation_args(crew, rubric)
    args["scores"][0]["sources"] = [{"title": "International", "url": url}]

    await agent.ok("submit_evaluation", **args)
    listed = ok(await (await api(crew.team.owner)).get(f"/ideas/{crew.ref}/evaluations"))

    [ai] = listed["items"]
    assert ai["scores"][0]["sources"][0]["url"] == stored
    assert ai["scores"][0]["sources"][0]["host"].isascii()


@pytest.mark.parametrize(
    "url",
    [
        "https://exa\u200bmple.org/",  # zero-width space
        "https://example.org/\u202eevil",  # bidi override
        "https://example.org/a b",
        "javascript:alert(1)",
        "https://user:pass@example.org/",
        "mailto:someone@example.org",
    ],
)
async def test_unsafe_source_urls_are_refused(
    crew: Crew, db_session: AsyncSession, mcp_as: McpAs, url: str
) -> None:
    await open_run(db_session, crew.agent, crew.idea, AiRunKind.RESEARCH)
    assert crew.agent.key is not None

    code = await mcp_as(crew.agent.key).fails(
        "add_research_note", idea=crew.ref, body_md="x", sources=[{"title": "t", "url": url}]
    )

    assert code == "validation_error"


# --- Research notes -----------------------------------------------------------------------------
async def test_a_research_note_is_written_replaced_read_and_deleted(
    api: AsUser, crew: Crew, db_session: AsyncSession, mcp_as: McpAs
) -> None:
    run = await open_run(db_session, crew.agent, crew.idea, AiRunKind.RESEARCH)
    assert crew.agent.key is not None
    agent = mcp_as(crew.agent.key)
    sources = [{"title": "Study", "url": "https://example.org/study"}]

    first = await agent.ok("add_research_note", idea=crew.ref, body_md="First", sources=sources)
    second = await agent.ok("add_research_note", idea=crew.ref, body_md="Second")
    note_id = first["note_id"]
    attached = await run_row(db_session, run.id)
    member_view = ok(
        await (await api(crew.team.member)).get(f"/ideas/{crew.ref}/research-notes/{note_id}")
    )
    owner_view = ok(
        await (await api(crew.team.owner)).get(f"/ideas/{crew.ref}/research-notes/{note_id}")
    )
    refused = await (await api(crew.team.member)).delete(
        f"/ideas/{crew.ref}/research-notes/{note_id}"
    )
    deleted = await (await api(crew.team.owner)).delete(
        f"/ideas/{crew.ref}/research-notes/{note_id}"
    )
    again = await (await api(crew.team.admin)).delete(f"/ideas/{crew.ref}/research-notes/{note_id}")
    after = ok(
        await (await api(crew.team.viewer)).get(f"/ideas/{crew.ref}/research-notes/{note_id}")
    )
    feed = ok(await (await api(crew.team.viewer)).get(f"/ideas/{crew.ref}/activity"))

    assert (first["replaced"], second["replaced"]) == (False, True)
    assert second["note_id"] == note_id
    assert str(attached.activity_event_id) == note_id
    assert member_view["body_md"] == "Second"
    assert member_view["sources"] == []
    assert member_view["agent"]["display_name"] == "Idea evaluator"
    assert (member_view["can_delete"], owner_view["can_delete"]) == (False, True)
    assert_problem(refused, 403, "forbidden")
    assert deleted.status_code == again.status_code == 204
    assert (after["deleted"], after["body_md"], after["sources"], after["can_delete"]) == (
        True,
        "",
        [],
        False,
    )
    notes = [i for i in feed["items"] if i["type"] == "ai_research_note"]
    assert [(n["note"]["deleted"], n["actor"]["id"]) for n in notes] == [
        (True, str(crew.agent.user.id))
    ]
    assert_problem(
        await (await api(crew.team.owner)).get(f"/ideas/{crew.ref}/research-notes/{run.id}"),
        404,
        "not_found",
    )
    # No notification for anyone: the requester watches the run, the note is in the feed.
    from app.models.notification import Notification

    assert list(await db_session.scalars(select(Notification))) == []


async def test_a_research_note_needs_an_open_idea(
    crew: Crew, db_session: AsyncSession, mcp_as: McpAs
) -> None:
    from app.models.enums import IdeaStatus, Resolution

    await open_run(db_session, crew.agent, crew.idea, AiRunKind.RESEARCH)
    await db_session.execute(
        update(Idea)
        .where(Idea.id == crew.idea.id)
        .values(status=IdeaStatus.CLOSED, resolution=Resolution.PARKED)
    )
    await db_session.commit()
    assert crew.agent.key is not None

    assert (
        await mcp_as(crew.agent.key).fails("add_research_note", idea=crew.ref, body_md="x")
        == "idea_closed"
    )


# --- Run events from MCP calls --------------------------------------------------------------------
async def test_an_agents_calls_become_soundings_sentences_on_its_open_runs(
    crew: Crew, db_session: AsyncSession, mcp_as: McpAs
) -> None:
    await add_evaluator(db_session, crew.idea, crew.agent.user)
    evaluate = await open_run(db_session, crew.agent, crew.idea, AiRunKind.EVALUATE)
    research = await open_run(db_session, crew.agent, crew.idea, AiRunKind.RESEARCH)
    assert crew.agent.key is not None
    agent = mcp_as(crew.agent.key)

    await agent.ok("get_idea", idea=crew.ref)
    await agent.ok("list_projects")
    await agent.ok("search_ideas")
    await agent.fails("add_comment", idea=crew.ref, body_md="Hello")
    await agent.fails("propose_proposal_section", idea=crew.ref, section_key="risks", body_md="x")
    await agent.ok("submit_evaluation", idea=crew.ref, scores=[], submit=False)
    await agent.call("not_a_tool")

    assert [e.message for e in await events(db_session, evaluate.id)] == [
        "Read the idea",
        "Commented: forbidden",
        "Saved its evaluation",  # a draft: no result_recorded
    ]
    assert [e.message for e in await events(db_session, research.id)] == [
        "Read the idea",
        "Commented: forbidden",
    ]
    assert (await run_row(db_session, evaluate.id)).evaluation_id is None


async def test_nothing_is_attached_or_recorded_after_a_cancel_request(
    crew: Crew, db_session: AsyncSession, mcp_as: McpAs
) -> None:
    run = await open_run(
        db_session, crew.agent, crew.idea, AiRunKind.RESEARCH, cancel_requested=True
    )
    assert crew.agent.key is not None

    code = await mcp_as(crew.agent.key).fails("add_research_note", idea=crew.ref, body_md="Late")

    assert code == "ai_run_not_active"
    assert (await run_row(db_session, run.id)).activity_event_id is None
    assert await events(db_session, run.id) == []


async def test_the_call_is_audited_once_as_mcp_call(
    crew: Crew, db_session: AsyncSession, mcp_as: McpAs
) -> None:
    await open_run(db_session, crew.agent, crew.idea, AiRunKind.RESEARCH)
    assert crew.agent.key is not None

    await mcp_as(crew.agent.key).ok("add_research_note", idea=crew.ref, body_md="NOTE BODY")

    [entry] = [
        a
        for a in await db_session.scalars(select(AuditLog).where(AuditLog.action == "mcp.call"))
        if a.details.get("tool") == "add_research_note"
    ]
    assert entry.actor_id == crew.agent.user.id
    assert "NOTE BODY" not in str(entry.details)
