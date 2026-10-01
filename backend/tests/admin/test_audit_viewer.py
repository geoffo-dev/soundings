"""The audit log viewer (contract-phase2 section 3.11): newest first with a cursor,
every filter, references resolved in batches (null once the thing is gone), and the
closed set of actions."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import AuditLog
from app.models.base import utcnow
from app.models.group import Group
from app.models.user import User
from app.schemas.audit import AuditAction
from app.services import audit
from tests.admin.conftest import AsUser, People, assert_problem, make_group, ok
from tests.factories import make_idea


async def write(
    db: AsyncSession,
    action: str,
    *,
    minutes_ago: float,
    actor_id: UUID | None = None,
    target_type: str | None = None,
    target_id: UUID | None = None,
    project_id: UUID | None = None,
    details: dict[str, Any] | None = None,
) -> AuditLog:
    entry = await audit.record(
        db,
        action,
        actor=actor_id,
        target_type=target_type,
        target_id=target_id,
        project_id=project_id,
        details=details,
    )
    entry.created_at = utcnow() - timedelta(minutes=minutes_ago)
    await db.commit()
    return entry


def test_the_closed_set_is_exactly_the_contract_enum() -> None:
    assert {action.value for action in AuditAction} == audit.AUDIT_ACTIONS


async def test_newest_first_with_resolved_references(
    api: AsUser, people: People, db_session: AsyncSession
) -> None:
    idea = await make_idea(db_session, people.project, submitted_by=people.bob)
    group = await make_group(db_session, "Tools team")
    project_id = people.project.id
    await db_session.execute(delete(AuditLog))  # only the entries written below
    await db_session.commit()
    denied = await write(
        db_session,
        "session.sign_in_denied",
        minutes_ago=50,
        target_type="user",
        target_id=people.carol.id,
        details={"method": "sso", "reason": "account_disabled"},
    )
    status = await write(
        db_session,
        "idea.status_change",
        minutes_ago=40,
        actor_id=people.lead.id,
        target_type="idea",
        target_id=idea.id,
        project_id=project_id,
        details={"rule": "idea.change_status", "from": "new", "to": "evaluating"},
    )
    granted = await write(
        db_session,
        "project.group_grant_add",
        minutes_ago=30,
        actor_id=people.admin.id,
        target_type="group",
        target_id=group.id,
        project_id=project_id,
        details={"rule": "project.manage_members", "role": "member"},
    )
    renamed = await write(
        db_session,
        "project.update",
        minutes_ago=20,
        actor_id=people.admin.id,
        target_type="project",
        target_id=project_id,
        project_id=project_id,
        details={"rule": "project.edit_settings", "fields": ["name"]},
    )
    gone = await write(
        db_session,
        "group.delete",
        minutes_ago=10,
        actor_id=uuid4(),  # a user that no longer exists
        target_type="group",
        target_id=uuid4(),
        project_id=uuid4(),
        details={"rule": "platform.manage_groups", "member_count": 0, "project_ids": []},
    )
    admin = await api(people.admin)  # signing in adds a session.sign_in entry (now)

    written = [a.value for a in AuditAction if a is not AuditAction.SESSION_SIGN_IN]
    page = ok(await admin.get("/admin/audit", action=written))

    ids = [item["id"] for item in page["items"]]
    assert ids == [str(e.id) for e in (gone, renamed, granted, status, denied)]
    by_id = {item["id"]: item for item in page["items"]}
    assert by_id[str(denied.id)]["actor_id"] is None
    assert by_id[str(denied.id)]["actor"] is None
    assert by_id[str(denied.id)]["target_label"] == "Carol Chen"
    assert by_id[str(denied.id)]["details"] == {"method": "sso", "reason": "account_disabled"}
    assert by_id[str(status.id)]["target_label"] == f"TOOLS-{idea.number}"
    assert by_id[str(status.id)]["actor"]["display_name"] == "Lena Lead"
    assert by_id[str(status.id)]["project"] == {
        "id": str(project_id),
        "slug": "internal-tools",
        "key": "TOOLS",
        "name": "Internal Tools",
    }
    assert by_id[str(granted.id)]["target_label"] == "Tools team"
    assert by_id[str(renamed.id)]["target_type"] == "project"
    assert by_id[str(renamed.id)]["target_label"] == "Internal Tools"
    assert by_id[str(gone.id)]["actor"] is None
    assert by_id[str(gone.id)]["actor_id"] == str(gone.actor_id)
    assert by_id[str(gone.id)]["target_label"] is None
    assert by_id[str(gone.id)]["project"] is None
    assert set(by_id[str(gone.id)]) == {
        "id",
        "created_at",
        "action",
        "actor_id",
        "actor",
        "target_type",
        "target_id",
        "target_label",
        "project",
        "details",
    }

    # The sign-in that just happened is the newest entry overall.
    everything = ok(await admin.get("/admin/audit"))
    assert everything["items"][0]["action"] == "session.sign_in"
    assert everything["items"][0]["actor"]["display_name"] == "Alice Anders"


async def test_filters_combine(api: AsUser, people: People, db_session: AsyncSession) -> None:
    group = await make_group(db_session, "Tools team")
    other_project = uuid4()
    a = await write(
        db_session,
        "group.create",
        minutes_ago=30,
        actor_id=people.admin.id,
        target_type="group",
        target_id=group.id,
        details={"rule": "platform.manage_groups"},
    )
    b = await write(
        db_session,
        "group.update",
        minutes_ago=20,
        actor_id=people.other_admin.id,
        target_type="group",
        target_id=group.id,
        details={"rule": "platform.manage_groups", "fields": ["name"]},
    )
    c = await write(
        db_session,
        "project.member_add",
        minutes_ago=10,
        actor_id=people.lead.id,
        target_type="user",
        target_id=people.bob.id,
        project_id=other_project,
        details={"rule": "project.manage_members", "role": "member"},
    )
    admin = await api(people.admin)

    async def ids(**params: Any) -> list[str]:
        return [item["id"] for item in ok(await admin.get("/admin/audit", **params))["items"]]

    since = (utcnow() - timedelta(minutes=25)).isoformat()
    until = (utcnow() - timedelta(minutes=15)).isoformat()
    assert await ids(actor_id=str(people.other_admin.id)) == [str(b.id)]
    assert await ids(action=["group.create", "group.update"]) == [str(b.id), str(a.id)]
    assert await ids(target_type="group", target_id=str(group.id)) == [str(b.id), str(a.id)]
    assert await ids(target_type="user", target_id=str(people.bob.id)) == [str(c.id)]
    assert await ids(target_id=str(people.bob.id)) == [str(c.id)]
    assert await ids(project_id=str(other_project)) == [str(c.id)]
    assert await ids(since=since, until=until) == [str(b.id)]
    assert await ids(since=since, action="group.update", actor_id=str(people.admin.id)) == []
    # until is exclusive, since inclusive.
    assert await ids(until=a.created_at.isoformat(), action="group.create") == []
    assert await ids(since=a.created_at.isoformat(), action="group.create") == [str(a.id)]

    assert_problem(await admin.get("/admin/audit", action="user.teleport"), 422, "validation_error")
    assert_problem(await admin.get("/admin/audit", target_type="comment"), 422, "validation_error")
    naive = await admin.get("/admin/audit", since="2026-10-01T00:00:00")
    assert_problem(naive, 422, "validation_error")
    assert_problem(await admin.get("/admin/audit", cursor="abc"), 400, "invalid_cursor")


async def test_pages_with_a_cursor(api: AsUser, people: People, db_session: AsyncSession) -> None:
    for minutes in range(7, 0, -1):
        await write(
            db_session,
            "user.sessions_end",
            minutes_ago=minutes,
            actor_id=people.admin.id,
            target_type="user",
            target_id=people.bob.id,
            details={"rule": "platform.manage_users", "count": minutes},
        )
    admin = await api(people.admin)

    seen: list[int] = []
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {"limit": 3, "action": "user.sessions_end"}
        if cursor:
            params["cursor"] = cursor
        page = ok(await admin.get("/admin/audit", **params))
        seen += [item["details"]["count"] for item in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break

    assert seen == [1, 2, 3, 4, 5, 6, 7]


async def test_entries_written_by_the_api_record_the_session_method(
    api: AsUser, people: People, db_session: AsyncSession
) -> None:
    admin = await api(people.admin)

    created = ok(await admin.post("/admin/groups", {"name": "Leads"}), 201)
    page = ok(await admin.get("/admin/audit", action="group.create"))

    [entry] = page["items"]
    assert entry["target_id"] == created["id"]
    assert entry["target_label"] == "Leads"
    assert entry["details"]["auth_method"] == "dev_login"
    assert entry["actor"]["id"] == str(people.admin.id)
    # Deleted later: the label goes, the id stays.
    await db_session.execute(delete(Group).where(Group.id == UUID(created["id"])))
    await db_session.commit()
    [after] = ok(await admin.get("/admin/audit", action="group.create"))["items"]
    assert after["target_label"] is None
    assert after["target_id"] == created["id"]
    assert await db_session.get(User, people.admin.id) is not None
