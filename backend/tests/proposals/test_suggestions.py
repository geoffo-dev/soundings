"""Proposal suggestions over REST (contract-phase5 section 3.4; role matrix section E):
create (``proposal.suggest_section``), list (``proposal.view``), accept and discard
(``proposal.write``) for every column, c7, archived and held ideas, one pending suggestion
per author and section, the cap of 50, ``base_version`` rules, accepting as a versioned
section save, and accept/discard races."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.principal import Principal
from app.models.activity import ActivityEvent, AuditLog
from app.models.enums import (
    HoldReason,
    IdeaStatus,
    ProjectRole,
    ProposalSectionKey,
    SuggestionSource,
    SuggestionStatus,
)
from app.models.idea import Idea
from app.models.notification import Notification
from app.models.project import Project, ProjectMember
from app.models.proposal import ProposalSuggestion
from app.models.user import User
from app.proposals import suggestions
from app.schemas.proposals import MAX_PENDING_SUGGESTIONS, ProposalSuggestionCreate
from app.services import ideas
from tests.factories import make_idea, make_user
from tests.proposals.conftest import AsUser, Team, assert_problem, ok, proposal_url, start


def url(key: str, suffix: str = "") -> str:
    return f"{proposal_url(key)}/suggestions{suffix}"


async def suggest(client: Any, key: str, section: str = "risks", **body: Any) -> dict[str, Any]:
    body.setdefault("body_md", "- Supplier lock-in\n")
    created: dict[str, Any] = ok(await client.post(url(key), {"section_key": section, **body}), 201)
    return created


def section(view: dict[str, Any], key: str) -> dict[str, Any]:
    found: dict[str, Any] = next(s for s in view["proposal"]["sections"] if s["key"] == key)
    return found


@pytest.fixture
async def started(api: AsUser, team: Team, key: str) -> str:
    """The idea's proposal, started by its owner; returns the idea key."""
    await start(await api(team.owner), key)
    return key


# --- Create and list -----------------------------------------------------------------
async def test_a_member_suggests_text_and_everyone_who_reads_the_proposal_sees_it(
    api: AsUser, team: Team, started: str
) -> None:
    member = await api(team.member)

    created = await suggest(member, started, body_md="  Indented code\n\n- and a list\n")

    assert created["section_key"] == "risks"
    assert created["body_md"] == "  Indented code\n\n- and a list\n"  # verbatim
    assert created["base_version"] == 1  # default: the current version
    assert created["section_changed"] is False
    assert created["author"]["display_name"] == "Max Member"
    assert created["source"] == "api"
    assert created["status"] == "pending"
    assert created["decided_at"] is None
    assert created["decided_by"] is None
    for user, can_suggest, can_decide in [
        (team.owner, True, True),
        (team.admin, True, True),
        (team.platform, True, True),
        (team.member, True, False),
        (team.evaluators[0], True, False),
        (team.viewer, False, False),
    ]:
        listed = ok(await (await api(user)).get(url(started)))
        assert [item["id"] for item in listed["items"]] == [created["id"]], user.display_name
        assert listed["permissions"] == {"can_suggest": can_suggest, "can_decide": can_decide}


@pytest.mark.parametrize("who", ["owner", "admin", "platform", "member"])
async def test_members_owners_and_admins_may_suggest(
    api: AsUser, team: Team, started: str, who: str
) -> None:
    created = await suggest(await api(getattr(team, who)), started)
    assert created["status"] == "pending"


@pytest.mark.parametrize(
    ("who", "status", "code"), [("viewer", 403, "forbidden"), ("outsider", 404, "not_found")]
)
async def test_viewers_and_outsiders_may_not_suggest(
    api: AsUser, team: Team, started: str, who: str, status: int, code: str
) -> None:
    client = await api(getattr(team, who))
    response = await client.post(url(started), {"section_key": "risks", "body_md": "x"})
    assert_problem(response, status, code)
    if who == "outsider":
        assert_problem(await client.get(url(started)), 404, "not_found")


async def test_an_internal_non_member_reads_but_may_not_suggest(
    api: AsUser, team: Team, started: str, db_session: AsyncSession
) -> None:
    await db_session.execute(
        update(Project).where(Project.id == team.project.id).values(visibility="internal")
    )
    await db_session.commit()
    outsider = await api(team.outsider)

    listed = ok(await outsider.get(url(started)))
    response = await outsider.post(url(started), {"section_key": "risks", "body_md": "x"})

    assert listed == {"items": [], "permissions": {"can_suggest": False, "can_decide": False}}
    assert_problem(response, 403, "forbidden")


async def test_without_a_proposal_every_suggestion_route_is_404(
    api: AsUser, team: Team, key: str
) -> None:
    admin = await api(team.admin)
    missing = f"/{uuid4()}"

    for response in [
        await admin.get(url(key)),
        await admin.post(url(key), {"section_key": "risks", "body_md": "x"}),
        await admin.post(url(key, missing + "/accept"), {"base_version": 1}),
        await admin.post(url(key, missing + "/discard")),
    ]:
        body = assert_problem(response, 404, "not_found")
    assert body["detail"] == "This idea has no proposal yet."


async def test_a_new_suggestion_from_the_same_author_replaces_the_pending_one(
    api: AsUser, team: Team, started: str, db_session: AsyncSession
) -> None:
    member, other = await api(team.member), await api(team.evaluators[0])
    first = await suggest(member, started, body_md="First try")
    theirs = await suggest(other, started, body_md="Someone else's")
    other_section = await suggest(member, started, section="cost", body_md="Cheap")

    second = await suggest(member, started, body_md="Second try")

    listed = ok(await member.get(url(started)))
    assert [item["id"] for item in listed["items"]] == [
        other_section["id"],  # template order: cost before risks
        theirs["id"],
        second["id"],
    ]
    replaced = await db_session.get(ProposalSuggestion, first["id"], populate_existing=True)
    assert replaced is not None
    assert replaced.status is SuggestionStatus.DISCARDED
    assert replaced.decided_by_id == team.member.id
    assert replaced.decided_at is not None


async def test_a_base_version_above_the_section_is_a_validation_error(
    api: AsUser, team: Team, started: str
) -> None:
    member = await api(team.member)

    response = await member.post(
        url(started), {"section_key": "risks", "body_md": "x", "base_version": 2}
    )

    body = assert_problem(response, 422, "validation_error")
    assert body["errors"][0]["loc"] == ["body", "base_version"]
    created = await suggest(member, started, base_version=1)
    assert created["base_version"] == 1


async def test_the_51st_pending_suggestion_is_refused_but_a_replacement_still_works(
    api: AsUser, team: Team, started: str, idea: Idea, db_session: AsyncSession
) -> None:
    member = await api(team.member)
    mine = await suggest(member, started, section="cost")
    proposal_id = await db_session.scalar(
        select(ProposalSuggestion.proposal_id).where(ProposalSuggestion.id == mine["id"])
    )
    db_session.add_all(
        ProposalSuggestion(
            id=uuid4(),
            proposal_id=proposal_id,
            section_key=ProposalSectionKey.RISKS,
            body_md=f"Suggestion {n}",
            base_version=1,
            author_id=None,  # authors who no longer exist: no per-author limit applies
            source=SuggestionSource.API,
        )
        for n in range(MAX_PENDING_SUGGESTIONS - 1)
    )
    await db_session.commit()

    response = await member.post(url(started), {"section_key": "risks", "body_md": "x"})
    replacement = await suggest(member, started, section="cost", body_md="Better")

    assert_problem(response, 409, "too_many_suggestions")
    assert replacement["status"] == "pending"
    pending = await db_session.scalar(
        select(func.count())
        .select_from(ProposalSuggestion)
        .where(ProposalSuggestion.status == SuggestionStatus.PENDING)
    )
    assert pending == MAX_PENDING_SUGGESTIONS


# --- Accept and discard --------------------------------------------------------------
async def test_accepting_saves_the_text_as_a_versioned_section_save(
    api: AsUser, team: Team, started: str
) -> None:
    created = await suggest(await api(team.member), started, body_md="  Verbatim\n")
    owner = await api(team.owner)

    accepted = ok(await owner.post(url(started, f"/{created['id']}/accept"), {"base_version": 1}))

    assert accepted["suggestion"]["status"] == "accepted"
    assert accepted["suggestion"]["decided_by"]["display_name"] == "Olive Owner"
    assert accepted["suggestion"]["decided_at"] is not None
    assert accepted["section"]["key"] == "risks"
    assert accepted["section"]["body_md"] == "  Verbatim\n"
    assert accepted["section"]["version"] == 2
    assert accepted["section"]["updated_by"]["display_name"] == "Olive Owner"
    view = ok(await owner.get(proposal_url(started)))
    assert section(view, "risks")["body_md"] == "  Verbatim\n"
    assert ok(await owner.get(url(started)))["items"] == []


async def test_accepting_after_someone_saved_the_section_is_a_conflict(
    api: AsUser, team: Team, started: str
) -> None:
    created = await suggest(await api(team.member), started)
    owner = await api(team.owner)
    saved = ok(
        await owner.put(
            f"{proposal_url(started)}/sections/risks", {"body_md": "Mine", "base_version": 1}
        )
    )

    listed = ok(await owner.get(url(started)))
    response = await owner.post(url(started, f"/{created['id']}/accept"), {"base_version": 1})

    assert listed["items"][0]["section_changed"] is True
    body = assert_problem(response, 409, "proposal_conflict")
    assert body["current"]["version"] == saved["version"] == 2
    assert body["current"]["body_md"] == "Mine"
    still = ok(await owner.get(url(started)))["items"][0]
    assert still["status"] == "pending"
    retried = ok(await owner.post(url(started, f"/{created['id']}/accept"), {"base_version": 2}))
    assert retried["section"]["version"] == 3


async def test_accepting_text_equal_to_the_section_changes_no_version(
    api: AsUser, team: Team, started: str
) -> None:
    owner = await api(team.owner)
    ok(
        await owner.put(
            f"{proposal_url(started)}/sections/risks", {"body_md": "Same", "base_version": 1}
        )
    )
    created = await suggest(await api(team.member), started, body_md="Same", base_version=1)

    accepted = ok(await owner.post(url(started, f"/{created['id']}/accept"), {"base_version": 1}))

    assert accepted["section"]["version"] == 2
    assert accepted["suggestion"]["status"] == "accepted"


async def test_deciding_twice(api: AsUser, team: Team, started: str) -> None:
    member, owner = await api(team.member), await api(team.owner)
    one = await suggest(member, started, section="risks")
    two = await suggest(member, started, section="cost")
    ok(await owner.post(url(started, f"/{one['id']}/accept"), {"base_version": 1}))

    again = await owner.post(url(started, f"/{one['id']}/accept"), {"base_version": 2})
    discard_accepted = await owner.post(url(started, f"/{one['id']}/discard"))
    first = ok(await owner.post(url(started, f"/{two['id']}/discard")))
    second = ok(await owner.post(url(started, f"/{two['id']}/discard")))
    accept_discarded = await owner.post(url(started, f"/{two['id']}/accept"), {"base_version": 1})

    assert_problem(again, 409, "suggestion_not_pending")
    assert_problem(discard_accepted, 409, "suggestion_not_pending")
    assert first["status"] == second["status"] == "discarded"
    assert first["decided_at"] == second["decided_at"]
    assert first["decided_by"]["display_name"] == "Olive Owner"
    assert_problem(accept_discarded, 409, "suggestion_not_pending")


@pytest.mark.parametrize(
    ("who", "status", "code"),
    [
        ("member", 403, "forbidden"),
        ("viewer", 403, "forbidden"),
        ("outsider", 404, "not_found"),
    ],
)
async def test_only_the_owner_and_admins_decide(
    api: AsUser, team: Team, started: str, who: str, status: int, code: str
) -> None:
    created = await suggest(await api(team.evaluators[0]), started)
    client = await api(getattr(team, who))

    accept = await client.post(url(started, f"/{created['id']}/accept"), {"base_version": 1})
    discard = await client.post(url(started, f"/{created['id']}/discard"))

    assert_problem(accept, status, code)
    assert_problem(discard, status, code)


@pytest.mark.parametrize("who", ["admin", "platform"])
async def test_admins_decide_too(api: AsUser, team: Team, started: str, who: str) -> None:
    created = await suggest(await api(team.member), started)
    client = await api(getattr(team, who))
    assert ok(await client.post(url(started, f"/{created['id']}/discard")))["status"] == (
        "discarded"
    )


async def test_a_suggestion_of_another_proposal_is_not_found(
    api: AsUser, team: Team, started: str, db_session: AsyncSession
) -> None:
    other = await make_idea(
        db_session, team.project, status=IdeaStatus.SHORTLISTED, owner=team.owner
    )
    other_key = f"{team.project.key}-{other.number}"
    owner = await api(team.owner)
    await start(owner, other_key)
    created = await suggest(await api(team.member), started)

    response = await owner.post(url(other_key, f"/{created['id']}/discard"))

    assert_problem(response, 404, "not_found")


async def test_a_discard_racing_an_accept_never_overwrites_it(
    api: AsUser, team: Team, started: str, db_session: AsyncSession
) -> None:
    member = await api(team.member)
    owner, admin = await api(team.owner), await api(team.admin)
    for attempt in range(5):
        created = await suggest(member, started, body_md=f"Attempt {attempt}")
        version = section(ok(await owner.get(proposal_url(started))), "risks")["version"]

        accept, discard = await asyncio.gather(
            owner.post(url(started, f"/{created['id']}/accept"), {"base_version": version}),
            admin.post(url(started, f"/{created['id']}/discard")),
        )

        row = await db_session.get(ProposalSuggestion, created["id"], populate_existing=True)
        assert row is not None
        if accept.status_code == 200:
            assert row.status is SuggestionStatus.ACCEPTED
            assert_problem(discard, 409, "suggestion_not_pending")
        else:
            assert discard.status_code == 200, discard.text
            assert row.status is SuggestionStatus.DISCARDED
            assert_problem(accept, 409, "suggestion_not_pending")


# --- Conditions: c7, archived, held --------------------------------------------------
async def test_c7_suggestions_wait_while_the_idea_is_not_shortlisted_or_in_proposal(
    api: AsUser, team: Team, started: str, idea: Idea, db_session: AsyncSession
) -> None:
    created = await suggest(await api(team.member), started)
    await db_session.execute(
        update(Idea).where(Idea.id == idea.id).values(status=IdeaStatus.EVALUATING)
    )
    await db_session.commit()
    member, owner = await api(team.member), await api(team.owner)

    listed = ok(await member.get(url(started)))
    create = await member.post(url(started), {"section_key": "cost", "body_md": "x"})
    accept = await owner.post(url(started, f"/{created['id']}/accept"), {"base_version": 1})
    discard = await owner.post(url(started, f"/{created['id']}/discard"))

    assert len(listed["items"]) == 1
    assert listed["permissions"] == {"can_suggest": False, "can_decide": False}
    for response in (create, accept, discard):
        assert_problem(response, 409, "proposal_not_available")


async def test_archived_projects_take_no_suggestions_or_decisions(
    api: AsUser, team: Team, started: str, db_session: AsyncSession
) -> None:
    created = await suggest(await api(team.member), started)
    await db_session.execute(
        update(Project).where(Project.id == team.project.id).values(archived_at=Project.created_at)
    )
    await db_session.commit()
    member, owner = await api(team.member), await api(team.owner)

    create = await member.post(url(started), {"section_key": "cost", "body_md": "x"})
    accept = await owner.post(url(started, f"/{created['id']}/accept"), {"base_version": 1})
    discard = await owner.post(url(started, f"/{created['id']}/discard"))

    for response in (create, accept, discard):
        assert_problem(response, 409, "project_archived")


@pytest.mark.parametrize("closed_by", ["archived", "c7"])
async def test_a_base_version_above_the_section_is_422_before_the_409s(
    api: AsUser,
    team: Team,
    started: str,
    idea: Idea,
    db_session: AsyncSession,
    closed_by: str,
) -> None:
    """Contract check order (401 -> 404 -> 403 -> 422 -> 409; review nit): the body's own
    422 comes before the policy's conflicts (an archived project, c7). A viewer's 403 still
    comes first."""
    if closed_by == "archived":
        statement = (
            update(Project)
            .where(Project.id == team.project.id)
            .values(archived_at=Project.created_at)
        )
    else:
        statement = update(Idea).where(Idea.id == idea.id).values(status=IdeaStatus.EVALUATING)
    await db_session.execute(statement)
    await db_session.commit()
    ahead = {"section_key": "risks", "body_md": "x", "base_version": 2}

    member = await api(team.member)
    viewer = await api(team.viewer)

    assert_problem(await member.post(url(started), ahead), 422, "validation_error")
    assert_problem(await viewer.post(url(started), ahead), 403, "forbidden")
    conflict = "project_archived" if closed_by == "archived" else "proposal_not_available"
    assert_problem(await member.post(url(started), {**ahead, "base_version": 1}), 409, conflict)


async def test_an_idea_held_for_moderation_takes_no_suggestions(
    api: AsUser, team: Team, started: str, idea: Idea, db_session: AsyncSession
) -> None:
    created = await suggest(await api(team.member), started)
    await db_session.execute(
        update(Idea).where(Idea.id == idea.id).values(held_for=HoldReason.MODERATION)
    )
    await db_session.commit()
    admin = await api(team.admin)

    create = await admin.post(url(started), {"section_key": "cost", "body_md": "x"})
    discard = await admin.post(url(started, f"/{created['id']}/discard"))

    assert_problem(create, 409, "awaiting_moderation")
    assert_problem(discard, 409, "awaiting_moderation")
    assert_problem(await (await api(team.member)).get(url(started)), 404, "not_found")


async def test_an_idea_held_for_confirmation_is_404_for_everyone(
    api: AsUser, team: Team, started: str, idea: Idea, db_session: AsyncSession
) -> None:
    await db_session.execute(
        update(Idea).where(Idea.id == idea.id).values(held_for=HoldReason.EMAIL_VERIFICATION)
    )
    await db_session.commit()
    for user in (team.platform, team.admin, team.owner):
        client = await api(user)
        assert_problem(await client.get(url(started)), 404, "not_found")
        response = await client.post(url(started), {"section_key": "risks", "body_md": "x"})
        assert_problem(response, 404, "not_found")


async def test_a_demoted_owner_can_no_longer_decide(
    api: AsUser, team: Team, started: str, db_session: AsyncSession
) -> None:
    created = await suggest(await api(team.member), started)
    await db_session.execute(
        update(ProjectMember)
        .where(ProjectMember.user_id == team.owner.id)
        .values(role=ProjectRole.VIEWER)
    )
    await db_session.commit()

    response = await (await api(team.owner)).post(url(started, f"/{created['id']}/discard"))

    assert_problem(response, 403, "forbidden")


# --- Source and side effects ---------------------------------------------------------
async def test_source_follows_the_author(
    app: Any, team: Team, started: str, db_session: AsyncSession
) -> None:
    """A person through REST is ``api``, through MCP ``mcp``; a service account is ``ai``
    whatever the channel (the MCP tests cover the tool end to end)."""
    agent = await make_user(db_session, "Research Agent", service_account=True)
    db_session.add(
        ProjectMember(project_id=team.project.id, user_id=agent.id, role=ProjectRole.MEMBER)
    )
    await db_session.commit()

    async def create(user: User, channel: SuggestionSource, key: str) -> SuggestionSource:
        async with app.state.sessionmaker() as db, db.begin():
            found = await db.get(User, user.id)
            assert found is not None
            principal = Principal(user=found)
            loaded = await ideas.load_idea(db, principal, started, for_update=True)
            created = await suggestions.create_suggestion(
                db,
                principal,
                loaded,
                ProposalSuggestionCreate(section_key=ProposalSectionKey(key), body_md="x"),
                channel=channel,
            )
            return created.suggestion.source

    assert await create(team.member, SuggestionSource.MCP, "risks") is SuggestionSource.MCP
    assert await create(agent, SuggestionSource.API, "risks") is SuggestionSource.AI
    assert await create(agent, SuggestionSource.MCP, "cost") is SuggestionSource.AI


async def test_suggestions_record_no_events_notifications_or_audit_entries(
    api: AsUser, team: Team, started: str, idea: Idea, db_session: AsyncSession
) -> None:
    before = await _counts(db_session, idea)
    member, owner = await api(team.member), await api(team.owner)
    one = await suggest(member, started)
    two = await suggest(member, started, section="cost")
    ok(await owner.post(url(started, f"/{one['id']}/accept"), {"base_version": 1}))
    ok(await owner.post(url(started, f"/{two['id']}/discard")))

    assert await _counts(db_session, idea) == before


async def _counts(db: AsyncSession, idea: Idea) -> tuple[int, int, int]:
    events = await db.scalar(
        select(func.count()).select_from(ActivityEvent).where(ActivityEvent.idea_id == idea.id)
    )
    notifications = await db.scalar(select(func.count()).select_from(Notification))
    audit = await db.scalar(  # sign-ins are audited; nothing else may be
        select(func.count()).select_from(AuditLog).where(AuditLog.action.not_like("session.%"))
    )
    return int(events or 0), int(notifications or 0), int(audit or 0)


async def test_a_suggestion_needs_text_that_is_not_only_whitespace(
    api: AsUser, team: Team, started: str
) -> None:
    member: Any = await api(team.member)
    response: httpx.Response = await member.post(
        url(started), {"section_key": "risks", "body_md": " \n "}
    )
    assert_problem(response, 422, "validation_error")
