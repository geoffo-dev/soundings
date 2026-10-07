"""Security review P7 N4: decisions that follow from who the principal is live in the
policy module under role-matrix names (section 1a), not as account-kind branches in
services, routes and the MCP dispatcher."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.authz import (
    counted_by_default,
    is_agent,
    may_cite_sources,
    searches_co_members_only,
    sees_email_trouble,
    writes_as_ai,
)
from app.domain.principal import Principal
from app.models.user import User


def principal(*, agent: bool = False, admin: bool = False) -> Principal:
    user = User(
        id=uuid4(),
        email="x@example.com",
        display_name="X",
        is_service_account=agent,
        is_platform_admin=admin,
        is_active=True,
        is_break_glass=False,
    )
    return Principal(user=user)


@pytest.mark.parametrize(
    ("who", "expected"),
    [
        (principal(), (False, False, False, True, False, False)),
        (principal(admin=True), (False, True, False, True, False, False)),
        (principal(agent=True), (True, False, True, False, True, True)),
    ],
    ids=["person", "platform admin", "agent"],
)
def test_traits(who: Principal, expected: tuple[bool, ...]) -> None:
    assert (
        is_agent(who),
        sees_email_trouble(who),
        may_cite_sources(who),
        counted_by_default(who),
        writes_as_ai(who),
        searches_co_members_only(who),
    ) == expected


def test_nobody_signed_in_has_no_traits() -> None:
    assert not is_agent(None)
    assert not sees_email_trouble(None)
    assert counted_by_default(None)
