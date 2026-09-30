"""The request's :class:`~app.domain.principal.Principal`, for every signed-in route.

Routes depend on ``PrincipalDep``, not on the user directly: the principal also
says how the caller authenticated (session now; API key in Phase 5, with scopes and
a project restriction), which the authorisation policy narrows by. The principal
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

    Falls back to a plain session principal when ``get_current_user`` is overridden
    (tests).
    """
    principal = getattr(request.state, "principal", None)
    if isinstance(principal, Principal) and principal.user is user:
        return principal
    return Principal(user=user)


PrincipalDep = Annotated[Principal, Depends(get_principal)]
"""The authenticated caller; 401 problem if there is none."""
