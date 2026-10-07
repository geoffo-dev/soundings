"""``soundings anonymise-user <email>`` (security review P7 L5, operator guide "What is
stored about users"): a deactivated account loses its name, address, identities and
external ids; keys are revoked, sessions, inbox and outbox go; mentions show the
placeholder; ideas, evaluations, comments and the audit trail stay under it."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import cli
from app.config import Settings
from app.models.activity import AuditLog, Comment
from app.models.api_key import ApiKey
from app.models.enums import AuthMethod, ProjectRole
from app.models.idea import Idea
from app.models.notification import Notification
from app.models.user import User, UserExternalId, UserIdentity, UserSession
from app.services.anonymise import AnonymiseRefused, anonymise_user
from app.services.sessions import start_session
from tests.api_keys.helpers import make_key
from tests.conftest import Login
from tests.factories import make_idea, make_project, make_user

API = "/api/v1"


async def count(db: AsyncSession, model: Any, *where: Any) -> int:
    return int(await db.scalar(select(func.count()).select_from(model).where(*where)) or 0)


async def test_a_deactivated_leaver_is_anonymised_and_their_work_stays(
    login: Login, db_session: AsyncSession, settings: Settings
) -> None:
    admin = await make_user(db_session, "Ada Admin", platform_admin=True)
    leaver = await make_user(db_session, "Lee Leaver", email="Lee.Leaver@example.com")
    colleague = await make_user(db_session, "Cam Colleague")
    project = await make_project(
        db_session,
        members={
            leaver: ProjectRole.MEMBER,
            colleague: ProjectRole.MEMBER,
            admin: ProjectRole.ADMIN,
        },
    )
    idea = await make_idea(
        db_session, project, title="Lee's idea", submitted_by=leaver, owner=leaver
    )
    db_session.add_all(
        [
            UserIdentity(user_id=leaver.id, issuer="https://idp.example.com", subject="lee-1"),
            UserExternalId(user_id=leaver.id, kind="employee_id", value="E-1234"),
        ]
    )
    await db_session.commit()
    key = await make_key(db_session, leaver, scopes=["read"])
    await start_session(db_session, leaver, settings=settings, auth_method=AuthMethod.DEV_LOGIN)
    await db_session.commit()
    cam = await login(colleague)
    mention = f"Thanks @[Lee Leaver](user:{leaver.id}), and @[Cam Colleague](user:{colleague.id})"
    posted = await cam.post(f"{API}/ideas/{idea.id}/comments", json={"body_md": mention})
    assert posted.status_code == 201, posted.text
    assert await count(db_session, Notification, Notification.user_id == leaver.id) == 1
    ada = await login(admin)
    deactivated = await ada.patch(f"{API}/admin/users/{leaver.id}", json={"is_active": False})
    assert deactivated.status_code == 200, deactivated.text

    done = await anonymise_user(db_session, "lee.leaver@EXAMPLE.com")
    await db_session.commit()

    row = await db_session.get(User, leaver.id, populate_existing=True)
    assert row is not None
    assert row.display_name == f"Former user {leaver.id.hex[:8]}" == done.display_name
    assert row.email == f"former-user-{leaver.id.hex}@anonymised.invalid"
    assert row.avatar_url is None
    assert not row.is_active
    assert await count(db_session, UserIdentity, UserIdentity.user_id == leaver.id) == 0
    assert await count(db_session, UserExternalId, UserExternalId.user_id == leaver.id) == 0
    assert await count(db_session, UserSession, UserSession.user_id == leaver.id) == 0
    assert await count(db_session, Notification, Notification.user_id == leaver.id) == 0
    assert (
        await count(db_session, ApiKey, ApiKey.user_id == leaver.id, ApiKey.revoked_at.is_(None))
        == 0
    )
    # Their work stays, under the placeholder.
    kept = await db_session.get(Idea, idea.id, populate_existing=True)
    assert kept is not None
    assert kept.owner_id == leaver.id
    comment = await db_session.scalar(select(Comment).execution_options(populate_existing=True))
    assert comment is not None
    assert f"@[{done.display_name}](user:{leaver.id})" in comment.body_md
    assert "Lee Leaver" not in comment.body_md
    assert f"@[Cam Colleague](user:{colleague.id})" in comment.body_md
    [entry] = list(
        await db_session.scalars(select(AuditLog).where(AuditLog.action == "user.anonymise"))
    )
    assert entry.actor_id is None
    assert entry.target_id == leaver.id
    assert entry.details == {
        "identities": 1,
        "external_ids": 1,
        "api_keys": 0,  # deactivation revoked it already
        "sessions": 0,  # and ended the sessions
        "notifications": 1,
        "emails": 0,
        "mentions": 1,
    }
    assert "Lee" not in str(entry.details)
    assert "example.com" not in str(entry.details)
    # The colleague's view: the placeholder everywhere.
    shown = (await ada.get(f"{API}/ideas/{idea.id}")).json()
    assert shown["owner"]["display_name"] == done.display_name
    assert key  # the key string itself is never stored


@pytest.mark.parametrize(
    ("kind", "message"),
    [
        ("active", "Deactivate the account first"),
        ("service", "AI agent"),
        ("missing", "No account"),
    ],
)
async def test_refusals(db_session: AsyncSession, kind: str, message: str) -> None:
    user = await make_user(
        db_session, "Still Here", active=kind != "active", service_account=kind == "service"
    )
    if kind == "active":
        user.is_active = True
        await db_session.commit()
    email = "nobody@example.com" if kind == "missing" else user.email
    user_id = user.id

    with pytest.raises(AnonymiseRefused, match=message):
        await anonymise_user(db_session, email)
    await db_session.rollback()
    row = await db_session.get(User, user_id, populate_existing=True)
    assert row is not None
    assert row.display_name == "Still Here"


def test_the_cli_anonymises_and_explains_refusals(
    database_url: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from app.db import create_engine, create_sessionmaker
    from tests.conftest import make_settings

    settings = make_settings(environment="test", database_url=database_url)
    monkeypatch.setattr(cli, "get_database_settings", lambda: settings)

    async def arrange() -> tuple[str, str]:
        engine = create_engine(settings)
        try:
            async with create_sessionmaker(engine)() as db:
                gone = await make_user(db, "Gone Person", active=False)
                here = await make_user(db, "Here Person")
                return gone.email, here.email
        finally:
            await engine.dispose()

    gone, here = asyncio.run(arrange())

    assert cli.main(["anonymise-user", gone]) == 0
    assert "Anonymised user" in capsys.readouterr().out
    assert cli.main(["anonymise-user", here]) == 1
    assert "Deactivate the account first" in capsys.readouterr().err
