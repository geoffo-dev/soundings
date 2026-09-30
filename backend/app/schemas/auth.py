"""Signed-in user and the development login stub (Phase 2 adds OIDC)."""

from __future__ import annotations

from uuid import UUID

from app.schemas.base import RequestModel
from app.schemas.users import UserRef

__all__ = ["CurrentUser", "DevLoginRequest"]


class CurrentUser(UserRef):
    """The signed-in user (``GET /auth/me``), also used for the dev login picker."""

    email: str
    is_platform_admin: bool


class DevLoginRequest(RequestModel):
    user_id: UUID
