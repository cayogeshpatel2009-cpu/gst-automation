"""client master onboarding tables

Revision ID: 0011_client_master_onboarding
Revises: 0010_gst_observation_and_graphs
Create Date: 2026-05-21
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0011_client_master_onboarding"
down_revision = "0010_gst_observation_and_graphs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "client_configs",
        sa.Column("client_id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("client_email", sa.String(length=256), nullable=False),
        sa.Column("cc_email", sa.String(length=256), nullable=True),
        sa.Column("active", sa.Integer(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("folder_root", sa.Text(), nullable=False),
        sa.Column("retry_policy_json", sa.Text(), nullable=False),
        sa.Column("session_reuse_enabled", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_client_configs_active", "client_configs", ["active"])
    op.create_index("ix_client_configs_priority", "client_configs", ["priority"])
    op.create_index("ix_client_configs_created_at", "client_configs", ["created_at"])
    op.create_index("ix_client_configs_updated_at", "client_configs", ["updated_at"])

    op.create_table(
        "client_credential_refs",
        sa.Column("client_id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("gst_username", sa.String(length=128), nullable=False),
        sa.Column("gst_password_secret_key", sa.String(length=256), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_client_credential_refs_created_at", "client_credential_refs", ["created_at"])


def downgrade() -> None:
    op.drop_table("client_credential_refs")
    op.drop_table("client_configs")

