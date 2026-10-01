"""Reading the ID token's claims (contract-phase2 sections 3.3 and 3.5): claim paths,
the groups claim, the external-ID claim, the verified email and the display name.

Pure functions; the same code runs at sign-in and in the admin "test mapping" box.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from app.auth.group_mapping import (
    MAX_GROUP_ELEMENTS,
    GroupClaim,
    Membership,
    display_name_from_claims,
    email_from_claims,
    external_id_from_claims,
    extract_groups,
    groups_overage,
    plan_group_sync,
    resolve_claim,
)
from app.models.enums import GroupSyncMode

MANAGED, ADDITIVE = GroupSyncMode.MANAGED, GroupSyncMode.ADDITIVE


# --- Claim paths --------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("claims", "path", "expected"),
    [
        ({"groups": ["a"]}, "groups", (True, ["a"])),
        ({"realm_access": {"roles": ["r"]}}, "realm_access.roles", (True, ["r"])),
        # The whole string as a top-level name wins (claim names may contain dots).
        (
            {"https://example.com/groups": ["x"], "https://example": {"com/groups": ["y"]}},
            "https://example.com/groups",
            (True, ["x"]),
        ),
        ({"a": {"b": {"c": 1}}}, "a.b.c", (True, 1)),
        ({"a": {"b": None}}, "a.b", (True, None)),
        ({"a": {"b": 1}}, "a.b.c", (False, None)),  # a non-object on the way
        ({"a": ["b"]}, "a.b", (False, None)),
        ({"a": {}}, "a.b", (False, None)),  # a missing segment
        ({}, "groups", (False, None)),
        ({"groups": ["a"]}, "", (False, None)),  # not configured
    ],
)
def test_resolve_claim(claims: dict[str, Any], path: str, expected: tuple[bool, Any]) -> None:
    assert resolve_claim(claims, path) == expected


# --- The groups claim ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("value", "values", "ignored"),
    [
        (["/Innovation/Admins", "/tools/members"], ("innovation/admins", "tools/members"), 0),
        ("/viewers", ("viewers",), 0),  # a string is one element
        (["b", "a", "A", " /a/ ", "b"], ("a", "b"), 0),  # normalised, de-duplicated, sorted
        (["ok", 7, None, {"x": 1}, ["y"], True, " / ", ""], ("ok",), 7),
        ({"not": "a list"}, (), 1),
        (42, (), 1),
        (True, (), 1),
        ([], (), 0),
        (None, (), 0),  # null: no values, nothing ignored
        (["innovation/admins"], ("innovation/admins",), 0),
        (["/innovation/admins"], ("innovation/admins",), 0),  # same value either way
    ],
)
def test_extract_groups_values(value: object, values: tuple[str, ...], ignored: int) -> None:
    result = extract_groups({"groups": value}, "groups")

    assert result == GroupClaim(claim_found=True, values=values, ignored_count=ignored)


def test_missing_groups_claim_is_no_groups() -> None:
    assert extract_groups({"sub": "x"}, "groups") == GroupClaim(False, (), 0)


def test_group_sync_off_extracts_nothing() -> None:
    assert extract_groups({"groups": ["a"]}, "") == GroupClaim(False, (), 0)


def test_inner_path_segments_are_kept() -> None:
    # "admins" is not "innovation/admins": same-named subgroups never match each other.
    result = extract_groups({"groups": ["/innovation/admins", "/other/admins"]}, "groups")

    assert result.values == ("innovation/admins", "other/admins")


def test_nested_groups_claim() -> None:
    claims = {"realm_access": {"roles": ["offline_access", "Reviewer"]}}

    assert extract_groups(claims, "realm_access.roles").values == ("offline_access", "reviewer")


def test_only_the_first_thousand_elements_count() -> None:
    elements = [f"g{n:04}" for n in range(MAX_GROUP_ELEMENTS + 5)]

    result = extract_groups({"groups": elements}, "groups")

    assert len(result.values) == MAX_GROUP_ELEMENTS
    assert "g1000" not in result.values
    assert result.ignored_count == 5


@pytest.mark.parametrize(
    ("claims", "overage"),
    [
        ({"_claim_names": {"groups": "src1"}, "_claim_sources": {}}, True),
        ({"_claim_names": {"groups": "src1"}, "groups": ["a"]}, False),  # the claim is there
        ({"_claim_names": {"other": "src1"}}, False),
        ({"_claim_names": "groups"}, False),  # not an object
        ({}, False),
    ],
)
def test_entra_group_overage(claims: dict[str, Any], overage: bool) -> None:
    assert groups_overage(claims, "groups") is overage


def test_group_overage_needs_group_sync() -> None:
    assert groups_overage({"_claim_names": {"groups": "src1"}}, "") is False


# --- External ID ------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("E1002", "E1002"),
        ("  E1002 ", "E1002"),
        (1002, "1002"),  # an integer counts as its decimal string
        ("x" * 200, "x" * 200),
        ("x" * 201, None),
        ("", None),
        ("   ", None),
        (None, None),
        (True, None),  # booleans are not integers here
        (12.5, None),
        (["E1"], None),
        ({"v": "E1"}, None),
    ],
)
def test_external_id_claim(value: object, expected: str | None) -> None:
    assert external_id_from_claims({"employee_no": value}, "employee_no") == expected


def test_external_id_claim_missing_or_unconfigured() -> None:
    assert external_id_from_claims({"sub": "x"}, "employee_no") is None
    assert external_id_from_claims({"employee_no": "E1"}, "") is None
    assert external_id_from_claims({"attributes": {"emp": "E1"}}, "attributes.emp") == "E1"


# --- Verified email ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("claims", "address", "verified"),
    [
        ({"email": "Erin@Example.com", "email_verified": True}, "Erin@Example.com", True),
        ({"email": "erin@example.com", "email_verified": "true"}, "erin@example.com", True),
        ({"email": "erin@example.com", "email_verified": "TRUE"}, "erin@example.com", True),
        ({"email": "erin@example.com", "email_verified": False}, "erin@example.com", False),
        ({"email": "erin@example.com", "email_verified": "false"}, "erin@example.com", False),
        ({"email": "erin@example.com", "email_verified": 1}, "erin@example.com", False),
        ({"email": "erin@example.com"}, "erin@example.com", False),  # missing = unverified
        ({"email": "not-an-address", "email_verified": True}, None, False),
        ({"email": "a@" + "x" * 320, "email_verified": True}, None, False),
        ({"email": 42, "email_verified": True}, None, False),
        ({"email": "break-glass@soundings.invalid", "email_verified": True}, None, False),
        ({"email": "x@Foo.INVALID", "email_verified": True}, None, False),
        ({"email": "break-glass@soundings.invalid.", "email_verified": True}, None, False),
        ({"email_verified": True}, None, False),
    ],
)
def test_email_claim(claims: dict[str, Any], address: str | None, verified: bool) -> None:
    email = email_from_claims(claims)

    assert (email.address, email.verified) == (address, verified)


# --- Display name -----------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("claims", "expected"),
    [
        ({"name": "  Nia Lee ", "preferred_username": "nia"}, "Nia Lee"),
        ({"name": "", "preferred_username": "nia"}, "nia"),
        ({"name": 7, "preferred_username": " nia "}, "nia"),
        ({}, "nia.lee"),
        ({"name": "N" * 150}, "N" * 100),
    ],
)
def test_display_name(claims: dict[str, Any], expected: str) -> None:
    assert display_name_from_claims(claims, "nia.lee@example.com") == expected


# --- What sync does (section 3.6), every cell of the table, both modes ---------------------------
G = uuid4()

NONE = None
MANUAL = Membership(manual=True, synced=False)
SYNCED = Membership(manual=False, synced=True)
BOTH = Membership(manual=True, synced=True)


@pytest.mark.parametrize(
    ("before", "matched", "mode", "effect", "after"),
    [
        # The group matches the claims.
        (NONE, True, MANAGED, "add", SYNCED),
        (MANUAL, True, MANAGED, "add", BOTH),
        (SYNCED, True, MANAGED, "keep", SYNCED),
        (BOTH, True, MANAGED, "keep", BOTH),
        (NONE, True, ADDITIVE, "add", SYNCED),
        (MANUAL, True, ADDITIVE, "add", BOTH),
        (SYNCED, True, ADDITIVE, "keep", SYNCED),
        (BOTH, True, ADDITIVE, "keep", BOTH),
        # It doesn't: managed groups lose the synced membership, additive ones keep it.
        (SYNCED, False, MANAGED, "remove", NONE),
        (BOTH, False, MANAGED, "remove", MANUAL),
        (SYNCED, False, ADDITIVE, "keep", SYNCED),
        (BOTH, False, ADDITIVE, "keep", BOTH),
    ],
)
def test_sync_table(
    before: Membership | None,
    matched: bool,
    mode: GroupSyncMode,
    effect: str,
    after: Membership | None,
) -> None:
    [change] = plan_group_sync(
        matched={G: (mode, ("innovation/admins",))} if matched else {},
        memberships={G: (mode, before)} if before else {},
    )

    assert change.group_id == G
    assert change.effect == effect
    assert change.before == before
    assert change.after == after
    assert change.sync_mode == mode
    assert change.matched_values == (("innovation/admins",) if matched else ())
    assert change.changed == (before != after)


@pytest.mark.parametrize("mode", [MANAGED, ADDITIVE])
def test_manual_only_membership_that_does_not_match_is_untouched(mode: GroupSyncMode) -> None:
    assert plan_group_sync(matched={}, memberships={G: (mode, MANUAL)}) == []


def test_sync_plan_is_ordered_and_complete() -> None:
    a, b, c, d = sorted(uuid4() for _ in range(4))
    plan = plan_group_sync(
        matched={b: (MANAGED, ("x",)), a: (ADDITIVE, ("y", "z"))},
        memberships={c: (MANAGED, SYNCED), d: (MANAGED, MANUAL), b: (MANAGED, SYNCED)},
    )

    assert [(change.group_id, change.effect) for change in plan] == [
        (a, "add"),
        (b, "keep"),
        (c, "remove"),
    ]
    assert plan[0].matched_values == ("y", "z")
