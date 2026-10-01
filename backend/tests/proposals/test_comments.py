"""Margin comment threads (contract-phase4 3.3; role matrix rows E and B): who may
open, reply, resolve and delete; stubs and unlisted threads; caps; no notifications."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import utcnow
from app.models.notification import Notification
from app.models.project import Project
from app.models.proposal import Proposal, ProposalComment, ProposalThread
from app.schemas.proposals import MAX_COMMENTS_PER_THREAD, MAX_THREADS_PER_PROPOSAL
from tests.proposals.conftest import Api, AsUser, Team, assert_problem, ok, proposal_url, start


def threads_url(key: str) -> str:
    return f"{proposal_url(key)}/threads"


async def open_thread(
    client: Api, key: str, section: str = "problem", text: str = "Source for the 8%?"
) -> dict[str, Any]:
    thread: dict[str, Any] = ok(
        await client.post(threads_url(key), {"section_key": section, "body_md": text}), 201
    )
    return thread


@pytest.fixture
async def started(api: AsUser, team: Team, key: str) -> str:
    await start(await api(team.owner), key)
    return key


async def test_members_open_threads_that_everyone_who_can_view_reads(
    api: AsUser, team: Team, started: str
) -> None:
    member = await api(team.member)

    thread = await open_thread(member, started)

    assert thread["section_key"] == "problem"
    assert thread["resolved_at"] is None
    assert thread["resolved_by"] is None
    [comment] = thread["comments"]
    assert comment["body_md"] == "Source for the 8%?"
    assert comment["author"]["display_name"] == "Max Member"
    assert comment["deleted"] is False
    assert comment["can_delete"] is True
    for reader in (team.viewer, team.owner, team.platform):
        listed = ok(await (await api(reader)).get(threads_url(started)))
        assert [item["id"] for item in listed["items"]] == [thread["id"]]
    viewer_view = ok(await (await api(team.viewer)).get(threads_url(started)))
    assert viewer_view["items"][0]["comments"][0]["can_delete"] is False
    admin_view = ok(await (await api(team.admin)).get(threads_url(started)))
    assert admin_view["items"][0]["comments"][0]["can_delete"] is True


async def test_viewers_and_outsiders_cannot_comment(api: AsUser, team: Team, started: str) -> None:
    body = {"section_key": "problem", "body_md": "Hi"}
    response = await (await api(team.viewer)).post(threads_url(started), body)
    assert_problem(response, 403, "forbidden")
    response = await (await api(team.outsider)).post(threads_url(started), body)
    assert_problem(response, 404, "not_found")
    assert_problem(await (await api(team.outsider)).get(threads_url(started)), 404, "not_found")


async def test_threads_need_a_proposal(api: AsUser, team: Team, key: str) -> None:
    member = await api(team.member)
    assert_problem(await member.get(threads_url(key)), 404, "not_found")
    response = await member.post(threads_url(key), {"section_key": "problem", "body_md": "Hi"})
    assert_problem(response, 404, "not_found")


async def test_threads_are_listed_in_template_order_then_oldest_first(
    api: AsUser, team: Team, started: str
) -> None:
    member = await api(team.member)
    risks = await open_thread(member, started, "risks", "Risky")
    summary = await open_thread(member, started, "summary", "Short")
    problem_one = await open_thread(member, started, "problem", "First")
    problem_two = await open_thread(member, started, "problem", "Second")

    listed = ok(await member.get(threads_url(started)))

    assert [item["id"] for item in listed["items"]] == [
        summary["id"],
        problem_one["id"],
        problem_two["id"],
        risks["id"],
    ]


async def test_replies_resolve_and_reopen(api: AsUser, team: Team, started: str) -> None:
    member, owner = await api(team.member), await api(team.owner)
    thread = await open_thread(member, started)
    url = f"{threads_url(started)}/{thread['id']}"

    replied = ok(await owner.post(f"{url}/comments", {"body_md": "The Q3 report, page 4."}), 201)
    assert [c["body_md"] for c in replied["comments"]] == [
        "Source for the 8%?",
        "The Q3 report, page 4.",
    ]
    assert replied["comments"][1]["author"]["display_name"] == "Olive Owner"

    resolved = ok(await owner.put(f"{url}/resolved"))
    assert resolved["resolved_by"]["display_name"] == "Olive Owner"
    assert resolved["resolved_at"] is not None
    again = ok(await member.put(f"{url}/resolved"))  # idempotent: keeps who resolved it
    assert again["resolved_by"]["display_name"] == "Olive Owner"
    assert again["resolved_at"] == resolved["resolved_at"]

    reopened = ok(await member.delete(f"{url}/resolved"))
    assert reopened["resolved_at"] is None
    assert reopened["resolved_by"] is None
    assert ok(await member.delete(f"{url}/resolved"))["resolved_at"] is None

    ok(await owner.put(f"{url}/resolved"))
    by_reply = ok(await member.post(f"{url}/comments", {"body_md": "One more thing"}), 201)
    assert by_reply["resolved_at"] is None
    assert len(by_reply["comments"]) == 3


async def test_viewers_cannot_reply_or_resolve(api: AsUser, team: Team, started: str) -> None:
    thread = await open_thread(await api(team.member), started)
    url = f"{threads_url(started)}/{thread['id']}"
    viewer = await api(team.viewer)
    assert_problem(await viewer.post(f"{url}/comments", {"body_md": "x"}), 403, "forbidden")
    assert_problem(await viewer.put(f"{url}/resolved"), 403, "forbidden")
    assert_problem(await viewer.delete(f"{url}/resolved"), 403, "forbidden")


async def test_unknown_threads_are_404(api: AsUser, team: Team, started: str) -> None:
    member = await api(team.member)
    url = f"{threads_url(started)}/{uuid4()}"
    assert_problem(await member.post(f"{url}/comments", {"body_md": "x"}), 404, "not_found")
    assert_problem(await member.put(f"{url}/resolved"), 404, "not_found")
    assert_problem(await member.delete(f"{url}/comments/{uuid4()}"), 404, "not_found")


async def test_threads_of_another_proposal_are_404(
    api: AsUser, team: Team, started: str, db_session: AsyncSession
) -> None:
    from app.models.enums import IdeaStatus
    from tests.factories import make_idea
    from tests.proposals.conftest import idea_key

    other = await make_idea(
        db_session, team.project, status=IdeaStatus.SHORTLISTED, owner=team.owner
    )
    other_key = idea_key(team, other)
    await start(await api(team.owner), other_key)
    member = await api(team.member)
    thread = await open_thread(member, started)

    url = f"{threads_url(other_key)}/{thread['id']}"
    assert_problem(await member.post(f"{url}/comments", {"body_md": "x"}), 404, "not_found")
    comment = thread["comments"][0]["id"]
    assert_problem(await member.delete(f"{url}/comments/{comment}"), 404, "not_found")


async def test_deleting_comments(api: AsUser, team: Team, started: str) -> None:
    member, owner, admin = await api(team.member), await api(team.owner), await api(team.admin)
    thread = await open_thread(member, started)
    url = f"{threads_url(started)}/{thread['id']}"
    reply = ok(await owner.post(f"{url}/comments", {"body_md": "Owner's reply"}), 201)
    first, second = (c["id"] for c in reply["comments"])

    # Someone else's: 403 not_author for a member; project admins may.
    assert_problem(await member.delete(f"{url}/comments/{second}"), 403, "not_author")
    assert_problem(
        await (await api(team.viewer)).delete(f"{url}/comments/{first}"), 403, "not_author"
    )
    assert (await admin.delete(f"{url}/comments/{second}")).status_code == 204

    listed = ok(await member.get(threads_url(started)))["items"][0]["comments"]
    assert listed[1] == listed[1] | {"body_md": "", "deleted": True, "can_delete": False}
    assert listed[1]["author"]["display_name"] == "Olive Owner"

    # Your own: fine, and again (idempotent).
    assert (await member.delete(f"{url}/comments/{first}")).status_code == 204
    assert (await member.delete(f"{url}/comments/{first}")).status_code == 204
    # Every comment deleted: the thread is no longer listed or reachable.
    assert ok(await member.get(threads_url(started)))["items"] == []
    assert_problem(await member.post(f"{url}/comments", {"body_md": "x"}), 404, "not_found")
    assert_problem(await member.put(f"{url}/resolved"), 404, "not_found")


async def test_platform_admins_delete_any_comment(api: AsUser, team: Team, started: str) -> None:
    thread = await open_thread(await api(team.member), started)
    comment = thread["comments"][0]["id"]
    url = f"{threads_url(started)}/{thread['id']}/comments/{comment}"
    assert (await (await api(team.platform)).delete(url)).status_code == 204


async def test_archived_projects_refuse_comment_writes(
    api: AsUser, team: Team, started: str, db_session: AsyncSession
) -> None:
    member = await api(team.member)
    thread = await open_thread(member, started)
    url = f"{threads_url(started)}/{thread['id']}"
    await db_session.execute(
        update(Project).where(Project.id == team.project.id).values(archived_at=utcnow())
    )
    await db_session.commit()

    body = {"section_key": "problem", "body_md": "x"}
    assert_problem(await member.post(threads_url(started), body), 409, "project_archived")
    assert_problem(await member.post(f"{url}/comments", {"body_md": "x"}), 409, "project_archived")
    assert_problem(await member.put(f"{url}/resolved"), 409, "project_archived")
    comment = thread["comments"][0]["id"]
    assert_problem(await member.delete(f"{url}/comments/{comment}"), 409, "project_archived")
    listed = ok(await member.get(threads_url(started)))
    assert listed["items"][0]["comments"][0]["can_delete"] is False


async def test_thread_and_comment_caps(
    api: AsUser, team: Team, started: str, idea: Any, db_session: AsyncSession
) -> None:
    member = await api(team.member)
    proposal_id = await db_session.scalar(select(Proposal.id).where(Proposal.idea_id == idea.id))
    thread = await open_thread(member, started)
    now = utcnow()
    await db_session.execute(
        insert(ProposalThread),
        [
            {
                "id": uuid4(),
                "proposal_id": proposal_id,
                "section_key": "risks",
                "created_at": now,
                "updated_at": now,
            }
            for _ in range(MAX_THREADS_PER_PROPOSAL - 1)
        ],
    )
    await db_session.execute(
        insert(ProposalComment),
        [
            {
                "id": uuid4(),
                "thread_id": thread["id"],
                "author_id": team.member.id,
                "body_md": "more",
                "created_at": now,
                "updated_at": now,
            }
            for _ in range(MAX_COMMENTS_PER_THREAD - 1)
        ],
    )
    await db_session.commit()

    body = {"section_key": "problem", "body_md": "One too many"}
    assert_problem(await member.post(threads_url(started), body), 409, "too_many_comments")
    url = f"{threads_url(started)}/{thread['id']}/comments"
    assert_problem(await member.post(url, {"body_md": "x"}), 409, "too_many_comments")
    count = await db_session.scalar(
        select(func.count())
        .select_from(ProposalComment)
        .where(ProposalComment.thread_id == thread["id"])
    )
    assert count == MAX_COMMENTS_PER_THREAD


async def test_margin_comments_notify_nobody_in_phase_4(
    api: AsUser, team: Team, started: str, db_session: AsyncSession
) -> None:
    before = await db_session.scalar(select(func.count()).select_from(Notification))
    member = await api(team.member)
    thread = await open_thread(member, started, text=f"@[Olive Owner](user:{team.owner.id}) look")
    ok(
        await (await api(team.owner)).post(
            f"{threads_url(started)}/{thread['id']}/comments", {"body_md": "Thanks"}
        ),
        201,
    )

    after = await db_session.scalar(select(func.count()).select_from(Notification))
    assert after == before


async def test_comment_text_is_kept_as_written(api: AsUser, team: Team, started: str) -> None:
    text = "**Bold** and <b>html</b>\n\n- a list"
    thread = await open_thread(await api(team.member), started, text=text)
    assert thread["comments"][0]["body_md"] == text
