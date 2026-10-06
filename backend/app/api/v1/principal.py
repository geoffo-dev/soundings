"""The request's :class:`~app.domain.principal.Principal`, for every signed-in route.

Routes depend on ``PrincipalDep``, not on the user directly: the principal also
says how the caller authenticated (a session, or an API key with scopes and a project
restriction), which the authorisation policy narrows by. The principal
sources in :mod:`app.auth.sources` build it; adding one changes no route.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from app.api.deps import CurrentUserDep
from app.domain.principal import Principal

__all__ = ["PrincipalDep", "get_principal"]


async def get_principal(request: Request, user: CurrentUserDep) -> Principal:
    """The principal ``get_current_user`` authenticated (401/403 come from there).

    Whenever a principal was stored it is the answer, as it is: a key's principal is
    never widened into a session one (contract-phase5 section 3.2). Only when none was
    stored (tests that override ``get_current_user``) is a plain session principal built.
    """
    principal = getattr(request.state, "principal", None)
    if isinstance(principal, Principal):
        return principal
    return Principal(user=user)


PrincipalDep = Annotated[Principal, Depends(get_principal)]
"""The authenticated caller; 401 problem if there is none."""
