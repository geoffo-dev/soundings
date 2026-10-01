"""Phase 2, sign-in and access: identities, external IDs, groups, group grants.

* ``users.is_break_glass`` (at most one such row) and, on ``user_sessions``,
  ``auth_method`` (existing rows are dev-login sessions) and ``id_token`` (SSO
  sessions, for RP-initiated logout).
* ``user_identities`` (issuer, subject) and ``user_external_ids`` (kind, value) for
  login matching; ``oidc_login_attempts`` holds sign-ins in progress (hashed state,
  nonce, PKCE verifier) so the browser never sees them.
* ``groups``, ``group_idp_values`` (normalised IdP values), ``group_memberships``
  (manual and/or synced) and ``project_group_grants``.
* ``project_effective_roles`` now returns the highest of the direct role and every
  group-granted role (same columns, so no query changes).
* ``audit_log`` indexes for the admin viewer's filters and newest-first paging.

Downgrade keeps Phase 1 working: it deletes SSO and break-glass sessions (Phase 1 only
knows the dev login) and leaves the break-glass account as an ordinary row, which a
later upgrade marks as the break-glass account again (by its reserved email).

Hand-written to match the models exactly (``tests/test_domain_schema.py`` compares
them). See docs/erd.md and docs/api/contract-phase2.md.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-01
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _id() -> sa.Column[Any]:
    return sa.Column("id", sa.Uuid(), nullable=False)


def _timestamp(name: str) -> sa.Column[Any]:
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def _flag(name: str, *, default: bool) -> sa.Column[Any]:
    return sa.Column(
        name, sa.Boolean(), server_default=sa.text(str(default).lower()), nullable=False
    )


def _enum_check(column: str, values: Sequence[str], name: str) -> sa.CheckConstraint:
    allowed = ", ".join(f"'{value}'" for value in values)
    return sa.CheckConstraint(f"{column} IN ({allowed})", name=op.f(name))


def _fk(column: str, target: str, name: str, ondelete: str = "CASCADE") -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint([column], [target], name=op.f(name), ondelete=ondelete)


# Effective role = the highest of the direct role and every group-granted role. Same
# columns (and types) as the Phase 1 view. Filters on project_id / user_id are pushed
# into both branches (they are the GROUP BY columns), so per-user and per-project
# lookups use the primary keys and the user_id / group_id indexes.
EFFECTIVE_ROLES_VIEW = """
CREATE VIEW project_effective_roles AS
SELECT project_id, user_id,
       CAST(CASE max(rank) WHEN 3 THEN 'admin' WHEN 2 THEN 'member' ELSE 'viewer' END
            AS VARCHAR(6)) AS role
FROM (
    SELECT pm.project_id, pm.user_id,
           CASE pm.role WHEN 'admin' THEN 3 WHEN 'member' THEN 2 ELSE 1 END AS rank
    FROM project_members pm
    UNION ALL
    SELECT pgg.project_id, gm.user_id,
           CASE pgg.role WHEN 'admin' THEN 3 WHEN 'member' THEN 2 ELSE 1 END AS rank
    FROM project_group_grants pgg
    JOIN group_memberships gm ON gm.group_id = pgg.group_id
) AS granted
GROUP BY project_id, user_id
"""

PHASE1_EFFECTIVE_ROLES_VIEW = """
CREATE VIEW project_effective_roles AS
SELECT project_id, user_id, role FROM project_members
"""

# The break-glass account's fixed, reserved address (contract-phase2 section 3.8).
# Hard-coded: a migration must not import application code that may change later.
BREAK_GLASS_EMAIL = "break-glass@soundings.invalid"


def upgrade() -> None:
    # --- users and sessions -------------------------------------------------------
    op.add_column("users", _flag("is_break_glass", default=False))
    # After a downgrade and upgrade, the account created by an earlier Phase 2 is the
    # break-glass account again (otherwise its email would block creating a new one).
    op.execute(
        sa.text(
            "UPDATE users SET is_break_glass = true "
            "WHERE lower(email) = :email AND NOT is_service_account"
        ).bindparams(email=BREAK_GLASS_EMAIL)
    )
    op.create_index(
        "uq_users_is_break_glass",
        "users",
        ["is_break_glass"],
        unique=True,
        postgresql_where=sa.text("is_break_glass"),
    )

    # Existing sessions all came from the dev login; new rows always name their method.
    op.add_column(
        "user_sessions",
        sa.Column("auth_method", sa.String(length=11), server_default="dev_login", nullable=False),
    )
    op.alter_column("user_sessions", "auth_method", server_default=None)
    op.create_check_constraint(
        op.f("ck_user_sessions_auth_method"),
        "user_sessions",
        "auth_method IN ('dev_login', 'sso', 'break_glass')",
    )
    op.add_column("user_sessions", sa.Column("id_token", sa.Text(), nullable=True))

    op.create_table(
        "user_identities",
        _id(),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("issuer", sa.String(length=512), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        _timestamp("created_at"),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        _fk("user_id", "users.id", "fk_user_identities_user_id_users"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_identities")),
        sa.UniqueConstraint("issuer", "subject", name=op.f("uq_user_identities_issuer_subject")),
        sa.UniqueConstraint("user_id", "issuer", name=op.f("uq_user_identities_user_id_issuer")),
    )

    op.create_table(
        "user_external_ids",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("value", sa.String(length=200), nullable=False),
        _timestamp("created_at"),
        sa.CheckConstraint(
            "kind ~ '^[a-z][a-z0-9_]{0,39}$'", name=op.f("ck_user_external_ids_kind")
        ),
        sa.CheckConstraint("length(value) > 0", name=op.f("ck_user_external_ids_value_not_empty")),
        _fk("user_id", "users.id", "fk_user_external_ids_user_id_users"),
        sa.PrimaryKeyConstraint("user_id", "kind", name=op.f("pk_user_external_ids")),
    )
    op.create_index(
        "uq_user_external_ids_kind_value_lower",
        "user_external_ids",
        ["kind", sa.literal_column("lower(value)")],
        unique=True,
    )

    op.create_table(
        "oidc_login_attempts",
        _id(),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("nonce", sa.String(length=128), nullable=False),
        sa.Column("code_verifier", sa.String(length=128), nullable=False),
        sa.Column("redirect_uri", sa.String(length=2048), nullable=False),
        sa.Column("next_path", sa.String(length=2048), server_default="/", nullable=False),
        _timestamp("created_at"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oidc_login_attempts")),
        sa.UniqueConstraint("state_hash", name=op.f("uq_oidc_login_attempts_state_hash")),
    )
    op.create_index(
        op.f("ix_oidc_login_attempts_expires_at"), "oidc_login_attempts", ["expires_at"]
    )

    # --- groups -------------------------------------------------------------------
    op.create_table(
        "groups",
        _id(),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("description", sa.String(length=500), server_default="", nullable=False),
        sa.Column("sync_mode", sa.String(length=8), server_default="managed", nullable=False),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        _enum_check("sync_mode", ["managed", "additive"], "ck_groups_sync_mode"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_groups")),
    )
    op.create_index(
        "uq_groups_name_lower", "groups", [sa.literal_column("lower(name)")], unique=True
    )

    op.create_table(
        "group_idp_values",
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("value", sa.String(length=255), nullable=False),
        _timestamp("created_at"),
        sa.CheckConstraint("length(value) > 0", name=op.f("ck_group_idp_values_value_not_empty")),
        _fk("group_id", "groups.id", "fk_group_idp_values_group_id_groups"),
        sa.PrimaryKeyConstraint("group_id", "value", name=op.f("pk_group_idp_values")),
    )
    op.create_index(op.f("ix_group_idp_values_value"), "group_idp_values", ["value"])

    op.create_table(
        "group_memberships",
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        _flag("manual", default=False),
        _flag("synced", default=False),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.CheckConstraint("manual OR synced", name=op.f("ck_group_memberships_has_source")),
        _fk("group_id", "groups.id", "fk_group_memberships_group_id_groups"),
        _fk("user_id", "users.id", "fk_group_memberships_user_id_users"),
        sa.PrimaryKeyConstraint("group_id", "user_id", name=op.f("pk_group_memberships")),
    )
    op.create_index(op.f("ix_group_memberships_user_id"), "group_memberships", ["user_id"])

    op.create_table(
        "project_group_grants",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=6), nullable=False),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        _enum_check("role", ["admin", "member", "viewer"], "ck_project_group_grants_role"),
        _fk("project_id", "projects.id", "fk_project_group_grants_project_id_projects"),
        _fk("group_id", "groups.id", "fk_project_group_grants_group_id_groups"),
        sa.PrimaryKeyConstraint("project_id", "group_id", name=op.f("pk_project_group_grants")),
    )
    op.create_index(op.f("ix_project_group_grants_group_id"), "project_group_grants", ["group_id"])

    op.execute("DROP VIEW project_effective_roles")
    op.execute(EFFECTIVE_ROLES_VIEW)

    # --- audit log viewer ----------------------------------------------------------
    op.drop_index("ix_audit_log_created_at", table_name="audit_log")
    op.drop_index("ix_audit_log_actor_id", table_name="audit_log")
    op.create_index("ix_audit_log_created_at_id", "audit_log", ["created_at", "id"])
    op.create_index("ix_audit_log_actor_id_created_at", "audit_log", ["actor_id", "created_at"])
    op.create_index("ix_audit_log_action_created_at", "audit_log", ["action", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_log_action_created_at", table_name="audit_log")
    op.drop_index("ix_audit_log_actor_id_created_at", table_name="audit_log")
    op.drop_index("ix_audit_log_created_at_id", table_name="audit_log")
    op.create_index("ix_audit_log_actor_id", "audit_log", ["actor_id"])
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"])

    # Group-granted roles disappear with their tables; direct roles are untouched.
    op.execute("DROP VIEW project_effective_roles")
    op.execute(PHASE1_EFFECTIVE_ROLES_VIEW)
    for table in (
        "project_group_grants",
        "group_memberships",
        "group_idp_values",
        "groups",
        "oidc_login_attempts",
        "user_external_ids",
        "user_identities",
    ):
        op.drop_table(table)

    # Dev-login sessions keep working as Phase 1 sessions. SSO and break-glass sessions
    # end: Phase 1 can't tell them apart, and the break-glass row is about to become an
    # ordinary platform admin (unreachable without a session: Phase 1 only has the dev
    # login, which is refused in production).
    op.execute("DELETE FROM user_sessions WHERE auth_method <> 'dev_login'")
    op.drop_column("user_sessions", "id_token")
    op.drop_constraint(op.f("ck_user_sessions_auth_method"), "user_sessions", type_="check")
    op.drop_column("user_sessions", "auth_method")
    op.drop_index("uq_users_is_break_glass", table_name="users")
    op.drop_column("users", "is_break_glass")
