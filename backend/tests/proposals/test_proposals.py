"""Starting a proposal and saving its sections (contract-phase4 3.1 and 3.2; role
matrix section E): permissions for every column, c7, the status move with its event,
notification and audit entry, and optimistic concurrency per section."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import ActivityEvent, AuditLog
from app.models.enums import HoldReason, IdeaStatus, NotificationType, ProjectRole
from app.models.idea import Idea, IdeaWatcher
from app.models.notification import Notification
from app.models.project import Project, ProjectMember
from tests.factories import make_idea
from tests.proposals.conftest import (
    SECTION_KEYS,
    AsUser,
    Team,
    assert_problem,
    idea_key,
    ok,
    proposal_url,
    start,
)


def section_url(key: str, section: str) -> str:
    return f"{proposal_url(key)}/sections/{section}"


def sections(view: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {section["key"]: section for section in view["proposal"]["sections"]}


# --- Reading and permissions ---------------------------------------------------------
async def test_before_a_proposal_the_tab_says_who_may_start_one(
    api: AsUser, team: Team, key: str
) -> None:
    owner = ok(await (await api(team.owner)).get(proposal_url(key)))
    member = ok(await (await api(team.member)).get(proposal_url(key)))
    viewer = ok(await (await api(team.viewer)).get(proposal_url(key)))

    assert owner == {
        "proposal": None,
        "permissions": {
            "can_create": True,
            "can_edit": False,
            "can_comment": True,
            "can_export": False,
        },
    }
    assert member["permissions"] == {
        "can_create": False,
        "can_edit": False,
        "can_comment": True,
        "can_export": False,
    }
    assert viewer["permissions"]["can_comment"] is False
    assert_problem(await (await api(team.outsider)).get(proposal_url(key)), 404, "not_found")


async def test_starting_creates_the_fixed_template_in_order(
    api: AsUser, team: Team, key: str
) -> None:
    view = await start(await api(team.owner), key)

    proposal = view["proposal"]
    assert [section["key"] for section in proposal["sections"]] == SECTION_KEYS
    assert [section["title"] for section in proposal["sections"]] == [
        "Summary",
        "Problem",
        "Solution",
        "Market & users",
        "Cost & effort",
        "Benefits / revenue",
        "Risks",
        "Next steps / the ask",
    ]
    by_key = sections(view)
    assert by_key["summary"]["body_md"] == "Let customers refund without calling us."
    assert all(by_key[k]["body_md"] == "" for k in SECTION_KEYS[1:])
    assert {section["version"] for section in proposal["sections"]} == {1}
    assert all(section["updated_by"] is None for section in proposal["sections"])
    assert all(section["prompt"] for section in proposal["sections"])
    assert proposal["idea"]["key"] == key
    assert proposal["idea"]["status"] == "proposal"
    assert proposal["created_by"]["display_name"] == "Olive Owner"
    assert view["permissions"] == {
        "can_create": False,
        "can_edit": True,
        "can_comment": True,
        "can_export": True,
    }


async def test_starting_moves_a_shortlisted_idea_to_proposal_like_a_status_change(
    api: AsUser, team: Team, idea: Idea, key: str, db_session: AsyncSession
) -> None:
    db_session.add(IdeaWatcher(idea_id=idea.id, user_id=team.member.id))
    await db_session.commit()

    await start(await api(team.owner), key)

    moved = await db_session.get(Idea, idea.id, populate_existing=True)
    assert moved is not None
    assert moved.status is IdeaStatus.PROPOSAL
    events = list(
        await db_session.scalars(select(ActivityEvent).where(ActivityEvent.idea_id == idea.id))
    )
    assert [(e.type, e.payload["to_status"]) for e in events] == [("status_changed", "proposal")]
    assert events[0].actor_id == team.owner.id
    audit = list(await db_session.scalars(select(AuditLog).where(AuditLog.target_id == idea.id)))
    assert [(a.action, a.details["to_status"]) for a in audit] == [
        ("idea.status_change", "proposal")
    ]
    notified = list(
        await db_session.scalars(select(Notification).where(Notification.idea_id == idea.id))
    )
    assert [(n.user_id, n.type) for n in notified] == [
        (team.member.id, NotificationType.STATUS_CHANGED)
    ]
    # The board shows it in Proposal.
    board = ok(await (await api(team.member)).get(f"/ideas/{key}"))
    assert board["status"] == "proposal"


async def test_an_idea_already_in_proposal_just_gets_its_proposal(
    api: AsUser, team: Team, idea: Idea, key: str, db_session: AsyncSession
) -> None:
    await db_session.execute(
        update(Idea).where(Idea.id == idea.id).values(status=IdeaStatus.PROPOSAL)
    )
    await db_session.commit()

    await start(await api(team.owner), key)

    events = await db_session.scalars(
        select(ActivityEvent.type).where(ActivityEvent.idea_id == idea.id)
    )
    assert list(events) == []


@pytest.mark.parametrize(
    ("who", "status", "code"),
    [
        ("member", 403, "forbidden"),
        ("viewer", 403, "forbidden"),
        ("outsider", 404, "not_found"),
        ("evaluator", 403, "forbidden"),
    ],
)
async def test_only_the_owner_and_admins_start_a_proposal(
    api: AsUser, team: Team, key: str, who: str, status: int, code: str
) -> None:
    user = team.evaluators[0] if who == "evaluator" else getattr(team, who)
    assert_problem(await (await api(user)).post(proposal_url(key)), status, code)


@pytest.mark.parametrize("who", ["admin", "platform"])
async def test_project_and_platform_admins_start_one_too(
    api: AsUser, team: Team, key: str, who: str
) -> None:
    view = await start(await api(getattr(team, who)), key)
    assert view["permissions"]["can_edit"] is True


async def test_an_owner_demoted_to_viewer_can_no_longer_write(
    api: AsUser, team: Team, key: str, db_session: AsyncSession
) -> None:
    owner = await api(team.owner)
    await start(owner, key)
    await db_session.execute(
        update(ProjectMember)
        .where(ProjectMember.user_id == team.owner.id)
        .values(role=ProjectRole.VIEWER)
    )
    await db_session.commit()

    view = ok(await owner.get(proposal_url(key)))
    assert view["permissions"] == {
        "can_create": False,
        "can_edit": False,
        "can_comment": False,
        "can_export": True,
    }
    response = await owner.put(section_url(key, "problem"), {"body_md": "x", "base_version": 1})
    assert_problem(response, 403, "forbidden")


@pytest.mark.parametrize("status", [IdeaStatus.NEW, IdeaStatus.EVALUATING, IdeaStatus.CLOSED])
async def test_c7_a_proposal_needs_shortlisted_or_proposal(
    api: AsUser, team: Team, db_session: AsyncSession, status: IdeaStatus
) -> None:
    idea = await make_idea(db_session, team.project, status=status, owner=team.owner)
    key = idea_key(team, idea)
    owner = await api(team.owner)

    view = ok(await owner.get(proposal_url(key)))
    assert view["permissions"]["can_create"] is False
    assert_problem(await owner.post(proposal_url(key)), 409, "proposal_not_available")


async def test_a_second_start_is_refused(api: AsUser, team: Team, key: str) -> None:
    owner = await api(team.owner)
    await start(owner, key)
    assert_problem(await owner.post(proposal_url(key)), 409, "proposal_exists")
    assert_problem(await (await api(team.admin)).post(proposal_url(key)), 409, "proposal_exists")


async def test_archived_projects_are_read_only(
    api: AsUser, team: Team, key: str, db_session: AsyncSession
) -> None:
    owner = await api(team.owner)
    await start(owner, key)
    await db_session.execute(
        update(Project).where(Project.id == team.project.id).values(archived_at=Project.created_at)
    )
    await db_session.commit()

    view = ok(await owner.get(proposal_url(key)))
    assert view["permissions"]["can_edit"] is False
    assert view["permissions"]["can_export"] is True
    response = await owner.put(section_url(key, "problem"), {"body_md": "x", "base_version": 1})
    assert_problem(response, 409, "project_archived")


async def test_an_idea_held_for_moderation_has_no_proposal_writes(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea = await make_idea(
        db_session, team.project, status=IdeaStatus.SHORTLISTED, owner=team.owner
    )
    await db_session.execute(
        update(Idea).where(Idea.id == idea.id).values(held_for=HoldReason.MODERATION)
    )
    await db_session.commit()
    key = idea_key(team, idea)

    admin = await api(team.admin)
    view = ok(await admin.get(proposal_url(key)))
    assert view["permissions"] == {
        "can_create": False,
        "can_edit": False,
        "can_comment": False,
        "can_export": False,
    }
    assert_problem(await admin.post(proposal_url(key)), 409, "awaiting_moderation")
    # Everyone else doesn't see the idea at all (c12).
    assert_problem(await (await api(team.owner)).post(proposal_url(key)), 404, "not_found")
    assert_problem(await (await api(team.member)).get(proposal_url(key)), 404, "not_found")


async def test_an_idea_held_for_email_verification_is_404_for_everyone(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    idea = await make_idea(db_session, team.project, status=IdeaStatus.SHORTLISTED)
    await db_session.execute(
        update(Idea).where(Idea.id == idea.id).values(held_for=HoldReason.EMAIL_VERIFICATION)
    )
    await db_session.commit()
    key = idea_key(team, idea)

    for user in (team.admin, team.platform):
        assert_problem(await (await api(user)).get(proposal_url(key)), 404, "not_found")
        assert_problem(await (await api(user)).post(proposal_url(key)), 404, "not_found")


# --- Saving sections ------------------------------------------------------------------
async def test_a_save_stores_the_text_verbatim_and_bumps_the_version(
    api: AsUser, team: Team, key: str
) -> None:
    owner = await api(team.owner)
    await start(owner, key)
    text = "    indented code\n\n\tand a tab\n\nTrailing blank lines:\n\n\n"

    saved = ok(await owner.put(section_url(key, "problem"), {"body_md": text, "base_version": 1}))

    assert saved["body_md"] == text
    assert saved["version"] == 2
    assert saved["key"] == "problem"
    assert saved["title"] == "Problem"
    assert saved["updated_by"]["display_name"] == "Olive Owner"
    again = sections(ok(await owner.get(proposal_url(key))))["problem"]
    assert again["body_md"] == text
    assert again["version"] == 2


async def test_admins_save_too_members_and_viewers_cannot(
    api: AsUser, team: Team, key: str
) -> None:
    await start(await api(team.owner), key)
    body = {"body_md": "Admin text", "base_version": 1}

    assert ok(await (await api(team.admin)).put(section_url(key, "risks"), body))["version"] == 2
    for user in (team.member, team.viewer, team.evaluators[0]):
        response = await (await api(user)).put(section_url(key, "cost"), body)
        assert_problem(response, 403, "forbidden")
    response = await (await api(team.outsider)).put(section_url(key, "cost"), body)
    assert_problem(response, 404, "not_found")


async def test_saving_without_a_proposal_is_404(api: AsUser, team: Team, key: str) -> None:
    response = await (await api(team.owner)).put(
        section_url(key, "problem"), {"body_md": "x", "base_version": 1}
    )
    assert_problem(response, 404, "not_found")


async def test_a_save_from_an_older_version_is_a_conflict_with_the_current_section(
    api: AsUser, team: Team, key: str
) -> None:
    owner, admin = await api(team.owner), await api(team.admin)
    await start(owner, key)
    ok(await admin.put(section_url(key, "problem"), {"body_md": "Admin's", "base_version": 1}))

    response = await owner.put(section_url(key, "problem"), {"body_md": "Mine", "base_version": 1})

    body = assert_problem(response, 409, "proposal_conflict")
    current = body["current"]
    assert current["body_md"] == "Admin's"
    assert current["version"] == 2
    assert current["updated_by"]["display_name"] == "Ada Admin"
    # "Keep mine": save again from current.version.
    kept = ok(
        await owner.put(
            section_url(key, "problem"), {"body_md": "Mine", "base_version": current["version"]}
        )
    )
    assert (kept["body_md"], kept["version"]) == ("Mine", 3)


async def test_a_conflict_on_a_never_saved_section_keeps_updated_by_null(
    api: AsUser, team: Team, key: str
) -> None:
    owner = await api(team.owner)
    await start(owner, key)

    response = await owner.put(section_url(key, "risks"), {"body_md": "x", "base_version": 7})

    body = assert_problem(response, 409, "proposal_conflict")
    assert body["current"]["updated_by"] is None
    assert body["current"]["version"] == 1


async def test_an_identical_save_is_a_no_op(api: AsUser, team: Team, key: str) -> None:
    owner = await api(team.owner)
    await start(owner, key)
    first = ok(await owner.put(section_url(key, "problem"), {"body_md": "A", "base_version": 1}))

    retried = ok(await owner.put(section_url(key, "problem"), {"body_md": "A", "base_version": 1}))
    same = ok(await owner.put(section_url(key, "problem"), {"body_md": "A", "base_version": 2}))

    assert retried == first
    assert same == first
    assert first["version"] == 2


async def test_two_saves_from_the_same_version_one_wins_one_conflicts(
    api: AsUser, team: Team, key: str
) -> None:
    owner, admin = await api(team.owner), await api(team.admin)
    await start(owner, key)
    ok(await owner.put(section_url(key, "solution"), {"body_md": "v2", "base_version": 1}))
    ok(await owner.put(section_url(key, "solution"), {"body_md": "v3", "base_version": 2}))

    responses = await asyncio.gather(
        owner.put(section_url(key, "solution"), {"body_md": "owner", "base_version": 3}),
        admin.put(section_url(key, "solution"), {"body_md": "admin", "base_version": 3}),
    )

    statuses = sorted(response.status_code for response in responses)
    assert statuses == [200, 409]
    winner = next(r for r in responses if r.status_code == 200).json()
    loser = next(r for r in responses if r.status_code == 409).json()
    assert loser["code"] == "proposal_conflict"
    assert loser["current"] == winner
    assert winner["version"] == 4


async def test_saves_to_different_sections_never_conflict(
    api: AsUser, team: Team, key: str
) -> None:
    owner, admin = await api(team.owner), await api(team.admin)
    await start(owner, key)

    responses = await asyncio.gather(
        *(
            client.put(section_url(key, section), {"body_md": f"{section} text", "base_version": 1})
            for client, section in [
                (owner, "problem"),
                (admin, "solution"),
                (owner, "market"),
                (admin, "cost"),
            ]
        )
    )

    assert [response.status_code for response in responses] == [200, 200, 200, 200]
    view = sections(ok(await owner.get(proposal_url(key))))
    assert view["cost"]["body_md"] == "cost text"
    assert view["market"]["version"] == 2


async def test_saves_need_c7_but_the_proposal_stays_readable(
    api: AsUser, team: Team, idea: Idea, key: str
) -> None:
    owner = await api(team.owner)
    await start(owner, key)
    ok(await owner.post(f"/ideas/{key}/status", {"status": "evaluating"}))

    response = await owner.put(section_url(key, "problem"), {"body_md": "x", "base_version": 1})
    assert_problem(response, 409, "proposal_not_available")
    view = ok(await owner.get(proposal_url(key)))
    assert view["proposal"] is not None
    assert view["permissions"] == {
        "can_create": False,
        "can_edit": False,
        "can_comment": True,
        "can_export": True,
    }

    ok(await owner.post(f"/ideas/{key}/status", {"status": "shortlisted"}))
    assert (
        ok(await owner.put(section_url(key, "problem"), {"body_md": "x", "base_version": 1}))[
            "version"
        ]
        == 2
    )


async def test_section_saves_are_not_activity(
    api: AsUser, team: Team, idea: Idea, key: str, db_session: AsyncSession
) -> None:
    owner = await api(team.owner)
    await start(owner, key)
    before = await db_session.scalar(
        select(Idea.last_activity_at)
        .where(Idea.id == idea.id)
        .execution_options(populate_existing=True)
    )
    events = await db_session.scalar(
        select(ActivityEvent.id).where(ActivityEvent.idea_id == idea.id).limit(1)
    )

    ok(await owner.put(section_url(key, "problem"), {"body_md": "x", "base_version": 1}))

    after = await db_session.scalar(
        select(Idea.last_activity_at)
        .where(Idea.id == idea.id)
        .execution_options(populate_existing=True)
    )
    assert after == before
    rows = await db_session.scalars(
        select(ActivityEvent.id).where(ActivityEvent.idea_id == idea.id)
    )
    assert list(rows) == [events]


async def test_deleting_the_idea_deletes_its_proposal(api: AsUser, team: Team, key: str) -> None:
    owner = await api(team.owner)
    await start(owner, key)
    admin = await api(team.admin)
    assert (await admin.delete(f"/ideas/{key}")).status_code == 204
    assert_problem(await admin.get(proposal_url(key)), 404, "not_found")


# --- A status change racing a save ---------------------------------------------------
async def test_a_status_change_waits_for_a_save_in_flight_and_vice_versa(
    app: FastAPI, api: AsUser, team: Team, idea: Idea, key: str
) -> None:
    """The save holds the idea row ``FOR SHARE`` until it commits, so a status change
    (``FOR UPDATE``) waits for it; a save that starts after the status change took its
    lock sees the new status (c7) instead of writing into a proposal that just became
    read-only."""
    from app.domain.principal import Principal
    from app.errors import ProblemError
    from app.models.enums import ProposalSectionKey
    from app.proposals import service
    from app.schemas.ideas import StatusChange
    from app.schemas.proposals import ProposalSectionUpdate
    from app.services import ideas as idea_service

    await start(await api(team.owner), key)
    sessionmaker = app.state.sessionmaker
    owner = Principal(user=team.owner)

    # 1. A save in flight blocks the status change until it commits.
    async with sessionmaker() as saving:
        loaded = await service.load_idea_shared(saving, owner, key)
        await service.update_section(
            saving,
            owner,
            loaded,
            ProposalSectionKey.PROBLEM,
            ProposalSectionUpdate(body_md="x", base_version=1),
        )

        async def move() -> None:
            async with sessionmaker() as moving:
                target = await idea_service.load_idea(moving, owner, key, for_update=True)
                await idea_service.change_status(
                    moving, owner, target, StatusChange(status=IdeaStatus.EVALUATING)
                )
                await moving.commit()

        mover = asyncio.create_task(move())
        await asyncio.sleep(0.3)
        assert not mover.done()  # waiting for the save's share lock
        await saving.commit()
    await asyncio.wait_for(mover, 5)

    # 2. A save that starts while a status change holds the idea waits for it, then
    #    sees the new status: Shortlisted -> Evaluating makes the proposal read-only.
    async with sessionmaker() as moving:
        target = await idea_service.load_idea(moving, owner, key, for_update=True)
        await idea_service.change_status(
            moving, owner, target, StatusChange(status=IdeaStatus.SHORTLISTED)
        )
        await moving.commit()

    async with sessionmaker() as moving:
        target = await idea_service.load_idea(moving, owner, key, for_update=True)
        await idea_service.change_status(
            moving, owner, target, StatusChange(status=IdeaStatus.EVALUATING)
        )

        async def save() -> int:
            async with sessionmaker() as saving:
                again = await service.load_idea_shared(saving, owner, key)
                try:
                    await service.update_section(
                        saving,
                        owner,
                        again,
                        ProposalSectionKey.PROBLEM,
                        ProposalSectionUpdate(body_md="y", base_version=2),
                    )
                except ProblemError as error:
                    return error.status
                await saving.commit()
                return 200

        saver = asyncio.create_task(save())
        await asyncio.sleep(0.3)
        assert not saver.done()  # waiting for the status change's lock
        await moving.commit()
    assert await asyncio.wait_for(saver, 5) == 409
