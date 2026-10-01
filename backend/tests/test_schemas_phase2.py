"""Validation rules encoded in the Phase 2 schemas (contract-phase2 sections 3.4-3.6)."""

from __future__ import annotations

from typing import get_args

import pytest
from pydantic import ValidationError

from app.models.enums import GroupSyncMode
from app.models.user import BREAK_GLASS_EMAIL
from app.schemas.admin_users import AdminUserCreate, AdminUserUpdate, ExternalIdsReplace
from app.schemas.audit import AuditAction
from app.schemas.auth import BreakGlassLogin
from app.schemas.groups import (
    GroupCreate,
    GroupMappingUpdate,
    MappingEffect,
    normalise_idp_value,
)
from app.services.audit import AUDIT_ACTIONS


@pytest.mark.parametrize(
    ("raw", "normalised"),
    [
        ("/innovation/admins", "innovation/admins"),  # Keycloak full path
        ("innovation/admins", "innovation/admins"),
        (" /Innovation/Admins/ ", "innovation/admins"),
        ("//viewers", "viewers"),
        ("Soundings-Users", "soundings-users"),
        ("8f1c2c3e-AAAA-4b5b-9c9c-0d0d0d0d0d0d", "8f1c2c3e-aaaa-4b5b-9c9c-0d0d0d0d0d0d"),
        (" / ", ""),
    ],
)
def test_idp_values_are_normalised(raw: str, normalised: str) -> None:
    assert normalise_idp_value(raw) == normalised


def test_inner_path_segments_are_kept() -> None:
    assert normalise_idp_value("/innovation/admins") != normalise_idp_value("admins")


def test_group_mapping_is_normalised_deduplicated_and_sorted() -> None:
    group = GroupCreate.model_validate(
        {
            "name": "Leads",
            "idp_values": ["/tools/members", "/Innovation/Admins", "innovation/admins"],
        }
    )

    assert group.sync_mode is GroupSyncMode.MANAGED
    assert group.idp_values == ["innovation/admins", "tools/members"]


@pytest.mark.parametrize("values", [["/"], [""], ["x" * 256], ["v"] * 51])
def test_invalid_mappings_are_rejected(values: list[str]) -> None:
    with pytest.raises(ValidationError):
        GroupMappingUpdate.model_validate({"sync_mode": "additive", "idp_values": values})


def test_external_ids_are_one_per_kind() -> None:
    with pytest.raises(ValidationError, match="one external ID per kind"):
        ExternalIdsReplace.model_validate(
            {"external_ids": [{"kind": "gitlab", "value": "a"}, {"kind": "gitlab", "value": "b"}]}
        )
    with pytest.raises(ValidationError):
        ExternalIdsReplace.model_validate({"external_ids": [{"kind": "Employee", "value": "1"}]})


def test_pre_created_user_needs_an_email_shape() -> None:
    user = AdminUserCreate.model_validate({"email": " ada@example.com ", "display_name": "Ada"})
    assert user.email == "ada@example.com"
    assert user.external_ids == []
    with pytest.raises(ValidationError):
        AdminUserCreate.model_validate({"email": "ada", "display_name": "Ada"})


@pytest.mark.parametrize(
    "email", [BREAK_GLASS_EMAIL, "Break-Glass@Soundings.INVALID", "agent@x.invalid"]
)
def test_reserved_invalid_addresses_are_refused(email: str) -> None:
    """.invalid is for system accounts: a pre-created user can't take the break-glass
    account's address (which would break its sign-in)."""
    with pytest.raises(ValidationError, match="reserved"):
        AdminUserCreate.model_validate({"email": email, "display_name": "Mallory"})
    with pytest.raises(ValidationError, match="reserved"):
        AdminUserUpdate.model_validate({"email": email})
    assert AdminUserCreate.model_validate(
        {"email": "ada@invalid.example.com", "display_name": "Ada"}
    )


def test_mapping_effects_are_add_keep_remove() -> None:
    assert set(get_args(MappingEffect)) == {"add", "keep", "remove"}


def test_break_glass_password_is_not_trimmed() -> None:
    login = BreakGlassLogin.model_validate({"username": "admin", "password": "  spaced  "})

    assert login.password == "  spaced  "


def test_audit_actions_cover_what_phase_1_records() -> None:
    """The backend's closed set grows to the AuditAction enum in Phase 2."""
    assert set(AUDIT_ACTIONS) <= {action.value for action in AuditAction}
