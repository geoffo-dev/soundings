"""Phase 8b code review fixes for the research assignment (contract-phase8b section 3).

* N1: a due date with any offset is stored, answered and put in the feed in UTC.
* N2: who may assign is checked before the named person's user row is locked, so someone
  who may only view the idea never takes that lock.
* N3: an admin who is the researcher and clears it with ``PUT`` hands it back (audit
  ``handed_back``, feed ``handed_back``), as ``DELETE`` says.
* L1 (lead decision D2: making a project private ends outside researchers' assignments,
  tests/research/test_lead_decisions.py): its ``project.update`` audit entry records how
  many assignments that ended.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import AuditLog
from app.models.enums import ProjectVisibility, ResearchStep
from app.models.idea import Idea
from app.models.project import Project
from app.services import research_assignment
from tests.factories import make_idea
from tests.research.conftest import (
    AsUser,
    Team,
    assert_problem,
    assign,
    key_of,
    ok,
    researcher_audit,
    set_step,
)


async def _idea(db: AsyncSession, team: Team) -> tuple[Idea, str]:
    await set_step(db, team.project, ResearchStep.BEFORE_EVALUATION)
    idea = await make_idea(db, team.project, owner=team.owner)
    return idea, key_of(team.project, idea)


async def test_a_due_date_with_any_offset_comes_back_in_utc(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    _, key = await _idea(db_session, team)
    owner = await api(team.owner)

    body = ok(await assign(owner, key, team.member, "2026-12-11T10:00:00+05:30"))
    again = ok(await owner.get(f"/ideas/{key}/research"))
    feed = ok(await owner.get(f"/ideas/{key}/activity"))["items"]

    expected = datetime(2026, 12, 11, 4, 30, tzinfo=UTC)
    for value in (
        body["assignment"]["due_at"],
        again["assignment"]["due_at"],
        next(e for e in feed if e["type"] == "research_due_date_changed")["to_due_at"],
    ):
        parsed = datetime.fromisoformat(value)
        assert parsed == expected
        assert parsed.utcoffset() == timedelta(0)


async def test_the_rule_comes_before_the_named_persons_lock(
    api: AsUser, team: Team, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, key = await _idea(db_session, team)
    looked_up: list[object] = []
    original = research_assignment._named

    async def spy(*args: object, **kwargs: object) -> object:
        looked_up.append(args)
        return await original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(research_assignment, "_named", spy)

    refused = await assign(await api(team.member), key, team.evaluators[0])
    assert_problem(refused, 403, "forbidden")
    assert looked_up == []

    ok(await assign(await api(team.owner), key, team.evaluators[0]))
    assert len(looked_up) == 1


async def test_an_admin_researcher_clearing_it_with_put_hands_it_back(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea, key = await _idea(db_session, team)
    admin = await api(team.admin)
    ok(await assign(await api(team.owner), key, team.admin))

    ok(await assign(admin, key, None))

    entry = (await researcher_audit(db_session, idea))[-1]
    assert entry.details["reason"] == "handed_back"
    feed = ok(await admin.get(f"/ideas/{key}/activity"))["items"]
    assert feed[0]["type"] == "researcher_changed"
    assert feed[0]["handed_back"] is True
    # Someone else's removal by PUT stays "removed".
    ok(await assign(admin, key, team.member))
    ok(await assign(admin, key, None))
    assert (await researcher_audit(db_session, idea))[-1].details["reason"] == "removed"


async def test_making_a_project_private_counts_the_assignments_it_ends(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    await db_session.execute(
        update(Project)
        .where(Project.id == team.project.id)
        .values(visibility=ProjectVisibility.INTERNAL)
    )
    await db_session.commit()
    _, key = await _idea(db_session, team)
    other = await make_idea(db_session, team.project, owner=team.owner)
    owner = await api(team.owner)
    ok(await assign(owner, key, team.outsider))  # internal: the owner names anyone
    ok(await assign(owner, key_of(team.project, other), team.member))
    admin = await api(team.admin)

    ok(await admin.patch(f"/projects/{team.slug}", {"visibility": "private"}))

    entry = await db_session.scalar(
        select(AuditLog)
        .where(AuditLog.action == "project.update", AuditLog.target_id == team.project.id)
        .order_by(AuditLog.created_at.desc())
        .limit(1)
    )
    assert entry is not None
    assert entry.details["fields"] == ["visibility"]
    assert entry.details["outside_researchers"] == 1
    # Lead decision D2: the outsider's assignment ended with the change, so the idea is
    # gone for them; the member's stays.
    assert_problem(await (await api(team.outsider)).get(f"/ideas/{key}"), 404, "not_found")
    kept = await db_session.get(Idea, other.id, populate_existing=True)
    assert kept is not None
    assert kept.researcher_id == team.member.id
