"""``get_principal``: the stored principal is the answer, never widened (contract-phase5
section 3.2)."""

from __future__ import annotations

from uuid import uuid4

from starlette.requests import Request

from app.api.v1.principal import get_principal
from app.domain.principal import Principal
from app.models.user import User


def _request() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": [], "state": {}})


def _user() -> User:
    return User(id=uuid4(), email="ada@example.com", display_name="Ada")


async def test_a_stored_key_principal_is_returned_even_for_another_user_object() -> None:
    request = _request()
    owner = _user()
    stored = Principal(
        user=owner,
        auth="api_key",
        scopes=frozenset({"read"}),
        project_ids=frozenset(),
        api_key_id=uuid4(),
    )
    request.state.principal = stored
    reloaded = User(id=owner.id, email=owner.email, display_name=owner.display_name)

    principal = await get_principal(request, reloaded)

    assert principal is stored
    assert principal.scopes == frozenset({"read"})
    assert principal.project_ids == frozenset()  # an empty restriction stays "no project"


async def test_without_a_stored_principal_a_plain_session_principal_is_built() -> None:
    user = _user()

    principal = await get_principal(_request(), user)

    assert principal == Principal(user=user)
    assert principal.scopes is None
