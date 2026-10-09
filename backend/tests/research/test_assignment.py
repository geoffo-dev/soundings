"""Phase 8b: assigning the research (contract-phase8b sections 3, 14 and 17).

``set_research_assignment`` and ``remove_researcher`` through the API: who may assign
(c5, c25), who may be named (c23), the check order, idempotency, the feed events, the
watch, the audit entries and their ``reason``, API keys (assigning is session only), and
the automatic clears (closing, the step off, deactivation); the archived project only
suspends the assignment.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi import FastAPI
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import utcnow
from app.models.enums import (
    HoldReason,
    IdeaStatus,
    NotificationType,
    ProjectRole,
    ProjectVisibility,
    ResearchStep,
)
from app.models.idea import Idea, IdeaWatcher
from app.models.notification import Notification
from app.models.project import Project
from app.models.research import ResearchAnswer
from app.models.user import User
from tests.api_keys.helpers import key_client, make_key, problem
from tests.factories import add_evaluator, make_idea, make_user
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

DUE = "2026-12-11T17:00:00+00:00"


async def _idea(db: AsyncSession, team: Team, **kwargs: object) -> tuple[Idea, str]:
    await set_step(db, team.project, ResearchStep.BEFORE_EVALUATION)
    idea = await make_idea(db, team.project, owner=team.owner, **kwargs)  # type: ignore[arg-type]
    return idea, key_of(team.project, idea)


async def _fresh(db: AsyncSession, idea: Idea) -> Idea:
    row = await db.get(Idea, idea.id, populate_existing=True)
    assert row is not None
    return row


async def _notes(db: AsyncSession, user: User) -> list[Notification]:
    return list(
        await db.scalars(
            select(Notification)
            .where(
                Notification.user_id == user.id,
                Notification.type == NotificationType.RESEARCHER_ASSIGNED,
            )
            .execution_options(populate_existing=True)
        )
    )


# --- Assigning ---------------------------------------------------------------------------
async def test_the_owner_asks_a_member(api: AsUser, team: Team, db_session: AsyncSession) -> None:
    idea, key = await _idea(db_session, team)
    owner = await api(team.owner)

    body = ok(await assign(owner, key, team.member, DUE))

    assignment = body["assignment"]
    assert assignment["researcher"]["id"] == str(team.member.id)
    assert assignment["researcher_in_project"] is True
    assert assignment["assigned_at"] is not None
    assert assignment["due_at"].startswith("2026-12-11T17:00:00")
    assert assignment["overdue"] is False
    assert body["permissions"]["can_assign"] is True
    assert body["permissions"]["can_hand_back"] is False
    assert body["gate_status_label"] == "Evaluating"  # the status the gate guards
    row = await _fresh(db_session, idea)
    assert row.researcher_id == team.member.id
    assert row.research_assigned_at is not None
    assert await feed_types(db_session, idea) == ["researcher_changed", "research_due_date_changed"]
    (entry,) = await researcher_audit(db_session, idea)
    assert entry.actor_id == team.owner.id
    assert entry.project_id == team.project.id
    assert entry.details == {
        "auth": "session",
        "auth_method": "dev_login",
        "from_user_id": None,
        "to_user_id": str(team.member.id),
        "reason": "assigned",
        "outside_project": False,
        "rule": "idea.assign_researcher",
    }
    watching = await db_session.scalar(
        select(IdeaWatcher).where(
            IdeaWatcher.idea_id == idea.id, IdeaWatcher.user_id == team.member.id
        )
    )
    assert watching is not None
    (note,) = await _notes(db_session, team.member)
    assert note.actor_id == team.owner.id
    row = await _fresh(db_session, idea)
    assert row.research_assigned_at is not None
    # Review L2: the payload names the assignment it asks about.
    assert note.payload == {
        "due_at": "2026-12-11T17:00:00+00:00",
        "assigned_at": row.research_assigned_at.isoformat(),
    }
    # The idea shows it too.
    detail = ok(await owner.get(f"/ideas/{key}"))
    assert detail["researcher"]["id"] == str(team.member.id)
    assert detail["research_due_at"].startswith("2026-12-11T17:00:00")
    assert detail["permissions"]["can_assign_researcher"] is True
    assert detail["permissions"]["can_assign_outside_researcher"] is False  # private
    assert detail["permissions"]["can_view_project"] is True


async def test_the_same_state_again_changes_nothing(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea, key = await _idea(db_session, team)
    owner = await api(team.owner)
    ok(await assign(owner, key, team.member, DUE))

    ok(await assign(owner, key, team.member, "2026-12-11T18:00:00+01:00"))  # the same moment

    assert await feed_types(db_session, idea) == ["researcher_changed", "research_due_date_changed"]
    assert len(await researcher_audit(db_session, idea)) == 1
    assert len(await _notes(db_session, team.member)) == 1


async def test_a_due_date_alone_is_a_feed_event_without_audit(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea, key = await _idea(db_session, team)
    owner = await api(team.owner)

    body = ok(await assign(owner, key, None, DUE))
    ok(await assign(owner, key, None, None))

    assert body["assignment"]["researcher"] is None
    assert await feed_types(db_session, idea) == [
        "research_due_date_changed",
        "research_due_date_changed",
    ]
    assert await researcher_audit(db_session, idea) == []
    assert (await _fresh(db_session, idea)).research_due_at is None


async def test_reassigning_tells_only_the_new_researcher(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea, key = await _idea(db_session, team)
    owner = await api(team.owner)
    ok(await assign(owner, key, team.member, DUE))

    ok(await assign(owner, key, team.evaluators[0], DUE))

    assert len(await _notes(db_session, team.member)) == 1
    assert len(await _notes(db_session, team.evaluators[0])) == 1
    _, second = await researcher_audit(db_session, idea)
    assert second.details["from_user_id"] == str(team.member.id)
    assert second.details["to_user_id"] == str(team.evaluators[0].id)


async def test_asking_yourself_notifies_nobody(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    """The owner may be named explicitly (amara on GREEN-6); the actor is never told."""
    _, key = await _idea(db_session, team)

    body = ok(await assign(await api(team.owner), key, team.owner))

    assert body["assignment"]["researcher"]["id"] == str(team.owner.id)
    assert await _notes(db_session, team.owner) == []


@pytest.mark.parametrize(
    ("who", "status", "code"),
    [
        ("owner", 200, None),
        ("admin", 200, None),
        ("platform", 200, None),
        ("member", 403, "forbidden"),
        ("viewer", 403, "forbidden"),
        ("evaluator", 403, "forbidden"),
        ("outsider", 404, "not_found"),
    ],
)
async def test_who_may_assign(
    api: AsUser, team: Team, db_session: AsyncSession, who: str, status: int, code: str | None
) -> None:
    idea, key = await _idea(db_session, team)
    await add_evaluator(db_session, idea, team.evaluators[0])
    user = {
        "owner": team.owner,
        "admin": team.admin,
        "platform": team.platform,
        "member": team.member,
        "viewer": team.viewer,
        "evaluator": team.evaluators[0],
        "outsider": team.outsider,
    }[who]

    response = await assign(await api(user), key, team.evaluators[1], DUE)

    if code is None:
        assert response.status_code == status, response.text
    else:
        assert_problem(response, status, code)


async def test_a_demoted_owner_and_the_researcher_cant_assign(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea, key = await _idea(db_session, team)
    ok(await assign(await api(team.owner), key, team.member))
    researcher = await api(team.member)

    assert_problem(await assign(researcher, key, team.evaluators[0]), 403, "forbidden")
    body = ok(await researcher.get(f"/ideas/{key}/research"))
    assert body["permissions"]["can_assign"] is False
    assert body["permissions"]["can_hand_back"] is True
    assert body["permissions"]["can_answer"] is True
    assert body["permissions"]["can_override"] is False

    await db_session.execute(
        update(Idea).where(Idea.id == idea.id).values(researcher_id=None, research_assigned_at=None)
    )
    from tests.factories import add_member

    await db_session.commit()
    viewer = await make_user(db_session, "Dee Demoted")
    await add_member(db_session, team.project, viewer, ProjectRole.VIEWER)
    await db_session.execute(update(Idea).where(Idea.id == idea.id).values(owner_id=viewer.id))
    await db_session.commit()
    assert_problem(await assign(await api(viewer), key, team.member), 403, "forbidden")


async def test_in_a_private_project_only_admins_name_an_outsider(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    """c25 (the product owner's answer to review S1 a)."""
    idea, key = await _idea(db_session, team)

    assert_problem(
        await assign(await api(team.owner), key, team.outsider),
        403,
        "outside_researcher_needs_admin",
    )
    body = ok(await assign(await api(team.admin), key, team.outsider))

    assert body["assignment"]["researcher_in_project"] is False
    assert body["permissions"]["can_assign_outside_researcher"] is True
    (entry,) = await researcher_audit(db_session, idea)
    assert entry.details["outside_project"] is True
    # c25 is about naming: the owner keeps the outsider an admin named and changes only
    # the due date (the dialog sends the same researcher again).
    kept = ok(await assign(await api(team.owner), key, team.outsider, DUE))
    assert kept["assignment"]["researcher"]["id"] == str(team.outsider.id)
    assert kept["assignment"]["due_at"] is not None
    # The owner may still name anyone with a role, themselves included, and remove the
    # outsider an admin named.
    ok(await assign(await api(team.owner), key, team.viewer))
    ok(await assign(await api(team.owner), key, team.owner))


async def test_in_an_internal_project_the_owner_names_anyone(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    await db_session.execute(
        update(Project)
        .where(Project.id == team.project.id)
        .values(visibility=ProjectVisibility.INTERNAL)
    )
    await db_session.commit()
    _, key = await _idea(db_session, team)
    owner = await api(team.owner)

    assert ok(await owner.get(f"/ideas/{key}"))["permissions"]["can_assign_outside_researcher"]
    body = ok(await assign(owner, key, team.outsider))

    assert body["assignment"]["researcher_in_project"] is False


@pytest.mark.parametrize("kind", ["service", "break_glass", "deactivated", "unknown"])
async def test_only_an_active_person_may_be_named(
    api: AsUser, team: Team, db_session: AsyncSession, kind: str
) -> None:
    """c23: 422 for an admin; the owner naming someone without a role hears c25's 403
    first, a service account with a role 422."""
    idea, key = await _idea(db_session, team)
    if kind == "unknown":
        named = User(id=__import__("uuid").uuid4(), email="x@example.com", display_name="X")
    else:
        named = await make_user(
            db_session,
            f"Not {kind}",
            service_account=kind == "service",
            active=kind != "deactivated",
        )
        if kind == "break_glass":
            await db_session.execute(
                update(User).where(User.id == named.id).values(is_break_glass=True)
            )
            await db_session.commit()

    assert_problem(await assign(await api(team.admin), key, named), 422, "researcher_not_eligible")
    assert_problem(
        await assign(await api(team.owner), key, named), 403, "outside_researcher_needs_admin"
    )
    if kind == "service":
        from tests.factories import add_member

        await add_member(db_session, team.project, named, ProjectRole.MEMBER)
        assert_problem(
            await assign(await api(team.owner), key, named), 422, "researcher_not_eligible"
        )
    assert (await _fresh(db_session, idea)).researcher_id is None


@pytest.mark.parametrize("status", [IdeaStatus.NEW, IdeaStatus.RESEARCH])
async def test_assigning_is_allowed_in_research_and_before_it(
    api: AsUser, team: Team, db_session: AsyncSession, status: IdeaStatus
) -> None:
    """Past Research nobody new is asked (409 ``research_finished``, adversarial check L2:
    tests/research/test_assignment_past_research.py)."""
    _, key = await _idea(db_session, team, status=status)

    ok(await assign(await api(team.owner), key, team.member, DUE))


@pytest.mark.parametrize("state", ["archived", "closed", "step_off", "held"])
async def test_the_conflicts(api: AsUser, team: Team, db_session: AsyncSession, state: str) -> None:
    idea, key = await _idea(db_session, team)
    code = {
        "archived": "project_archived",
        "closed": "idea_closed",
        "step_off": "research_step_off",
        "held": "awaiting_moderation",
    }[state]
    if state == "archived":
        await db_session.execute(
            update(Project).where(Project.id == team.project.id).values(archived_at=utcnow())
        )
    elif state == "closed":
        await db_session.execute(
            update(Idea)
            .where(Idea.id == idea.id)
            .values(status=IdeaStatus.CLOSED, resolution="parked")
        )
    elif state == "step_off":
        await db_session.execute(
            update(Project)
            .where(Project.id == team.project.id)
            .values(research_step=ResearchStep.OFF)
        )
    else:
        await db_session.execute(
            update(Idea).where(Idea.id == idea.id).values(held_for=HoldReason.MODERATION)
        )
    await db_session.commit()
    admin = await api(team.admin)

    assert_problem(await assign(admin, key, team.member), 409, code)
    if state != "held":  # a held idea's removal is a write on it too
        assert_problem(await admin.delete(f"/ideas/{key}/research/assignment"), 409, code)


async def test_unknown_fields_and_bad_dates_are_422(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    _, key = await _idea(db_session, team)
    owner = await api(team.owner)

    assert_problem(
        await owner.put(
            f"/ideas/{key}/research/assignment",
            {"researcher_id": None, "due_at": None, "extra": 1},
        ),
        422,
        "validation_error",
    )
    assert_problem(
        await owner.put(f"/ideas/{key}/research/assignment", {"researcher_id": None}),
        422,
        "validation_error",
    )
    assert_problem(
        await owner.put(
            f"/ideas/{key}/research/assignment",
            {"researcher_id": None, "due_at": "2026-12-11T17:00:00"},
        ),
        422,
        "validation_error",
    )


# --- API keys -----------------------------------------------------------------------------
@pytest.mark.parametrize(
    "scopes", [("read",), ("write",), ("read", "write", "evaluate", "mcp"), ("evaluate",)]
)
async def test_every_key_is_refused_on_assigning(
    app: FastAPI, team: Team, db_session: AsyncSession, scopes: tuple[str, ...]
) -> None:
    """Review M3: session only, before the route runs (it reveals nothing)."""
    idea, key = await _idea(db_session, team)
    secret = await make_key(db_session, team.admin, scopes=scopes)
    async with key_client(app, secret) as http:
        response = await http.put(
            f"/api/v1/ideas/{key}/research/assignment",
            json={"researcher_id": str(team.member.id), "due_at": None},
        )
        hidden = await http.put(
            "/api/v1/ideas/NOPE-1/research/assignment",
            json={"researcher_id": None, "due_at": None},
        )

    problem(response, 403, "insufficient_scope")
    problem(hidden, 403, "insufficient_scope")
    assert (await _fresh(db_session, idea)).researcher_id is None


async def test_a_write_key_may_remove_or_hand_back(
    app: FastAPI, api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea, key = await _idea(db_session, team)
    ok(await assign(await api(team.owner), key, team.member))
    read_only = await make_key(db_session, team.member, scopes=("read",))
    write = await make_key(db_session, team.member, scopes=("write",))

    async with key_client(app, read_only) as http:
        refused = await http.delete(f"/api/v1/ideas/{key}/research/assignment")
    async with key_client(app, write) as http:
        handed = await http.delete(f"/api/v1/ideas/{key}/research/assignment")

    problem(refused, 403, "insufficient_scope")
    assert handed.status_code == 204, handed.text
    assert (await _fresh(db_session, idea)).researcher_id is None
    assert (await researcher_audit(db_session, idea))[-1].details["reason"] == "handed_back"


# --- Removing and handing back -------------------------------------------------------------
async def test_the_owner_removes_the_researcher(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea, key = await _idea(db_session, team)
    owner = await api(team.owner)
    ok(await assign(owner, key, team.member, DUE))

    response = await owner.delete(f"/ideas/{key}/research/assignment")

    assert response.status_code == 204
    row = await _fresh(db_session, idea)
    assert (row.researcher_id, row.research_assigned_at) == (None, None)
    assert row.research_due_at is not None  # the due date is kept
    feed = ok(await owner.get(f"/ideas/{key}/activity"))["items"]
    assert feed[0]["type"] == "researcher_changed"
    assert feed[0]["from_researcher"]["id"] == str(team.member.id)
    assert feed[0]["to_researcher"] is None
    assert feed[0]["handed_back"] is False
    entry = (await researcher_audit(db_session, idea))[-1]
    assert entry.details["reason"] == "removed"
    assert entry.details["rule"] == "idea.assign_researcher"
    # Again: 204, nothing new.
    assert (await owner.delete(f"/ideas/{key}/research/assignment")).status_code == 204
    assert len(await researcher_audit(db_session, idea)) == 2
    assert (await feed_types(db_session, idea)).count("researcher_changed") == 2


async def test_the_researcher_hands_it_back(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea, key = await _idea(db_session, team)
    ok(await assign(await api(team.admin), key, team.outsider, DUE))
    guest = await api(team.outsider)

    response = await guest.delete(f"/ideas/{key}/research/assignment")

    assert response.status_code == 204
    entry = (await researcher_audit(db_session, idea))[-1]
    assert entry.actor_id == team.outsider.id
    assert entry.details["reason"] == "handed_back"
    assert entry.details["rule"] == "idea.release_researcher"
    feed = ok(await (await api(team.owner)).get(f"/ideas/{key}/activity"))["items"]
    assert feed[0]["handed_back"] is True
    # Their access ended with the request.
    assert_problem(await guest.get(f"/ideas/{key}"), 404, "not_found")
    assert_problem(await guest.delete(f"/ideas/{key}/research/assignment"), 404, "not_found")


async def test_others_cant_remove(api: AsUser, team: Team, db_session: AsyncSession) -> None:
    _, key = await _idea(db_session, team)
    ok(await assign(await api(team.owner), key, team.evaluators[0]))

    assert_problem(
        await (await api(team.member)).delete(f"/ideas/{key}/research/assignment"),
        403,
        "forbidden",
    )
    assert_problem(
        await (await api(team.viewer)).delete(f"/ideas/{key}/research/assignment"),
        403,
        "forbidden",
    )
    assert_problem(
        await (await api(team.outsider)).delete(f"/ideas/{key}/research/assignment"),
        404,
        "not_found",
    )


# --- What ends an assignment by itself ----------------------------------------------------
async def test_closing_clears_it_and_reopening_doesnt_bring_it_back(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    """Review S8 (the product owner accepted it): audited ``closed``, no feed event or
    notification, the due date kept."""
    idea, key = await _idea(db_session, team)
    owner = await api(team.owner)
    ok(await assign(owner, key, team.member, DUE))
    before = await feed_types(db_session, idea)

    ok(await owner.post(f"/ideas/{key}/status", {"status": "closed", "resolution": "parked"}))

    row = await _fresh(db_session, idea)
    assert (row.researcher_id, row.research_assigned_at) == (None, None)
    assert row.research_due_at is not None
    entry = (await researcher_audit(db_session, idea))[-1]
    assert entry.details["reason"] == "closed"
    assert entry.actor_id == team.owner.id
    assert await feed_types(db_session, idea) == [*before, "status_changed"]

    ok(await owner.post(f"/ideas/{key}/status", {"status": "new"}))
    assert (await _fresh(db_session, idea)).researcher_id is None


async def test_turning_the_step_off_clears_every_assignment_moving_it_keeps_them(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    first, first_key = await _idea(db_session, team)
    second = await make_idea(db_session, team.project, owner=team.owner)
    owner = await api(team.owner)
    ok(await assign(owner, first_key, team.member, DUE))
    ok(await assign(owner, key_of(team.project, second), team.evaluators[0]))
    admin = await api(team.admin)
    settings = ok(await admin.get(f"/projects/{team.slug}/research"))
    items = [
        {
            "id": item["id"],
            "title": item["title"],
            "hint": item["hint"],
            "required": item["required"],
        }
        for item in settings["items"]
    ]

    ok(
        await admin.put(
            f"/projects/{team.slug}/research", {"step": "before_proposal", "items": items}
        )
    )
    assert (await _fresh(db_session, first)).researcher_id == team.member.id

    ok(await admin.put(f"/projects/{team.slug}/research", {"step": "off", "items": []}))

    for idea in (first, second):
        row = await _fresh(db_session, idea)
        assert row.researcher_id is None
        assert (await researcher_audit(db_session, idea))[-1].details["reason"] == "step_off"
    assert (await _fresh(db_session, first)).research_due_at is not None
    assert "researcher_changed" not in (await feed_types(db_session, first))[1:]


async def test_deactivating_the_researcher_clears_it_and_keeps_their_answers(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    items = await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION)
    idea = await make_idea(db_session, team.project, owner=team.owner)
    key = key_of(team.project, idea)
    ok(await assign(await api(team.admin), key, team.outsider, DUE))
    await answer(db_session, idea, items[0], team.outsider)

    ok(
        await (await api(team.platform)).patch(
            f"/admin/users/{team.outsider.id}", {"is_active": False}
        )
    )

    row = await _fresh(db_session, idea)
    assert row.researcher_id is None
    assert row.research_due_at is not None
    entry = (await researcher_audit(db_session, idea))[-1]
    assert entry.details["reason"] == "deactivated"
    assert entry.actor_id == team.platform.id
    kept = await db_session.scalar(select(ResearchAnswer).where(ResearchAnswer.idea_id == idea.id))
    assert kept is not None
    assert kept.answered_by_id == team.outsider.id


async def test_an_archived_project_suspends_the_assignment(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea, key = await _idea(db_session, team)
    ok(await assign(await api(team.admin), key, team.outsider))
    guest = await api(team.outsider)
    ok(await guest.get(f"/ideas/{key}"))

    await db_session.execute(
        update(Project).where(Project.id == team.project.id).values(archived_at=utcnow())
    )
    await db_session.commit()
    assert_problem(await guest.get(f"/ideas/{key}"), 404, "not_found")
    assert_problem(await guest.delete(f"/ideas/{key}/research/assignment"), 404, "not_found")
    assert (await _fresh(db_session, idea)).researcher_id == team.outsider.id

    await db_session.execute(
        update(Project).where(Project.id == team.project.id).values(archived_at=None)
    )
    await db_session.commit()
    ok(await guest.get(f"/ideas/{key}"))


async def test_overdue_follows_the_research_still_to_do(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    items = await set_step(db_session, team.project, ResearchStep.BEFORE_EVALUATION)
    idea = await make_idea(db_session, team.project, owner=team.owner)
    key = key_of(team.project, idea)
    owner = await api(team.owner)
    past = (utcnow() - timedelta(days=1)).isoformat()

    assert ok(await assign(owner, key, team.member, past))["assignment"]["overdue"] is True

    for item in items:
        if item.required:
            await answer(db_session, idea, item, team.member)
    body = ok(await owner.get(f"/ideas/{key}/research"))
    assert body["assignment"]["overdue"] is False
