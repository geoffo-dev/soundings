"""Group sync at sign-in (contract-phase2 section 3.6) against Postgres: every cell of
the table in both modes, manual memberships untouched, idempotence, the audit entry,
and the roles that follow (the project_effective_roles view)."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.group_sync import sync_groups
from app.authz import effective_role_of
from app.config import Settings
from app.models.enums import GroupSyncMode, ProjectRole
from app.models.user import User
from tests.factories import make_project, make_user
from tests.identity.helpers import (
    ISSUER,
    add_to_group,
    audit_entries,
    grant,
    make_group,
    memberships,
)

MANAGED, ADDITIVE = GroupSyncMode.MANAGED, GroupSyncMode.ADDITIVE


@pytest.fixture
def settings_overrides() -> dict[str, Any]:
    return {"oidc_issuer": ISSUER, "oidc_groups_claim": "groups"}


def token(*groups: str) -> dict[str, Any]:
    return {"sub": "k-1", "groups": list(groups)}


async def sync(db: AsyncSession, user: User, settings: Settings, claims: dict[str, Any]) -> Any:
    result = await sync_groups(db, user, claims, settings)
    await db.commit()
    return result


# before: None, "manual", "synced", "both"
_FLAGS = {"manual": (True, False), "synced": (False, True), "both": (True, True)}


@pytest.mark.parametrize("mode", [MANAGED, ADDITIVE])
@pytest.mark.parametrize(
    ("before", "matches", "after_managed", "after_additive", "added", "removed_managed"),
    [
        (None, True, "synced", "synced", True, False),
        ("manual", True, "both", "both", True, False),
        ("synced", True, "synced", "synced", False, False),
        ("both", True, "both", "both", False, False),
        (None, False, None, None, False, False),
        ("manual", False, "manual", "manual", False, False),
        ("synced", False, None, "synced", False, True),
        ("both", False, "manual", "both", False, True),
    ],
)
async def test_sync_table(
    db_session: AsyncSession,
    settings: Settings,
    mode: GroupSyncMode,
    before: str | None,
    matches: bool,
    after_managed: str | None,
    after_additive: str | None,
    added: bool,
    removed_managed: bool,
) -> None:
    carol = await make_user(db_session, "Carol")
    group = await make_group(db_session, "Tools", idp_values=["/tools/members"], sync_mode=mode)
    if before is not None:
        manual, synced = _FLAGS[before]
        await add_to_group(db_session, group, carol, manual=manual, synced=synced)

    result = await sync(
        db_session, carol, settings, token("/tools/members") if matches else token()
    )

    after = after_managed if mode is MANAGED else after_additive
    assert (await memberships(db_session, carol)).get(group.id) == (
        _FLAGS[after] if after else None
    )
    removed = removed_managed and mode is MANAGED
    assert result.added_group_ids == ([group.id] if added else [])
    assert result.removed_group_ids == ([group.id] if removed else [])
    entries = await audit_entries(db_session, "user.groups_sync")
    if added or removed:
        [entry] = entries
        assert entry.actor_id == carol.id
        assert (entry.target_type, entry.target_id) == ("user", carol.id)
        assert entry.details == {
            "added_group_ids": [str(group.id)] if added else [],
            "removed_group_ids": [str(group.id)] if removed else [],
            "claim_found": True,
            "auth_method": "sso",
        }
    else:
        assert entries == []  # audited only when something changed


async def test_managed_sync_is_exactly_the_matched_groups(
    db_session: AsyncSession, settings: Settings
) -> None:
    carol = await make_user(db_session, "Carol")
    admins = await make_group(db_session, "Innovation admins", idp_values=["/innovation/admins"])
    members = await make_group(db_session, "Innovation members", idp_values=["innovation/members"])
    tools = await make_group(db_session, "Tools", idp_values=["/tools/members"])
    viewers = await make_group(db_session, "Viewers", idp_values=["/viewers"])
    await add_to_group(db_session, admins, carol, manual=False, synced=True)
    await add_to_group(db_session, viewers, carol, manual=True, synced=False)

    await sync(db_session, carol, settings, token("/Innovation/Members", "/tools/members/"))

    assert await memberships(db_session, carol) == {
        members.id: (False, True),
        tools.id: (False, True),
        viewers.id: (True, False),  # manual: never touched by sync
    }


async def test_one_value_can_map_to_several_groups(
    db_session: AsyncSession, settings: Settings
) -> None:
    carol = await make_user(db_session, "Carol")
    first = await make_group(db_session, "First", idp_values=["/tools/members"])
    second = await make_group(db_session, "Second", idp_values=["/tools/members", "/other"])

    result = await sync(db_session, carol, settings, token("/tools/members"))

    assert sorted(result.added_group_ids) == sorted([first.id, second.id])
    assert set(await memberships(db_session, carol)) == {first.id, second.id}


async def test_subgroups_do_not_inherit_a_parent_mapping(
    db_session: AsyncSession, settings: Settings
) -> None:
    carol = await make_user(db_session, "Carol")
    parent = await make_group(db_session, "Innovation", idp_values=["/innovation"])
    short = await make_group(db_session, "Admins", idp_values=["admins"])

    await sync(db_session, carol, settings, token("/innovation/admins"))

    assert parent.id not in await memberships(db_session, carol)
    assert short.id not in await memberships(db_session, carol)


async def test_sync_is_idempotent(db_session: AsyncSession, settings: Settings) -> None:
    carol = await make_user(db_session, "Carol")
    tools = await make_group(db_session, "Tools", idp_values=["/tools/members"])

    first = await sync(db_session, carol, settings, token("/tools/members"))
    second = await sync(db_session, carol, settings, token("/tools/members"))

    assert first.added_group_ids == [tools.id]
    assert (second.added_group_ids, second.removed_group_ids) == ([], [])
    assert len(await audit_entries(db_session, "user.groups_sync")) == 1


async def test_missing_claim_removes_managed_synced_memberships(
    db_session: AsyncSession, settings: Settings
) -> None:
    carol = await make_user(db_session, "Carol")
    tools = await make_group(db_session, "Tools", idp_values=["/tools/members"])
    keep = await make_group(db_session, "Keep", idp_values=["/keep"], sync_mode=ADDITIVE)
    await add_to_group(db_session, tools, carol, manual=False, synced=True)
    await add_to_group(db_session, keep, carol, manual=False, synced=True)

    result = await sync(db_session, carol, settings, {"sub": "k-1"})  # no groups claim at all

    assert result.claim_found is False
    assert result.removed_group_ids == [tools.id]
    assert await memberships(db_session, carol) == {keep.id: (False, True)}
    [entry] = await audit_entries(db_session, "user.groups_sync")
    assert entry.details["claim_found"] is False


async def test_managed_group_with_an_emptied_mapping_loses_synced_members(
    db_session: AsyncSession, settings: Settings
) -> None:
    carol = await make_user(db_session, "Carol")
    unmapped = await make_group(db_session, "Unmapped")
    await add_to_group(db_session, unmapped, carol, manual=False, synced=True)

    await sync(db_session, carol, settings, token("/tools/members"))

    assert await memberships(db_session, carol) == {}


@pytest.mark.settings(oidc_groups_claim="")
async def test_no_sync_when_the_claim_is_not_configured(
    db_session: AsyncSession, settings: Settings
) -> None:
    carol = await make_user(db_session, "Carol")
    tools = await make_group(db_session, "Tools", idp_values=["/tools/members"])
    await add_to_group(db_session, tools, carol, manual=False, synced=True)

    result = await sync(db_session, carol, settings, {"sub": "k-1"})

    assert result is None
    assert await memberships(db_session, carol) == {tools.id: (False, True)}


@pytest.mark.settings(oidc_groups_claim="realm_access.roles")
async def test_nested_claim_path(db_session: AsyncSession, settings: Settings) -> None:
    carol = await make_user(db_session, "Carol")
    reviewers = await make_group(db_session, "Reviewers", idp_values=["reviewer"])

    await sync(db_session, carol, settings, {"realm_access": {"roles": ["Reviewer", 3]}})

    assert set(await memberships(db_session, carol)) == {reviewers.id}


async def test_other_users_memberships_are_untouched(
    db_session: AsyncSession, settings: Settings
) -> None:
    carol = await make_user(db_session, "Carol")
    dave = await make_user(db_session, "Dave")
    tools = await make_group(db_session, "Tools", idp_values=["/tools/members"])
    await add_to_group(db_session, tools, dave, manual=False, synced=True)

    await sync(db_session, carol, settings, token())

    assert await memberships(db_session, dave) == {tools.id: (False, True)}


async def test_sync_cost_does_not_grow_with_groups(
    db_session: AsyncSession, settings: Settings
) -> None:
    carol = await make_user(db_session, "Carol")
    values = [f"/team/{n}" for n in range(40)]
    for n, value in enumerate(values):
        await make_group(db_session, f"Team {n}", idp_values=[value])
    statements: list[str] = []

    def count(*args: Any, **_: Any) -> None:
        statements.append(str(args[2]))

    engine = db_session.bind.sync_engine  # type: ignore[union-attr]
    event.listen(engine, "before_cursor_execute", count)
    try:
        added = await sync(db_session, carol, settings, token(*values))
        removed = await sync(db_session, carol, settings, token())
    finally:
        event.remove(engine, "before_cursor_execute", count)

    assert len(added.added_group_ids) == 40
    assert len(removed.removed_group_ids) == 40
    assert len(statements) <= 16  # a handful per sign-in, not one per group


# --- The acceptance rule: roles follow the synced memberships -------------------------------
async def test_removing_the_idp_group_removes_project_access_at_next_sync(
    db_session: AsyncSession, settings: Settings
) -> None:
    carol = await make_user(db_session, "Carol")
    project = await make_project(db_session)
    tools = await make_group(db_session, "Tools", idp_values=["/tools/members"])
    await grant(db_session, project, tools, ProjectRole.MEMBER)

    await sync(db_session, carol, settings, token("/tools/members"))
    with_group = await effective_role_of(db_session, carol.id, project.id)
    await sync(db_session, carol, settings, token("/innovation/members"))
    without_group = await effective_role_of(db_session, carol.id, project.id)

    assert with_group is ProjectRole.MEMBER
    assert without_group is None


async def test_manual_membership_keeps_access_when_the_idp_group_goes(
    db_session: AsyncSession, settings: Settings
) -> None:
    carol = await make_user(db_session, "Carol")
    project = await make_project(db_session)
    tools = await make_group(db_session, "Tools", idp_values=["/tools/members"])
    await grant(db_session, project, tools, ProjectRole.MEMBER)
    await add_to_group(db_session, tools, carol, manual=True, synced=False)

    await sync(db_session, carol, settings, token("/tools/members"))
    await sync(db_session, carol, settings, token())

    assert await memberships(db_session, carol) == {tools.id: (True, False)}
    assert await effective_role_of(db_session, carol.id, project.id) is ProjectRole.MEMBER
