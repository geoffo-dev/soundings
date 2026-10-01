"""@mentions (contract-phase3 section 3.8): rewriting, limits and who is notified."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.email import delivery
from app.email.delivery import Runtime
from app.models.enums import NotificationMode, NotificationType, ProjectRole, ProjectVisibility
from app.models.notification import Notification
from app.models.project import Project, ProjectMember
from app.notifications.fanout import MENTION_EMAIL_CAP
from app.schemas.comments import MAX_MENTIONS, MENTION_PATTERN
from tests.factories import add_member, make_user
from tests.notifications.conftest import AsUser, Outbox, Team, assert_problem, ok

pytestmark = pytest.mark.usefixtures("team")


def token(user_id: UUID, label: str = "Someone") -> str:
    return f"@[{label}](user:{user_id})"


async def comment(api: AsUser, team: Team, body: str, *, idea: str | None = None) -> Any:
    member = await api(team.member)
    if idea is None:
        idea = (await member.create_idea(team.slug))["key"]
    return ok(await member.post(f"/ideas/{idea}/comments", {"body_md": body}), 201)


async def test_labels_are_rewritten_to_current_names(api: AsUser, team: Team) -> None:
    unknown = uuid4()
    body = f"Hi {token(team.owner.id, 'The CEO')} and {token(unknown, 'Ghost')}"

    item = await comment(api, team, body)

    stored = item["comment"]["body_md"]
    assert stored == f"Hi @[Olive Owner](user:{team.owner.id}) and @Ghost"


async def test_more_than_twenty_people_is_refused(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    people = [await make_user(db_session) for _ in range(MAX_MENTIONS + 1)]
    member = await api(team.member)
    idea = await member.create_idea(team.slug)
    body = " ".join(token(person.id) for person in people)

    response = await member.post(f"/ideas/{idea['key']}/comments", {"body_md": body})

    assert_problem(response, 422, "too_many_mentions")


async def test_the_length_limit_applies_after_rewriting(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    long_name = await make_user(db_session, "Bartholomew " + "X" * 80)
    filler = "x" * (10_000 - len(token(long_name.id, "B")))
    member = await api(team.member)
    idea = await member.create_idea(team.slug)

    response = await member.post(
        f"/ideas/{idea['key']}/comments", {"body_md": token(long_name.id, "B") + filler}
    )

    problem = assert_problem(response, 422, "validation_error")
    assert problem["errors"][0]["loc"] == ["body", "body_md"]


async def test_mentioned_project_members_are_notified_but_not_the_author_or_outsiders(
    api: AsUser, team: Team, outbox: Outbox
) -> None:
    body = " ".join(
        token(user.id)
        for user in (team.owner, team.member, team.outsider, team.platform, team.viewer)
    )

    await comment(api, team, body)

    mentions = await outbox.notifications(type_=NotificationType.MENTION)
    # Olive (member) and Vic (viewer: a role, can view) are; Max wrote it; Otto can't view
    # the private project; Pat is a platform admin without a role in it.
    assert {note.user_id for note in mentions} == {team.owner.id, team.viewer.id}
    assert {note.email_mode for note in mentions} == {NotificationMode.IMMEDIATE}


async def test_internal_project_viewers_without_a_role_are_not_notified(
    api: AsUser, team: Team, outbox: Outbox, db_session: AsyncSession
) -> None:
    project = await db_session.get(Project, team.project.id)
    assert project is not None
    project.visibility = ProjectVisibility.INTERNAL
    await db_session.commit()

    await comment(api, team, f"cc {token(team.outsider.id)}")

    assert await outbox.notifications(type_=NotificationType.MENTION) == []


async def test_editing_notifies_only_people_newly_mentioned(
    api: AsUser, team: Team, outbox: Outbox
) -> None:
    item = await comment(api, team, f"cc {token(team.owner.id)}")
    member = await api(team.member)
    path = f"/comments/{item['comment']['id']}"

    ok(await member.patch(path, {"body_md": f"cc {token(team.owner.id)} {token(team.admin.id)}"}))
    ok(await member.patch(path, {"body_md": f"cc {token(team.admin.id)}"}))
    ok(await member.patch(path, {"body_md": f"cc {token(team.owner.id)} again"}))

    mentions = await outbox.notifications(type_=NotificationType.MENTION)
    assert sorted(str(note.user_id) for note in mentions) == sorted(
        [str(team.owner.id), str(team.admin.id)]
    )  # at most one per comment and person, however often it is edited


async def test_mentioned_watchers_get_a_mention_instead_of_a_comment(
    api: AsUser, team: Team, outbox: Outbox
) -> None:
    member = await api(team.member)
    idea = (await member.create_idea(team.slug))["key"]
    ok(await (await api(team.owner)).put(f"/ideas/{idea}/watch"))
    ok(await (await api(team.admin)).put(f"/ideas/{idea}/watch"))

    await comment(api, team, f"{token(team.owner.id)} what do you think?", idea=idea)

    by_type = {
        (note.user_id, note.type) for note in await outbox.notifications() if note.comment_id
    }
    assert by_type == {
        (team.owner.id, NotificationType.MENTION),
        (team.admin.id, NotificationType.COMMENT),
    }


async def test_the_51st_mention_email_in_an_hour_is_in_app_only(
    api: AsUser, team: Team, outbox: Outbox, db_session: AsyncSession
) -> None:
    member = await api(team.member)
    idea = await member.create_idea(team.slug)
    # 49 earlier mention notifications by Max (with a real comment), then two more.
    first = await comment(api, team, "hello", idea=idea["key"])
    db_session.add_all(
        [
            Notification(
                user_id=team.admin.id,
                type=NotificationType.MENTION,
                idea_id=idea["id"],
                actor_id=team.member.id,
                comment_id=first["comment"]["id"],
                dedupe_key=f"earlier:{n}",
                email_mode=NotificationMode.IMMEDIATE,
            )
            for n in range(MENTION_EMAIL_CAP - 1)
        ]
    )
    await db_session.commit()

    await comment(api, team, f"{token(team.owner.id)} {token(team.viewer.id)}", idea=idea["key"])

    fresh = [
        note
        for note in await outbox.notifications(type_=NotificationType.MENTION)
        if not note.dedupe_key.startswith("earlier:")
    ]
    assert sorted(note.email_mode.value for note in fresh) == ["immediate", "off"]


async def test_nested_tokens_cannot_keep_a_chosen_label(api: AsUser, team: Team) -> None:
    """Review L1: rewriting the inner (unknown) token used to leave the outer one as a
    new token with the attacker's label."""
    ghost = uuid4()
    body = f"@[Bob @[CEO Jane](user:{ghost})](user:{team.owner.id}) hi"

    item = await comment(api, team, body)

    stored = item["comment"]["body_md"]
    assert stored == f"@[Olive Owner](user:{team.owner.id}) hi"


async def test_every_token_left_in_a_comment_is_canonical(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    ghost = uuid4()
    deep = f"@[x](user:{ghost})"
    for _ in range(5):
        deep = f"@[a {deep}](user:{ghost})"
    body = f"{deep} @[b @[c](user:{ghost})](user:{team.viewer.id})"

    stored = (await comment(api, team, body))["comment"]["body_md"]

    tokens = list(MENTION_PATTERN.finditer(stored))
    assert [(m.group("label"), m.group("user_id")) for m in tokens] == [
        (team.viewer.display_name, str(team.viewer.id))
    ]


async def test_nested_tokens_count_towards_the_mention_limit(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    """Review L1: 25 tokens wrapped around one unknown token were counted as one."""
    ghost = uuid4()
    people = [await make_user(db_session) for _ in range(MAX_MENTIONS + 5)]
    member = await api(team.member)
    idea = await member.create_idea(team.slug)
    body = " ".join(f"@[x@[y](user:{ghost})](user:{person.id})" for person in people)

    response = await member.post(f"/ideas/{idea['key']}/comments", {"body_md": body})

    assert_problem(response, 422, "too_many_mentions")


async def test_the_mention_email_cap_holds_for_concurrent_comments(
    api: AsUser, team: Team, outbox: Outbox, db_session: AsyncSession
) -> None:
    """Review M2: parallel comments each read the count before any committed (160
    emails in an hour, cap 50)."""
    project = await db_session.get(Project, team.project.id)
    assert project is not None
    people = [await make_user(db_session) for _ in range(MAX_MENTIONS)]
    for person in people:
        await add_member(db_session, project, person, ProjectRole.MEMBER)
    await db_session.commit()
    member = await api(team.member)
    ideas = [(await member.create_idea(team.slug))["key"] for _ in range(4)]
    body = " ".join(token(person.id) for person in people)

    responses = await asyncio.gather(
        *(member.post(f"/ideas/{key}/comments", {"body_md": body}) for key in ideas)
    )

    assert [response.status_code for response in responses] == [201] * 4
    mentions = await outbox.notifications(type_=NotificationType.MENTION)
    assert len(mentions) == 4 * MAX_MENTIONS
    emailed = [note for note in mentions if note.email_mode is not NotificationMode.OFF]
    assert len(emailed) == MENTION_EMAIL_CAP


async def test_a_mention_email_is_cancelled_once_the_recipient_has_no_role(
    api: AsUser, team: Team, outbox: Outbox, runtime: Runtime, db_session: AsyncSession
) -> None:
    """Review nit: mentions reach people with a role in the project; at send time that
    was not checked again (Vic can still view the now internal project)."""
    await comment(api, team, f"cc {token(team.viewer.id)}")
    email = (await outbox.emails(team.viewer.id))[0]
    project = await db_session.get(Project, team.project.id)
    assert project is not None
    project.visibility = ProjectVisibility.INTERNAL
    await db_session.execute(
        delete(ProjectMember).where(
            ProjectMember.project_id == team.project.id,
            ProjectMember.user_id == team.viewer.id,
        )
    )
    await db_session.commit()

    assert await delivery.send_email(runtime, email.id) == "cancelled"
    assert (await outbox.email(email.id)).last_error == "Not sent: no longer applies"
