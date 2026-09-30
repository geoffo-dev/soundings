"""The request's :class:`~app.domain.principal.Principal`, for every signed-in route.

Routes depend on ``PrincipalDep``, not on the user directly, so Phase 5 (API keys:
scopes and a project restriction) changes only :func:`get_principal`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from app.api.deps import CurrentUserDep
from app.domain.principal import Principal

__all__ = ["PrincipalDep", "get_principal"]


async def get_principal(user: CurrentUserDep) -> Principal:
    """Phase 1: every caller is a session user (401/403 come from ``get_current_user``).

    Phase 5 builds API-key principals here (or in ``app/api/deps.py``): bearer key ->
    its owner, ``auth="api_key"``, the key's scopes and projects, no CSRF check.
    """
    return Principal(user=user)


PrincipalDep = Annotated[Principal, Depends(get_principal)]
"""The authenticated caller; 401 problem if there is none."""
