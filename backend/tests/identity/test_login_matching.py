"""Login matching (contract-phase2 section 3.3), table-driven from the worked examples.

Steps, first match decides and is final: (issuer, subject) -> external-ID claim ->
verified email (if enabled) -> auto-create with a verified email (if enabled) -> deny.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import login_matching
from app.auth.login_matching import LoginDenied, LoginMatch, match_login
from app.config import Settings
from app.models.user import User, UserIdentity
from app.schemas.auth import LoginErrorCode
from tests.factories import make_user
from tests.identity.helpers import ISSUER, add_external_id, audit_entries, link_identity


@pytest.fixture
def settings_overrides() -> dict[str, Any]:
    return {
        "oidc_issuer": ISSUER,
        "oidc_client_secret": "secret",
        "oidc_external_id_claim": "employee_no",
    }


@dataclass
class Person:
    name: str
    email: str
    active: bool = True
    service_account: bool = False
    break_glass: bool = False
    external_ids: dict[str, str] = field(default_factory=dict)
    linked_subject: str | None = None
    linked_issuer: str = ISSUER


BOB = Person("Bob", "bob@example.com")
ERIN = Person("Erin", "erin@example.com")


@dataclass
class Case:
    claims: dict[str, Any]
    people: list[Person]
    expected: str
    """``"<name> (<matched_by>)"``, or ``"<code> (<reason>)"`` for a denial."""
    settings: dict[str, Any] = field(default_factory=dict)
    target: str | None = None
    """For a denial: whose account the attempt identified (audit target)."""


def bob(**changes: Any) -> Person:
    return Person(**{**BOB.__dict__, **changes})


def erin(**changes: Any) -> Person:
    return Person(**{**ERIN.__dict__, **changes})


VERIFIED = {"email_verified": True}
CASES: dict[str, Case] = {
    # The worked examples of section 3.3 (claim employee_no, email on, auto-create off).
    "identity": Case({"sub": "k-1"}, [bob(linked_subject="k-1")], "Bob (identity)"),
    "external_id": Case(
        {"sub": "k-9", "employee_no": "E1002", "email": "bob@example.com", **VERIFIED},
        [bob(external_ids={"employee_no": "e1002"})],
        "Bob (external_id)",
    ),
    "external_id_already_linked": Case(
        {"sub": "k-9", "employee_no": "E1002"},
        [bob(external_ids={"employee_no": "E1002"}, linked_subject="k-1")],
        "identity_conflict (already_linked)",
        target="Bob",
    ),
    "email": Case(
        {"sub": "k-7", "email": "Erin@Example.com", **VERIFIED}, [erin()], "Erin (email)"
    ),
    "email_with_another_external_id": Case(
        {"sub": "k-7", "employee_no": "E9", "email": "erin@example.com", **VERIFIED},
        [erin(external_ids={"employee_no": "E5"})],
        "identity_conflict (external_id_mismatch)",
        target="Erin",
    ),
    "email_without_the_external_id": Case(
        {"sub": "k-7", "email": "erin@example.com", **VERIFIED},
        [erin(external_ids={"employee_no": "E5"})],
        "identity_conflict (external_id_missing)",
        target="Erin",
    ),
    "email_not_verified": Case(
        {"sub": "k-7", "email": "erin@example.com", "email_verified": False},
        [erin()],
        "no_account (email_not_verified)",
    ),
    "deactivated": Case(
        {"sub": "k-3", "email": "dave@example.com", **VERIFIED},
        [Person("Dave", "dave@example.com", active=False)],
        "account_disabled (account_disabled)",
        target="Dave",
    ),
    "nobody": Case(
        {"sub": "k-5", "email": "new@example.com", **VERIFIED}, [erin()], "no_account (no_match)"
    ),
    "auto_create_unverified": Case(
        {"sub": "k-5", "email": "new@example.com"},
        [],
        "no_account (email_not_verified)",
        settings={"oidc_auto_create_users": True},
    ),
    "auto_create": Case(
        {"sub": "k-5", "email": "new@example.com", "name": "Nia Lee", **VERIFIED},
        [],
        "Nia Lee (created)",
        settings={"oidc_auto_create_users": True},
    ),
    # Further rules.
    "identity_wins_over_everything": Case(
        {"sub": "k-1", "employee_no": "E5", "email": "erin@example.com", **VERIFIED},
        [bob(linked_subject="k-1"), erin(external_ids={"employee_no": "E5"})],
        "Bob (identity)",
    ),
    "identity_of_a_deactivated_user_is_final": Case(
        {"sub": "k-1", "email": "erin@example.com", **VERIFIED},
        [bob(linked_subject="k-1", active=False), erin()],
        "account_disabled (account_disabled)",
        target="Bob",
    ),
    "identity_at_another_issuer_does_not_count": Case(
        {"sub": "k-1", "email": "bob@example.com", **VERIFIED},
        [bob(linked_subject="k-1", linked_issuer="https://other.example.com")],
        "Bob (email)",
    ),
    "external_id_is_final": Case(
        {"sub": "k-9", "employee_no": "E1002", "email": "erin@example.com", **VERIFIED},
        [bob(external_ids={"employee_no": "E1002"}, active=False), erin()],
        "account_disabled (account_disabled)",
        target="Bob",
    ),
    "external_id_integer_claim": Case(
        {"sub": "k-9", "employee_no": 1002},
        [bob(external_ids={"employee_no": "1002"})],
        "Bob (external_id)",
    ),
    "external_id_of_another_kind_does_not_count": Case(
        {"sub": "k-9", "employee_no": "E1002"},
        [bob(external_ids={"gitlab": "E1002"})],
        "no_account (no_match)",
    ),
    "unknown_external_id_falls_through_to_email": Case(
        {"sub": "k-9", "employee_no": "E404", "email": "erin@example.com", **VERIFIED},
        [erin()],
        "Erin (email)",
    ),
    "external_id_matching_off": Case(
        {"sub": "k-9", "employee_no": "E1002"},
        [bob(external_ids={"employee_no": "E1002"})],
        "no_account (no_match)",
        settings={"oidc_external_id_claim": ""},
    ),
    "external_id_matching_off_links_by_email": Case(
        # Without external-ID matching configured, the user's external IDs don't block it.
        {"sub": "k-7", "email": "erin@example.com", **VERIFIED},
        [erin(external_ids={"employee_no": "E5"})],
        "Erin (email)",
        settings={"oidc_external_id_claim": ""},
    ),
    "email_already_linked": Case(
        {"sub": "k-2", "email": "bob@example.com", **VERIFIED},
        [bob(linked_subject="k-1")],
        "identity_conflict (already_linked)",
        target="Bob",
    ),
    "email_matching_off": Case(
        {"sub": "k-7", "email": "erin@example.com", **VERIFIED},
        [erin()],
        "no_account (no_match)",
        settings={"oidc_match_verified_email": False},
    ),
    "email_verified_as_a_string": Case(
        {"sub": "k-7", "email": "erin@example.com", "email_verified": "true"},
        [erin()],
        "Erin (email)",
    ),
    "email_verified_missing": Case(
        {"sub": "k-7", "email": "erin@example.com"}, [erin()], "no_account (email_not_verified)"
    ),
    "service_account_is_never_matched": Case(
        {"sub": "k-7", "email": "agent@example.com", **VERIFIED},
        [Person("Agent", "agent@example.com", service_account=True)],
        "account_disabled (account_disabled)",
        target="Agent",
    ),
    "break_glass_is_never_matched_by_external_id": Case(
        {"sub": "k-7", "employee_no": "BG"},
        [
            Person(
                "Break-glass",
                "bg@example.com",
                break_glass=True,
                external_ids={"employee_no": "BG"},
            )
        ],
        "account_disabled (account_disabled)",
        target="Break-glass",
    ),
    "reserved_email_is_never_used": Case(
        {"sub": "k-7", "email": "break-glass@soundings.invalid", **VERIFIED},
        [Person("Break-glass", "break-glass@soundings.invalid", break_glass=True)],
        "no_account (no_match)",
        settings={"oidc_auto_create_users": True},
    ),
    "auto_create_never_reuses_an_address": Case(
        {"sub": "k-7", "email": "dave@example.com", **VERIFIED},
        [Person("Dave", "dave@example.com", active=False)],
        "identity_conflict (email_taken)",
        settings={"oidc_auto_create_users": True, "oidc_match_verified_email": False},
        target="Dave",
    ),
    "auto_create_falls_back_to_the_username": Case(
        {"sub": "k-5", "email": "nia@example.com", "preferred_username": "nia.lee", **VERIFIED},
        [],
        "nia.lee (created)",
        settings={"oidc_auto_create_users": True},
    ),
    "no_email_at_all": Case({"sub": "k-5"}, [], "no_account (no_match)"),
}


async def arrange(db: AsyncSession, people: list[Person]) -> dict[str, User]:
    users: dict[str, User] = {}
    for person in people:
        user = await make_user(
            db,
            person.name,
            email=person.email,
            active=person.active,
            service_account=person.service_account,
        )
        user.is_break_glass = person.break_glass
        await db.commit()
        for kind, value in person.external_ids.items():
            await add_external_id(db, user, kind, value)
        if person.linked_subject:
            await link_identity(db, user, person.linked_subject, issuer=person.linked_issuer)
        users[person.name] = user
    return users


def describe(result: LoginMatch | LoginDenied) -> str:
    if isinstance(result, LoginMatch):
        return f"{result.user.display_name} ({result.matched_by})"
    return f"{result.code} ({result.reason})"


@pytest.mark.parametrize("name", sorted(CASES))
async def test_login_matching(db_session: AsyncSession, settings: Settings, name: str) -> None:
    case = CASES[name]
    settings = settings.model_copy(update=case.settings)
    users = await arrange(db_session, case.people)
    identities_before = await db_session.scalar(select(func.count()).select_from(UserIdentity))

    result = await match_login(
        db_session, settings, issuer=ISSUER, subject=case.claims["sub"], claims=case.claims
    )
    await db_session.commit()

    assert describe(result) == case.expected
    identities_after = await db_session.scalar(select(func.count()).select_from(UserIdentity))
    if isinstance(result, LoginDenied):
        expected_target = users[case.target].id if case.target else None
        assert result.user_id == expected_target
        assert identities_after == identities_before  # nothing linked
        assert await audit_entries(db_session, "user.identity_link", "user.create") == []
        return
    assert result.identity.issuer == ISSUER
    assert result.identity.subject == case.claims["sub"]
    assert result.identity.user_id == result.user.id
    if result.matched_by == "identity":
        assert identities_after == identities_before
        assert await audit_entries(db_session, "user.identity_link") == []
    else:
        assert identities_after == (identities_before or 0) + 1
        [link] = await audit_entries(db_session, "user.identity_link")
        assert link.actor_id == result.user.id
        assert (link.target_type, link.target_id) == ("user", result.user.id)
        assert link.details == {
            "identity_id": str(result.identity.id),
            "matched_by": result.matched_by,
            "issuer": ISSUER,
            "auth_method": "sso",
        }


@pytest.mark.settings(oidc_auto_create_users=True)
async def test_auto_created_user(db_session: AsyncSession, settings: Settings) -> None:
    claims = {"sub": "k-5", "email": " Nia@Example.com ", "name": "  " + "N" * 120, **VERIFIED}

    result = await match_login(db_session, settings, issuer=ISSUER, subject="k-5", claims=claims)
    await db_session.commit()

    assert isinstance(result, LoginMatch)
    user = result.user
    assert user.email == "Nia@Example.com"
    assert user.display_name == "N" * 100
    assert user.is_active
    assert not user.is_platform_admin
    assert not user.is_service_account
    assert not user.is_break_glass
    [created] = await audit_entries(db_session, "user.create")
    assert created.actor_id == user.id
    assert (created.target_type, created.target_id) == ("user", user.id)
    assert created.details == {
        "source": "sso",
        "is_platform_admin": False,
        "external_id_kinds": [],
        "auth_method": "sso",
    }


async def test_external_id_is_matched_case_insensitively(
    db_session: AsyncSession, settings: Settings
) -> None:
    [bob_user] = (await arrange(db_session, [bob(external_ids={"employee_no": "ab-12"})])).values()

    result = await match_login(
        db_session,
        settings,
        issuer=ISSUER,
        subject="k-9",
        claims={"sub": "k-9", "employee_no": "AB-12"},
    )

    assert isinstance(result, LoginMatch)
    assert result.user.id == bob_user.id


@pytest.mark.settings(oidc_external_id_claim="attributes.emp", oidc_external_id_kind="employee_no")
async def test_external_id_from_a_nested_claim(
    db_session: AsyncSession, settings: Settings
) -> None:
    await arrange(db_session, [bob(external_ids={"employee_no": "E1002"})])
    claims = {"sub": "k-9", "attributes": {"emp": "E1002"}}

    result = await match_login(db_session, settings, issuer=ISSUER, subject="k-9", claims=claims)

    assert describe(result) == "Bob (external_id)"


async def test_second_sign_in_matches_by_identity(
    db_session: AsyncSession, settings: Settings
) -> None:
    await arrange(db_session, [erin()])
    claims = {"sub": "k-7", "email": "erin@example.com", **VERIFIED}

    first = await match_login(db_session, settings, issuer=ISSUER, subject="k-7", claims=claims)
    await db_session.commit()
    second = await match_login(db_session, settings, issuer=ISSUER, subject="k-7", claims=claims)

    assert describe(first) == "Erin (email)"
    assert describe(second) == "Erin (identity)"
    assert isinstance(first, LoginMatch)
    assert isinstance(second, LoginMatch)
    assert second.identity.id == first.identity.id


async def test_profile_fields_are_not_synced(db_session: AsyncSession, settings: Settings) -> None:
    [erin_user] = (await arrange(db_session, [erin(linked_subject="k-7")])).values()
    claims = {"sub": "k-7", "email": "erin.new@example.com", "name": "Erin New", **VERIFIED}

    await match_login(db_session, settings, issuer=ISSUER, subject="k-7", claims=claims)
    await db_session.commit()
    await db_session.refresh(erin_user)

    assert (erin_user.display_name, erin_user.email) == ("Erin", "erin@example.com")


async def test_concurrent_first_sign_in_links_once(
    app: FastAPI, db_session: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two tabs: this one looked for the identity before the other tab linked it, so
    its insert hits the unique constraint. The SAVEPOINT rolls back and matching runs
    once more, finding the identity the other tab linked; the transaction survives."""
    [erin_user] = (await arrange(db_session, [erin()])).values()
    claims = {"sub": "k-7", "email": "erin@example.com", **VERIFIED}
    async with app.state.sessionmaker() as other:
        first = await match_login(other, settings, issuer=ISSUER, subject="k-7", claims=claims)
        await other.commit()
    calls: dict[str, int] = {}

    def too_early(name: str, before: object) -> None:
        """The first call answers as it would have before the other tab committed."""
        real = getattr(login_matching, name)

        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            calls[name] = calls.get(name, 0) + 1
            return before if calls[name] == 1 else await real(*args, **kwargs)

        monkeypatch.setattr(login_matching, name, wrapper)

    too_early("find_identity", None)
    too_early("_linked_at", False)

    second = await match_login(db_session, settings, issuer=ISSUER, subject="k-7", claims=claims)
    await db_session.commit()

    assert describe(first) == "Erin (email)"
    assert describe(second) == "Erin (identity)"
    assert isinstance(second, LoginMatch)
    assert second.user.id == erin_user.id
    assert calls == {"find_identity": 2, "_linked_at": 1}
    assert await db_session.scalar(select(func.count()).select_from(UserIdentity)) == 1
    assert len(await audit_entries(db_session, "user.identity_link")) == 1


@pytest.mark.parametrize(
    ("reason", "code"),
    [
        ("account_disabled", LoginErrorCode.ACCOUNT_DISABLED),
        ("already_linked", LoginErrorCode.IDENTITY_CONFLICT),
        ("external_id_mismatch", LoginErrorCode.IDENTITY_CONFLICT),
        ("external_id_missing", LoginErrorCode.IDENTITY_CONFLICT),
        ("email_taken", LoginErrorCode.IDENTITY_CONFLICT),
        ("email_not_verified", LoginErrorCode.NO_ACCOUNT),
        ("no_match", LoginErrorCode.NO_ACCOUNT),
        ("groups_overage", LoginErrorCode.SSO_FAILED),
    ],
)
def test_denial_codes(reason: str, code: LoginErrorCode) -> None:
    assert LoginDenied.of(reason).code is code  # type: ignore[arg-type]
