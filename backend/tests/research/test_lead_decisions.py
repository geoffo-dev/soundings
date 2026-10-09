"""Phase 8b review leftovers: the lead's decisions (docs/decisions.md "Phase 8b review
leftovers (lead, 2026-10-09)").

* **D1:** past Research, a researcher who isn't the idea's owner or an admin no longer
  changes the answers: answering, editing and clearing are theirs only while the idea is
  in Research or a status before it (409 ``research_finished`` afterwards, condition c26 on
  the +Rsr overlay; ``can_answer_research`` / ``can_answer`` false). The owner and admins
  keep Phase 8's rule (M1: past Research a required answer is edited, never cleared).
  Every path: the owner, a project admin, a platform admin, a member researcher, a viewer
  researcher, an internal non-member researcher and a guest researcher (R); sessions and
  API keys.
* **D2:** making a project private ends, at once, the research assignments of researchers
  without a role in it (audited ``made_private``, answers and the due date kept, no feed
  event or notification), like leaving a private project; project admins see how many
  people that is beforehand (``Project.outside_researcher_count``, null for everyone else).
* **D5 (review N1):** ``DueAt`` returns UTC at the schema level.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import AuditLog
from app.models.enums import IdeaStatus, ProjectRole, ProjectVisibility, ResearchStep
from app.models.idea import Idea
from app.models.notification import Notification
from app.models.project import Project, ProjectMember
from app.models.research import ResearchAnswer, ResearchChecklistItem
from app.models.user import User
from app.schemas.base import DueAt
from tests.api_keys.helpers import key_client, make_key
from tests.factories import make_idea, make_user
from tests.research.conftest import (
    AsUser,
    Team,
    answer,
    assert_problem,
    assign,
    feed_types,
    key_of,
    ok,
    researcher_audit,
    set_step,
)

S = IdeaStatus
TEXT = "Legal (contracts team), 3 Oct: fine if we keep the standard terms."
EDITED = "Legal again, 9 Oct: the standard terms still hold."
DUE = "2026-12-11T17:00:00+00:00"


def _url(idea: Idea, item: ResearchChecklistItem) -> str:
    return f"/ideas/{idea.id}/research/items/{item.id}"


async def _make_internal(db: AsyncSession, project: Project) -> None:
    await db.execute(
        update(Project)
        .where(Project.id == project.id)
        .values(visibility=ProjectVisibility.INTERNAL)
    )
    await db.commit()
    project.visibility = ProjectVisibility.INTERNAL


async def _researched(
    api: AsUser,
    team: Team,
    db: AsyncSession,
    researcher: User,
    *,
    status: IdeaStatus,
    step: ResearchStep = ResearchStep.BEFORE_EVALUATION,
) -> tuple[Idea, list[ResearchChecklistItem]]:
    """An idea of the owner in ``status`` with ``researcher`` assigned by an admin (who may
    name anyone) while it was New (past Research nobody new is asked: adversarial check
    L2), and every item answered by the owner."""
    items = await set_step(db, team.project, step)
    idea = await make_idea(db, team.project, status=S.NEW, owner=team.owner)
    ok(await assign(await api(team.admin), key_of(team.project, idea), researcher, DUE))
    await db.execute(update(Idea).where(Idea.id == idea.id).values(status=status))
    await db.commit()
    await db.refresh(idea)
    for item in items:
        await answer(db, idea, item, team.owner)
    return idea, items


async def _who(team: Team, db: AsyncSession, who: str) -> User:
    """The researcher for each kind of principal (D1's paths)."""
    match who:
        case "guest":
            return team.outsider  # no role in the private project: column R
        case "internal":
            await _make_internal(db, team.project)
            return team.outsider  # NMi + Rsr
        case _:
            user: User = getattr(team, who)
            return user


# --- D1: past Research, only the owner and admins change answers ----------------------------
RESEARCHERS = ("member", "viewer", "guest", "internal")


@pytest.mark.parametrize("who", RESEARCHERS)
@pytest.mark.parametrize(
    ("step", "status"),
    [
        (ResearchStep.BEFORE_EVALUATION, S.NEW),
        (ResearchStep.BEFORE_EVALUATION, S.RESEARCH),
        (ResearchStep.BEFORE_PROPOSAL, S.EVALUATING),  # before Research in this lifecycle
        (ResearchStep.BEFORE_PROPOSAL, S.SHORTLISTED),
        (ResearchStep.BEFORE_PROPOSAL, S.RESEARCH),
    ],
)
async def test_a_researcher_answers_edits_and_clears_in_or_before_research(
    api: AsUser,
    team: Team,
    db_session: AsyncSession,
    who: str,
    step: ResearchStep,
    status: IdeaStatus,
) -> None:
    researcher = await _who(team, db_session, who)
    idea, items = await _researched(api, team, db_session, researcher, status=status, step=step)
    client = await api(researcher)

    edited = ok(await client.put(_url(idea, items[0]), {"answer": EDITED}))
    cleared = ok(await client.delete(_url(idea, items[1])))

    assert edited["items"][0]["answer"]["answer"] == EDITED
    assert cleared["items"][1]["answer"] is None
    assert cleared["permissions"]["can_answer"] is True
    assert ok(await client.get(f"/ideas/{idea.id}"))["permissions"]["can_answer_research"]


@pytest.mark.parametrize("who", RESEARCHERS)
@pytest.mark.parametrize(
    ("step", "status"),
    [
        (ResearchStep.BEFORE_EVALUATION, S.EVALUATING),
        (ResearchStep.BEFORE_EVALUATION, S.SHORTLISTED),
        (ResearchStep.BEFORE_EVALUATION, S.PROPOSAL),
        (ResearchStep.BEFORE_PROPOSAL, S.PROPOSAL),
    ],
)
async def test_past_research_a_researcher_can_no_longer_change_the_answers(
    api: AsUser,
    team: Team,
    db_session: AsyncSession,
    who: str,
    step: ResearchStep,
    status: IdeaStatus,
) -> None:
    researcher = await _who(team, db_session, who)
    idea, items = await _researched(api, team, db_session, researcher, status=status, step=step)
    client = await api(researcher)

    edit = await client.put(_url(idea, items[0]), {"answer": EDITED})
    clear_required = await client.delete(_url(idea, items[0]))
    clear_optional = await client.delete(_url(idea, items[2]))  # optional: still refused
    panel = ok(await client.get(f"/ideas/{idea.id}/research"))
    detail = ok(await client.get(f"/ideas/{idea.id}"))

    for response in (edit, clear_required, clear_optional):
        body = assert_problem(response, 409, "research_finished")
        assert "owner or an admin" in body["detail"]
    assert [item["answer"]["answer"] for item in panel["items"]] == [TEXT, TEXT, TEXT]
    assert panel["permissions"]["can_answer"] is False
    assert panel["permissions"]["can_hand_back"] is True  # still their assignment
    assert detail["permissions"]["can_answer_research"] is False
    assert detail["permissions"]["can_hand_back_research"] is True


@pytest.mark.parametrize("who", ["owner", "admin", "platform"])
async def test_past_research_the_owner_and_admins_keep_phase_8s_rule(
    api: AsUser, team: Team, db_session: AsyncSession, who: str
) -> None:
    """M1 as before: edit, never clear a required answer; an optional one clears."""
    idea, items = await _researched(api, team, db_session, team.member, status=S.EVALUATING)
    client = await api(getattr(team, who))

    edited = ok(await client.put(_url(idea, items[0]), {"answer": EDITED}))
    kept = await client.delete(_url(idea, items[0]))
    optional = ok(await client.delete(_url(idea, items[2])))
    panel = ok(await client.get(f"/ideas/{idea.id}/research"))

    assert edited["items"][0]["answer"]["answer"] == EDITED
    assert_problem(kept, 409, "research_answer_required")
    assert optional["items"][2]["answer"] is None
    assert panel["permissions"]["can_answer"] is True


@pytest.mark.parametrize("who", ["owner", "admin"])
async def test_an_owner_or_admin_who_is_also_the_researcher_keeps_their_own_rule(
    api: AsUser, team: Team, db_session: AsyncSession, who: str
) -> None:
    person = getattr(team, who)
    idea, items = await _researched(api, team, db_session, person, status=S.PROPOSAL)
    client = await api(person)

    ok(await client.put(_url(idea, items[0]), {"answer": EDITED}))
    assert_problem(await client.delete(_url(idea, items[0])), 409, "research_answer_required")
    assert ok(await client.get(f"/ideas/{idea.id}"))["permissions"]["can_answer_research"]


async def test_a_demoted_owner_who_researches_it_follows_the_researchers_rule(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    """The owner overlay counts only with a member or admin role (role matrix section 1):
    an owner who is a viewer now answers as the researcher, so only until Research ends."""
    idea, items = await _researched(api, team, db_session, team.owner, status=S.RESEARCH)
    await db_session.execute(
        update(ProjectMember)
        .where(ProjectMember.project_id == team.project.id, ProjectMember.user_id == team.owner.id)
        .values(role=ProjectRole.VIEWER)
    )
    await db_session.commit()
    client = await api(team.owner)
    ok(await client.put(_url(idea, items[0]), {"answer": EDITED}))
    await db_session.execute(update(Idea).where(Idea.id == idea.id).values(status=S.EVALUATING))
    await db_session.commit()

    assert_problem(
        await client.put(_url(idea, items[0]), {"answer": TEXT}), 409, "research_finished"
    )


async def test_moving_the_idea_on_ends_the_researchers_answering_and_back_restores_it(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea, items = await _researched(api, team, db_session, team.outsider, status=S.RESEARCH)
    guest = await api(team.outsider)
    owner = await api(team.owner)
    ok(await guest.put(_url(idea, items[0]), {"answer": EDITED}))

    ok(await owner.post(f"/ideas/{idea.id}/status", {"status": "evaluating"}))
    refused = await guest.put(_url(idea, items[0]), {"answer": TEXT})
    ok(await owner.post(f"/ideas/{idea.id}/status", {"status": "research"}))
    again = await guest.put(_url(idea, items[0]), {"answer": TEXT})

    assert_problem(refused, 409, "research_finished")
    assert again.status_code == 200, again.text


async def test_the_check_order_is_unchanged_around_the_new_409(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    """404 (an item that isn't one) -> 403 (not the researcher) -> 409 research_finished."""
    idea, items = await _researched(api, team, db_session, team.member, status=S.EVALUATING)
    member = await api(team.member)

    missing = await member.put(f"/ideas/{idea.id}/research/items/{idea.id}", {"answer": TEXT})
    other = await (await api(team.evaluators[0])).put(_url(idea, items[0]), {"answer": TEXT})
    finished = await member.put(_url(idea, items[0]), {"answer": TEXT})

    assert_problem(missing, 404, "not_found")
    assert_problem(other, 403, "forbidden")
    assert_problem(finished, 409, "research_finished")


@pytest.mark.parametrize("who", ["member", "guest"])
async def test_a_researchers_write_key_gets_the_same_answers(
    app: FastAPI, api: AsUser, team: Team, db_session: AsyncSession, who: str
) -> None:
    researcher = await _who(team, db_session, who)
    before, before_items = await _researched(api, team, db_session, researcher, status=S.RESEARCH)
    after, _ = await _researched(api, team, db_session, researcher, status=S.EVALUATING)
    secret = await make_key(db_session, researcher, scopes=["read", "write"])

    async with key_client(app, secret) as client:
        answered = await client.put(
            f"/api/v1{_url(before, before_items[0])}", json={"answer": EDITED}
        )
        refused = await client.put(
            f"/api/v1{_url(after, before_items[0])}", json={"answer": EDITED}
        )
        cleared = await client.delete(f"/api/v1{_url(after, before_items[0])}")

    assert answered.status_code == 200, answered.text
    assert_problem(refused, 409, "research_finished")
    assert_problem(cleared, 409, "research_finished")


async def test_the_owners_write_key_past_research_keeps_phase_8s_rule(
    app: FastAPI, api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea, items = await _researched(api, team, db_session, team.member, status=S.EVALUATING)
    secret = await make_key(db_session, team.owner, scopes=["read", "write"])

    async with key_client(app, secret) as client:
        edited = await client.put(f"/api/v1{_url(idea, items[0])}", json={"answer": EDITED})
        kept = await client.delete(f"/api/v1{_url(idea, items[0])}")

    assert edited.status_code == 200, edited.text
    assert_problem(kept, 409, "research_answer_required")


# --- D2: making a project private ends outside researchers' assignments ---------------------
async def _internal_with_researchers(api: AsUser, team: Team, db: AsyncSession) -> dict[str, Idea]:
    """An internal project with four researched ideas: an outsider (no role), a second
    outsider on two ideas, a viewer and a member (both with a role)."""
    await _make_internal(db, team.project)
    items = await set_step(db, team.project, ResearchStep.BEFORE_EVALUATION)
    second = await make_user(db, "Sam Second")
    owner = await api(team.owner)  # internal: the owner names anyone (c25)
    ideas: dict[str, Idea] = {}
    for name, person in (
        ("outsider", team.outsider),
        ("second", second),
        ("second_again", second),
        ("viewer", team.viewer),
        ("member", team.member),
    ):
        idea = await make_idea(db, team.project, status=S.RESEARCH, owner=team.owner)
        ok(await assign(owner, key_of(team.project, idea), person, DUE))
        await answer(db, idea, items[0], person)
        ideas[name] = idea
    return ideas


async def _researcher(db: AsyncSession, idea: Idea) -> Any:
    row = await db.get(Idea, idea.id, populate_existing=True)
    assert row is not None
    return row.researcher_id


async def _notifications(db: AsyncSession) -> int:
    return int(await db.scalar(select(func.count()).select_from(Notification)) or 0)


async def test_admins_see_how_many_outside_researchers_there_are(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    await _internal_with_researchers(api, team, db_session)

    for who in ("admin", "platform"):
        body = ok(await (await api(getattr(team, who))).get(f"/projects/{team.slug}"))
        assert body["outside_researcher_count"] == 2, who  # two people, three ideas
    for who in ("owner", "member", "viewer", "outsider"):
        body = ok(await (await api(getattr(team, who))).get(f"/projects/{team.slug}"))
        assert body["outside_researcher_count"] is None, who


async def test_the_count_is_zero_without_outsiders_and_skips_closed_and_other_projects(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION)
    idea = await make_idea(db_session, team.project, status=S.RESEARCH, owner=team.owner)
    ok(await assign(await api(team.owner), key_of(team.project, idea), team.member))

    body = ok(await (await api(team.admin)).get(f"/projects/{team.slug}"))

    assert body["outside_researcher_count"] == 0


async def test_making_a_project_private_ends_the_outside_researchers_assignments(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    ideas = await _internal_with_researchers(api, team, db_session)
    before = {name: await feed_types(db_session, idea) for name, idea in ideas.items()}
    notifications = await _notifications(db_session)
    admin = await api(team.admin)

    body = ok(await admin.patch(f"/projects/{team.slug}", {"visibility": "private"}))

    assert body["visibility"] == "private"
    assert body["outside_researcher_count"] == 0
    for name in ("outsider", "second", "second_again"):
        idea = ideas[name]
        row = await db_session.get(Idea, idea.id, populate_existing=True)
        assert row is not None
        assert (row.researcher_id, row.research_assigned_at) == (None, None), name
        assert row.research_due_at is not None, name  # the due date is the idea's
        entry = (await researcher_audit(db_session, idea))[-1]
        assert entry.details["reason"] == "made_private", name
        assert entry.actor_id == team.admin.id
        assert entry.details["to_user_id"] is None
        answers = await db_session.scalar(
            select(func.count()).where(ResearchAnswer.idea_id == idea.id)
        )
        assert answers == 1, name  # kept
        assert await feed_types(db_session, idea) == before[name], name  # no feed event
    for name in ("viewer", "member"):
        assert await _researcher(db_session, ideas[name]) is not None, name
    assert await _notifications(db_session) == notifications
    project_entry = await db_session.scalar(
        select(AuditLog)
        .where(AuditLog.action == "project.update", AuditLog.target_id == team.project.id)
        .order_by(AuditLog.created_at.desc())
        .limit(1)
    )
    assert project_entry is not None
    assert project_entry.details["fields"] == ["visibility"]
    assert project_entry.details["outside_researchers"] == 3  # the assignments it ended


async def test_a_former_outside_researcher_loses_the_idea_at_once(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    ideas = await _internal_with_researchers(api, team, db_session)
    outsider = await api(team.outsider)
    key = key_of(team.project, ideas["outsider"])
    assert ok(await outsider.get(f"/ideas/{key}"))["key"] == key  # internal: NMi

    ok(await (await api(team.admin)).patch(f"/projects/{team.slug}", {"visibility": "private"}))

    for path in (f"/ideas/{key}", f"/ideas/{key}/research", f"/ideas/{key}/activity"):
        assert_problem(await outsider.get(path), 404, "not_found")
    work = ok(await outsider.get("/me/work"))
    assert work["research_to_do"] == []


async def test_making_it_private_without_outsiders_ends_nothing(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    await _make_internal(db_session, team.project)
    await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION)
    idea = await make_idea(db_session, team.project, status=S.RESEARCH, owner=team.owner)
    ok(await assign(await api(team.owner), key_of(team.project, idea), team.member))

    ok(await (await api(team.admin)).patch(f"/projects/{team.slug}", {"visibility": "private"}))

    assert await _researcher(db_session, idea) == team.member.id
    assert [entry.details["reason"] for entry in await researcher_audit(db_session, idea)] == [
        "assigned"
    ]
    entry = await db_session.scalar(
        select(AuditLog)
        .where(AuditLog.action == "project.update", AuditLog.target_id == team.project.id)
        .order_by(AuditLog.created_at.desc())
        .limit(1)
    )
    assert entry is not None
    assert entry.details["outside_researchers"] == 0


@pytest.mark.parametrize(
    "change", [{"name": "Customer Innovation 2"}, {"visibility": "internal"}, {"archived": True}]
)
async def test_other_changes_end_nothing(
    api: AsUser, team: Team, db_session: AsyncSession, change: dict[str, Any]
) -> None:
    ideas = await _internal_with_researchers(api, team, db_session)

    ok(await (await api(team.admin)).patch(f"/projects/{team.slug}", change))

    assert await _researcher(db_session, ideas["outsider"]) == team.outsider.id


async def test_private_to_internal_keeps_a_guest_and_makes_them_nmi(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION)
    idea = await make_idea(db_session, team.project, status=S.RESEARCH, owner=team.owner)
    ok(await assign(await api(team.admin), key_of(team.project, idea), team.outsider))
    assert (
        ok(await (await api(team.admin)).get(f"/projects/{team.slug}"))["outside_researcher_count"]
        == 1
    )

    ok(await (await api(team.admin)).patch(f"/projects/{team.slug}", {"visibility": "internal"}))

    assert await _researcher(db_session, idea) == team.outsider.id
    body = ok(await (await api(team.outsider)).get(f"/ideas/{idea.id}"))
    assert body["permissions"]["can_view_project"] is True


async def test_only_project_admins_change_visibility(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    ideas = await _internal_with_researchers(api, team, db_session)

    refused = await (await api(team.owner)).patch(
        f"/projects/{team.slug}", {"visibility": "private"}
    )

    assert_problem(refused, 403, "forbidden")
    assert await _researcher(db_session, ideas["outsider"]) == team.outsider.id


# --- D5 (review N1): DueAt returns UTC ------------------------------------------------------
def test_due_at_returns_utc_at_the_schema_level() -> None:
    from pydantic import TypeAdapter

    when = datetime.now(UTC).replace(microsecond=0) + timedelta(days=3)
    local = when.astimezone(datetime.now().astimezone().tzinfo).isoformat()
    shifted = (when + timedelta(hours=5, minutes=30)).replace(tzinfo=None).isoformat() + "+05:30"

    for text in (local, shifted, when.isoformat()):
        parsed = TypeAdapter(DueAt).validate_python(text)
        assert parsed == when
        assert parsed.utcoffset() == timedelta(0)
        assert parsed.tzinfo is UTC


# --- D4: an explicitly assigned owner stays the researcher when the owner changes ---------
async def test_an_owner_asked_by_name_stays_the_researcher_when_the_idea_changes_owner(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION)
    idea = await make_idea(db_session, team.project, status=S.RESEARCH, owner=team.owner)
    implicit = await make_idea(db_session, team.project, status=S.RESEARCH, owner=team.owner)
    admin = await api(team.admin)
    ok(await assign(admin, key_of(team.project, idea), team.owner, DUE))  # asked by name

    for target in (idea, implicit):
        ok(await admin.put(f"/ideas/{target.id}/owner", {"user_id": str(team.member.id)}))

    assert await _researcher(db_session, idea) == team.owner.id
    panel = ok(await (await api(team.owner)).get(f"/ideas/{idea.id}/research"))
    assert panel["assignment"]["researcher"]["id"] == str(team.owner.id)
    assert panel["permissions"]["can_answer"] is True  # +Rsr, not the owner overlay now
    # Nobody assigned: the new owner does the research.
    assert await _researcher(db_session, implicit) is None
    new_owner = ok(await (await api(team.member)).get(f"/ideas/{implicit.id}/research"))
    assert new_owner["permissions"]["can_answer"] is True
