"""The admin "test mapping" box (contract-phase2 section 3.12): the same extraction and
sync rules as sign-in, for pasted claims and optionally a user, writing nothing."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.group_mapping import preview_group_mapping
from app.config import Settings
from app.errors import ProblemError
from app.models.activity import AuditLog
from app.models.enums import GroupSyncMode, ProjectRole
from app.models.group import GroupMembership
from tests.factories import add_member, make_project, make_user
from tests.identity.helpers import ISSUER, add_to_group, grant, make_group, memberships


@pytest.fixture
def settings_overrides() -> dict[str, Any]:
    return {"oidc_issuer": ISSUER, "oidc_groups_claim": "groups"}


def effects(result: Any) -> list[tuple[str, str, list[str], bool]]:
    return [
        (group.group.name, group.effect, group.matched_values, group.manual)
        for group in result.groups
    ]


def roles(result: Any) -> list[tuple[str, str, list[str]]]:
    return [
        (
            item.project.name,
            item.role.value,
            [source.group.name if source.group else "direct" for source in item.sources],
        )
        for item in result.project_roles
    ]


async def test_without_a_user(db_session: AsyncSession, settings: Settings) -> None:
    project = await make_project(db_session, name="Tools project")
    tools = await make_group(db_session, "Tools", idp_values=["/tools/members"])
    await make_group(db_session, "Unrelated", idp_values=["/other"])
    await grant(db_session, project, tools, ProjectRole.MEMBER)
    claims = {"sub": "x", "groups": ["/Tools/Members", "/tools/members/", 7, " / ", "/new"]}

    result = await preview_group_mapping(db_session, settings, claims, None)

    assert result.groups_claim == "groups"
    assert result.claim_found is True
    assert result.values == ["new", "tools/members"]
    assert result.ignored_count == 2
    assert effects(result) == [("Tools", "add", ["tools/members"], False)]
    assert roles(result) == [("Tools project", "member", ["Tools"])]


async def test_for_a_user(db_session: AsyncSession, settings: Settings) -> None:
    carol = await make_user(db_session, "Carol")
    direct = await make_project(db_session, name="Direct project")
    tools_project = await make_project(db_session, name="Tools project")
    await add_member(db_session, direct, carol, ProjectRole.VIEWER)
    keep = await make_group(db_session, "A keep (synced, matches)", idp_values=["/a"])
    add_manual = await make_group(db_session, "B manual, matches", idp_values=["/b"])
    remove = await make_group(db_session, "C synced, gone", idp_values=["/c"])
    additive = await make_group(
        db_session, "D additive, gone", idp_values=["/d"], sync_mode=GroupSyncMode.ADDITIVE
    )
    manual_only = await make_group(db_session, "E manual only", idp_values=["/e"])
    both_gone = await make_group(db_session, "F manual and synced, gone", idp_values=["/f"])
    await add_to_group(db_session, keep, carol, manual=False, synced=True)
    await add_to_group(db_session, add_manual, carol, manual=True, synced=False)
    await add_to_group(db_session, remove, carol, manual=False, synced=True)
    await add_to_group(db_session, additive, carol, manual=False, synced=True)
    await add_to_group(db_session, manual_only, carol, manual=True, synced=False)
    await add_to_group(db_session, both_gone, carol, manual=True, synced=True)
    await grant(db_session, tools_project, remove, ProjectRole.ADMIN)
    await grant(db_session, tools_project, manual_only, ProjectRole.MEMBER)
    await grant(db_session, direct, keep, ProjectRole.MEMBER)
    before = await memberships(db_session, carol)

    result = await preview_group_mapping(db_session, settings, {"groups": ["/a", "/b"]}, carol.id)

    assert effects(result) == [
        ("A keep (synced, matches)", "keep", ["a"], False),
        ("B manual, matches", "add", ["b"], True),
        ("C synced, gone", "remove", [], False),
        ("D additive, gone", "keep", [], False),
        ("F manual and synced, gone", "remove", [], True),
    ]
    # After the sync: C's admin grant is gone, E (manual) still grants member.
    assert roles(result) == [
        ("Direct project", "member", ["direct", "A keep (synced, matches)"]),
        ("Tools project", "member", ["E manual only"]),
    ]
    # Nothing written, nothing audited.
    assert await memberships(db_session, carol) == before
    assert await db_session.scalar(select(func.count()).select_from(AuditLog)) == 0


async def test_missing_claim(db_session: AsyncSession, settings: Settings) -> None:
    carol = await make_user(db_session, "Carol")
    tools = await make_group(db_session, "Tools", idp_values=["/tools"])
    await add_to_group(db_session, tools, carol, manual=False, synced=True)

    result = await preview_group_mapping(db_session, settings, {"sub": "x"}, carol.id)

    assert (result.claim_found, result.values, result.ignored_count) == (False, [], 0)
    assert effects(result) == [("Tools", "remove", [], False)]


@pytest.mark.settings(oidc_groups_claim="")
async def test_group_sync_off(db_session: AsyncSession, settings: Settings) -> None:
    carol = await make_user(db_session, "Carol")
    tools = await make_group(db_session, "Tools", idp_values=["/tools"])
    await add_to_group(db_session, tools, carol, manual=False, synced=True)

    result = await preview_group_mapping(db_session, settings, {"groups": ["/tools"]}, carol.id)

    assert result.groups_claim is None
    assert (result.claim_found, result.values, result.groups) == (False, [], [])


@pytest.mark.settings(oidc_groups_claim="realm_access.roles")
async def test_nested_claim_path(db_session: AsyncSession, settings: Settings) -> None:
    await make_group(db_session, "Reviewers", idp_values=["reviewer"])

    result = await preview_group_mapping(
        db_session, settings, {"realm_access": {"roles": ["Reviewer"]}}, None
    )

    assert result.groups_claim == "realm_access.roles"
    assert effects(result) == [("Reviewers", "add", ["reviewer"], False)]


async def test_unknown_user_is_422(db_session: AsyncSession, settings: Settings) -> None:
    with pytest.raises(ProblemError) as raised:
        await preview_group_mapping(db_session, settings, {}, uuid4())

    assert (raised.value.status, raised.value.code) == (422, "user_not_found")


async def test_preview_matches_what_sign_in_does(
    db_session: AsyncSession, settings: Settings
) -> None:
    from app.auth.group_sync import sync_groups

    carol = await make_user(db_session, "Carol")
    a = await make_group(db_session, "A", idp_values=["/a"])
    b = await make_group(db_session, "B", idp_values=["/b"], sync_mode=GroupSyncMode.ADDITIVE)
    c = await make_group(db_session, "C", idp_values=["/c"])
    await add_to_group(db_session, b, carol, manual=False, synced=True)
    await add_to_group(db_session, c, carol, manual=True, synced=True)
    claims = {"groups": ["/a"]}

    preview = await preview_group_mapping(db_session, settings, claims, carol.id)
    await sync_groups(db_session, carol, claims, settings)
    await db_session.commit()

    after = await memberships(db_session, carol)
    expected_members = {
        group.group.id for group in preview.groups if group.effect != "remove" or group.manual
    }
    assert set(after) == expected_members == {a.id, b.id, c.id}
    assert after[c.id] == (True, False)
    assert await db_session.scalar(select(func.count()).select_from(GroupMembership)) == 3
