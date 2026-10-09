"""Who is making a request: the signed-in user plus how they authenticated.

Routes receive a :class:`Principal` (``PrincipalDep`` in ``app/api/v1/principal.py``),
never a bare ``User``, and pass it to the authorisation policy (ADR 0010). Phase 1
has sessions only. Phase 5 API keys act as their owner *narrowed* by scopes and a
project restriction (role matrix section 5): effective permission = the user's live
permission ∩ key scopes ∩ key projects. Adding API keys then changes how the
principal is built, not every route.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from app.models.enums import AuthMethod
from app.models.user import User

__all__ = ["ApiKeyScope", "AuthKind", "Principal"]

AuthKind = Literal["session", "api_key"]
"""``session``: browser cookie (CSRF-checked). ``api_key``: bearer key (Phase 5)."""

ApiKeyScope = Literal["read", "write", "evaluate", "mcp"]
"""API-key scopes (role matrix section 5)."""


@dataclass(frozen=True, slots=True)
class Principal:
    """An authenticated caller.

    ``scopes`` and ``project_ids`` are ``None`` when not narrowed (every session);
    an API key sets both (``project_ids`` stays ``None`` for an unrestricted key).
    ``session_id`` / ``api_key_id`` identify the credential (audit, sign-out).
    ``auth_method``: how the session was started (``sso``, ``break_glass``,
    ``dev_login``); audit entries record it as ``details.auth_method`` (contract-phase2
    section 3.11). ``None`` only for principals built without a session (tests).
    """

    user: User
    auth: AuthKind = "session"
    scopes: frozenset[ApiKeyScope] | None = None
    project_ids: frozenset[UUID] | None = None
    api_key_id: UUID | None = None
    session_id: UUID | None = None
    auth_method: AuthMethod | None = None
    operation: str | None = None
    """Phase 8b: the API operation (``operation_id``) or MCP tool (``mcp.<tool>``) being
    served, for the guest researcher's route table (:mod:`app.authz.guest`). ``None``
    outside a request (jobs, fan-out, the CLI): no route to decide, the rules do."""

    @property
    def user_id(self) -> UUID:
        return self.user.id

    @property
    def is_platform_admin(self) -> bool:
        return self.user.is_platform_admin

    def has_scope(self, scope: ApiKeyScope) -> bool:
        """The key grants ``scope`` (always true for a session)."""
        return self.scopes is None or scope in self.scopes

    def may_access_project(self, project_id: UUID) -> bool:
        """The key is not restricted away from this project (404 otherwise)."""
        return self.project_ids is None or project_id in self.project_ids
