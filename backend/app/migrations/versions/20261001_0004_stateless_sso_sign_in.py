"""Stateless SSO sign-in and sealed ID tokens (Phase 2 security review H1 and L4).

* ``oidc_login_attempts`` goes: a sign-in in progress is now sealed (AES-GCM with
  the secret key) into the HttpOnly ``soundings_oidc`` cookie, so starting sign-ins
  writes nothing and no number of them can fill a table and lock everyone out. Sign-ins
  in progress during the upgrade start again (``login_expired``).
* ``user_sessions.id_token`` is now stored sealed. Tokens stored in plain text are
  removed: those sessions keep working and sign out at the IdP without
  ``id_token_hint`` (the IdP may ask the person to confirm).

Downgrade re-creates the empty table; the sealed ID tokens are removed (0003 expects
plain ones).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index(op.f("ix_oidc_login_attempts_expires_at"), table_name="oidc_login_attempts")
    op.drop_table("oidc_login_attempts")
    op.execute("UPDATE user_sessions SET id_token = NULL WHERE id_token IS NOT NULL")


def downgrade() -> None:
    op.execute("UPDATE user_sessions SET id_token = NULL WHERE id_token IS NOT NULL")
    op.create_table(
        "oidc_login_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("nonce", sa.String(length=128), nullable=False),
        sa.Column("code_verifier", sa.String(length=128), nullable=False),
        sa.Column("redirect_uri", sa.String(length=2048), nullable=False),
        sa.Column("next_path", sa.String(length=2048), server_default="/", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oidc_login_attempts")),
        sa.UniqueConstraint("state_hash", name=op.f("uq_oidc_login_attempts_state_hash")),
    )
    op.create_index(
        op.f("ix_oidc_login_attempts_expires_at"), "oidc_login_attempts", ["expires_at"]
    )
