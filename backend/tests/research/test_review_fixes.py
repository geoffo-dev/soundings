"""Phase 8 review fixes for the research step, tests first.

* **M1** (code review): an answer that let an idea past Research can't vanish. Once the
  idea is in a status after Research, a required item's answer can be edited but not
  cleared (409 ``research_answer_required``), so "answer, move on, clear" no longer
  leaves an idea in Proposal at 0/3 with no trace. Optional items, and ideas in Research
  or before it (where clearing re-arms the gate), clear as before.
* **L3** (code review): public tracking history reads each move with the research step
  it happened under (recorded on the event), so moving the step later never rewrites it.
* **L1** (code review): two titles that Python's ``casefold`` keeps apart but the
  database's ``lower()`` folds together ("Idea", "İdea") are a 422, not a 500, in the
  rubric, the proposal template and the research checklist.
* **L2** (code review): "one visible character" means a letter, digit, punctuation or
  symbol after invisible characters are removed (a lone ZWJ, variation selector,
  combining mark or braille blank is not an answer); the length counts the cleaned
  text; section and item titles follow the same rule.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import ActivityEvent
from app.models.enums import IdeaStatus, ResearchStep
from app.models.idea import Idea
from app.models.research import ResearchAnswer, ResearchChecklistItem
from tests.api_keys.helpers import key_client, make_key
from tests.factories import make_idea
from tests.research.conftest import (
    AsUser,
    Team,
    answer,
    answer_required,
    assert_problem,
    ok,
    set_step,
)

S = IdeaStatus
TEXT = "Legal (contracts team), 3 Oct: fine if we keep the standard terms."


def _item_url(idea: Idea, item: ResearchChecklistItem) -> str:
    return f"/ideas/{idea.id}/research/items/{item.id}"


def _move(status: IdeaStatus, **extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"status": status.value, **extra}
    if status is S.CLOSED:
        body.setdefault("resolution", "parked")
    return body


async def _answers(db: AsyncSession, idea: Idea) -> dict[Any, str]:
    rows = await db.execute(
        select(ResearchAnswer.item_id, ResearchAnswer.answer)
        .where(ResearchAnswer.idea_id == idea.id)
        .execution_options(populate_existing=True)
    )
    return dict(rows.all())


# --- M1: a required answer stays once the idea is past Research --------------------------
async def test_the_reviewers_path_no_longer_leaves_a_proposal_without_research(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    """CUST-24 in the review: answered, moved to Evaluating, cleared both answers, moved
    on, started the proposal: in Proposal at 0/3 with no trace."""
    items = await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION)
    idea = await make_idea(db_session, team.project, status=S.RESEARCH, owner=team.owner)
    olive = await api(team.owner)
    for item in items[:2]:
        ok(await olive.put(_item_url(idea, item), {"answer": "x"}))
    ok(await olive.post(f"/ideas/{idea.id}/status", _move(S.EVALUATING)))

    refused = [await olive.delete(_item_url(idea, item)) for item in items[:2]]

    for response in refused:
        body = assert_problem(response, 409, "research_answer_required")
        assert body["detail"] == (
            "This idea is past Research: a required item's answer can be changed but not cleared."
        )
    assert set(await _answers(db_session, idea)) == {items[0].id, items[1].id}


@pytest.mark.parametrize(
    ("step", "status"),
    [
        (ResearchStep.BEFORE_EVALUATION, S.EVALUATING),
        (ResearchStep.BEFORE_EVALUATION, S.SHORTLISTED),
        (ResearchStep.BEFORE_EVALUATION, S.PROPOSAL),
        (ResearchStep.BEFORE_PROPOSAL, S.PROPOSAL),
    ],
)
@pytest.mark.parametrize("who", ["owner", "admin", "platform"])
async def test_a_required_answer_past_research_is_kept_for_everyone(
    api: AsUser,
    team: Team,
    db_session: AsyncSession,
    step: ResearchStep,
    status: IdeaStatus,
    who: str,
) -> None:
    items = await set_step(db_session, team.project, step)
    idea = await make_idea(db_session, team.project, status=status, owner=team.owner)
    await answer(db_session, idea, items[0], team.owner)

    response = await (await api(getattr(team, who))).delete(_item_url(idea, items[0]))

    assert_problem(response, 409, "research_answer_required")
    assert await _answers(db_session, idea) == {items[0].id: TEXT}


async def test_an_unanswered_required_item_past_research_clears_idempotently(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    """Nothing to keep: clearing an item with no answer stays a no-op (200)."""
    items = await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION)
    idea = await make_idea(db_session, team.project, status=S.EVALUATING, owner=team.owner)

    response = await (await api(team.owner)).delete(_item_url(idea, items[0]))

    assert ok(response)["items"][0]["answer"] is None


async def test_editing_a_required_answer_past_research_is_allowed(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    items = await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION)
    idea = await make_idea(db_session, team.project, status=S.EVALUATING, owner=team.owner)
    await answer(db_session, idea, items[0], team.owner)

    body = ok(
        await (await api(team.admin)).put(
            _item_url(idea, items[0]), {"answer": "Legal, 9 Oct: confirmed in writing."}
        )
    )

    item = body["items"][0]
    assert item["answer"]["answer"] == "Legal, 9 Oct: confirmed in writing."
    assert item["answer"]["answered_by"]["id"] == str(team.owner.id)  # the first author kept
    assert item["answer"]["updated_by"]["id"] == str(team.admin.id)


async def test_an_optional_answer_past_research_still_clears(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    items = await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION)
    idea = await make_idea(db_session, team.project, status=S.EVALUATING, owner=team.owner)
    await answer(db_session, idea, items[2], team.owner)  # "Data protection considered"
    assert not items[2].required

    body = ok(await (await api(team.owner)).delete(_item_url(idea, items[2])))

    assert body["items"][2]["answer"] is None
    assert await _answers(db_session, idea) == {}


@pytest.mark.parametrize(
    ("step", "status"),
    [
        (ResearchStep.BEFORE_EVALUATION, S.NEW),
        (ResearchStep.BEFORE_EVALUATION, S.RESEARCH),
        (ResearchStep.BEFORE_PROPOSAL, S.NEW),
        (ResearchStep.BEFORE_PROPOSAL, S.EVALUATING),  # before Research in this lifecycle
        (ResearchStep.BEFORE_PROPOSAL, S.SHORTLISTED),
        (ResearchStep.BEFORE_PROPOSAL, S.RESEARCH),
    ],
)
async def test_a_required_answer_before_or_in_research_still_clears(
    api: AsUser, team: Team, db_session: AsyncSession, step: ResearchStep, status: IdeaStatus
) -> None:
    items = await set_step(db_session, team.project, step)
    idea = await make_idea(db_session, team.project, status=status, owner=team.owner)
    await answer_required(db_session, idea, items, team.owner)

    body = ok(await (await api(team.owner)).delete(_item_url(idea, items[0])))

    assert body["items"][0]["answer"] is None
    assert body["blocking"] is True  # clearing re-arms the gate


async def test_moving_back_into_research_lets_answers_be_cleared_and_rearms_the_gate(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    """Crossing only (lead): an idea moved back to Research crosses the gate again when
    it moves on, so its answers may be cleared there and must be given again."""
    items = await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION)
    idea = await make_idea(db_session, team.project, status=S.RESEARCH, owner=team.owner)
    await answer_required(db_session, idea, items, team.owner)
    olive = await api(team.owner)
    ok(await olive.post(f"/ideas/{idea.id}/status", _move(S.EVALUATING)))
    assert_problem(await olive.delete(_item_url(idea, items[0])), 409, "research_answer_required")
    ok(await olive.post(f"/ideas/{idea.id}/status", _move(S.RESEARCH)))

    ok(await olive.delete(_item_url(idea, items[0])))

    assert_problem(
        await olive.post(f"/ideas/{idea.id}/status", _move(S.EVALUATING)),
        409,
        "research_incomplete",
    )


async def test_the_409_comes_after_the_answer_rules_own_checks(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    """401 -> 404 (item) -> 403 (idea.answer_research) -> 409 step off -> 409 kept."""
    items = await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION)
    idea = await make_idea(db_session, team.project, status=S.EVALUATING, owner=team.owner)
    await answer(db_session, idea, items[0], team.owner)

    member = await (await api(team.member)).delete(_item_url(idea, items[0]))

    assert_problem(member, 403, "forbidden")


async def test_a_write_key_gets_the_same_409(
    app: FastAPI, team: Team, db_session: AsyncSession
) -> None:
    items = await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION)
    idea = await make_idea(db_session, team.project, status=S.EVALUATING, owner=team.owner)
    await answer(db_session, idea, items[0], team.owner)
    secret = await make_key(db_session, team.owner, scopes=["read", "write"])

    async with key_client(app, secret) as client:
        response = await client.delete(f"/api/v1{_item_url(idea, items[0])}")

    assert_problem(response, 409, "research_answer_required")


# --- L3: tracking history doesn't change when the step moves ------------------------------
async def test_a_status_change_records_the_step_when_research_is_involved(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    items = await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION)
    idea = await make_idea(db_session, team.project, status=S.NEW, owner=team.owner)
    olive = await api(team.owner)
    ok(await olive.post(f"/ideas/{idea.id}/status", _move(S.RESEARCH)))
    await answer_required(db_session, idea, items, team.owner)
    ok(await olive.post(f"/ideas/{idea.id}/status", _move(S.EVALUATING)))
    ok(await olive.post(f"/ideas/{idea.id}/status", _move(S.SHORTLISTED)))

    payloads: Any = await db_session.scalars(
        select(ActivityEvent.payload)
        .where(ActivityEvent.idea_id == idea.id, ActivityEvent.type == "status_changed")
        .order_by(ActivityEvent.created_at, ActivityEvent.id)
    )

    assert [payload.get("research_step") for payload in payloads] == [
        "before_evaluation",  # New -> Research
        "before_evaluation",  # Research -> Evaluating
        None,  # Evaluating -> Shortlisted: Research not involved, nothing recorded
    ]


# --- L1: titles the database folds together are a 422 ---------------------------------------
async def test_titles_the_database_folds_together_are_a_422_everywhere(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    ada = await api(team.admin)
    rubric = {"criteria": [{"name": "Idea"}, {"name": "\u0130dea"}, {"name": "Value"}]}
    template = {"sections": [{"title": "Idea"}, {"title": "\u0130dea"}]}
    research = {"step": "before_evaluation", "items": [{"title": "Idea"}, {"title": "\u0130dea"}]}

    responses = {
        "rubric": await ada.put(f"/projects/{team.slug}/rubric", rubric),
        "template": await ada.put(f"/projects/{team.slug}/proposal-template", template),
        "research": await ada.put(f"/projects/{team.slug}/research", research),
    }

    messages = {}
    for name, response in responses.items():
        body = assert_problem(response, 422, "validation_error")
        [error] = body["errors"]
        messages[name] = (error["loc"], error["msg"])
    assert messages == {
        "rubric": (["body", "criteria"], "Value error, criterion names must be unique"),
        "template": (["body", "sections"], "Value error, section titles must be unique"),
        "research": (["body", "items"], "Value error, item titles must be unique"),
    }
    assert ok(await ada.get(f"/projects/{team.slug}/research"))["step"] == "off"


# --- L2: one visible character, lengths after cleaning, titles too ---------------------------
BLANK_LOOKING = [
    "\u200d",  # ZWJ
    "\u200c",  # ZWNJ
    "\ufe0f",  # VS16
    "\u2800",  # braille pattern blank
    "\u180b",  # Mongolian free variation selector
    "\u17b4",  # Khmer inherent vowel
    "\u0301",  # a lone combining acute accent
    " \u200d\u0301 ",
]


@pytest.mark.parametrize("text", BLANK_LOOKING)
async def test_blank_looking_answers_are_refused_and_never_pass_the_gate(
    api: AsUser, team: Team, db_session: AsyncSession, text: str
) -> None:
    items = await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION)
    idea = await make_idea(db_session, team.project, status=S.RESEARCH, owner=team.owner)
    olive = await api(team.owner)

    responses = [await olive.put(_item_url(idea, item), {"answer": text}) for item in items[:2]]

    for response in responses:
        assert_problem(response, 422, "validation_error")
    assert await _answers(db_session, idea) == {}
    assert_problem(
        await olive.post(f"/ideas/{idea.id}/status", _move(S.EVALUATING)),
        409,
        "research_incomplete",
    )


@pytest.mark.parametrize(
    "text",
    [
        "\U0001f469\u200d\U0001f4bb Product team agreed",  # an emoji ZWJ sequence
        "e\u0301quipe juridique: ok",  # a combining accent on a letter
        "\u2764\ufe0f",  # a symbol with VS16
        "\u0928\u094d\u200d\u092f",  # Devanagari with ZWJ
        "42",
        "?",
    ],
)
async def test_real_answers_with_joiners_and_marks_are_kept(
    api: AsUser, team: Team, db_session: AsyncSession, text: str
) -> None:
    items = await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION)
    idea = await make_idea(db_session, team.project, status=S.RESEARCH, owner=team.owner)

    body = ok(await (await api(team.owner)).put(_item_url(idea, items[0]), {"answer": text}))

    assert body["items"][0]["answer"]["answer"] == text


async def test_the_answer_length_counts_the_cleaned_text(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    """Contract section 3.4: invisible characters are removed before the length check."""
    items = await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION)
    idea = await make_idea(db_session, team.project, status=S.RESEARCH, owner=team.owner)
    olive = await api(team.owner)

    fits = await olive.put(_item_url(idea, items[0]), {"answer": "a" * 2000 + "\u200b" * 5})
    too_long = await olive.put(_item_url(idea, items[1]), {"answer": "a" * 2001})

    assert ok(fits)["items"][0]["answer"]["answer"] == "a" * 2000
    assert_problem(too_long, 422, "validation_error")


BLANK_TITLES = ["\u200b", "\u2800", "\u3164", "\u0301", "\u00ad"]


@pytest.mark.parametrize("title", BLANK_TITLES)
async def test_blank_looking_titles_are_refused(
    api: AsUser, team: Team, db_session: AsyncSession, title: str
) -> None:
    ada = await api(team.admin)

    template = await ada.put(
        f"/projects/{team.slug}/proposal-template",
        {"sections": [{"title": "Summary"}, {"title": title}]},
    )
    research = await ada.put(
        f"/projects/{team.slug}/research",
        {"step": "before_evaluation", "items": [{"title": title}]},
    )

    assert_problem(template, 422, "validation_error")
    assert_problem(research, 422, "validation_error")


async def test_titles_lose_invisible_characters_so_look_alikes_are_duplicates(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    ada = await api(team.admin)

    duplicate = await ada.put(
        f"/projects/{team.slug}/research",
        {"step": "before_evaluation", "items": [{"title": "Legal"}, {"title": "Le\u200bgal"}]},
    )
    cleaned = await ada.put(
        f"/projects/{team.slug}/research",
        {"step": "before_evaluation", "items": [{"title": "Le\u200bgal\u00ad team"}]},
    )
    section = await ada.put(
        f"/projects/{team.slug}/proposal-template",
        {"sections": [{"title": "\u200bThe ask\u2060"}]},
    )

    assert_problem(duplicate, 422, "validation_error")
    assert [item["title"] for item in ok(cleaned)["items"]] == ["Legal team"]
    assert [item["title"] for item in ok(section)["sections"]] == ["The ask"]
