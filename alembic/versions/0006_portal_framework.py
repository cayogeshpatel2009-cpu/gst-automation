"""portal automation framework persistence

Revision ID: 0006_portal_framework
Revises: 0005_browser_infra
Create Date: 2026-05-20
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0006_portal_framework"
down_revision = "0005_browser_infra"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "portal_selector_defs",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("candidates_json", sa.Text(), nullable=False),
        sa.Column("active", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("key", "version", name="uq_portal_selector_key_version"),
    )
    op.create_index("ix_portal_selector_defs_key", "portal_selector_defs", ["key"])
    op.create_index("ix_portal_selector_defs_version", "portal_selector_defs", ["version"])
    op.create_index("ix_portal_selector_defs_active", "portal_selector_defs", ["active"])
    op.create_index("ix_portal_selector_defs_created_at", "portal_selector_defs", ["created_at"])

    op.create_table(
        "portal_session_blobs",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=True),
        sa.Column("profile", sa.String(length=64), nullable=False),
        sa.Column("encrypted_blob", sa.Text(), nullable=False),
        sa.Column("key_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_portal_session_blobs_client_id", "portal_session_blobs", ["client_id"])
    op.create_index("ix_portal_session_blobs_profile", "portal_session_blobs", ["profile"])
    op.create_index("ix_portal_session_blobs_key_id", "portal_session_blobs", ["key_id"])
    op.create_index("ix_portal_session_blobs_created_at", "portal_session_blobs", ["created_at"])
    op.create_index("ix_portal_session_blobs_expires_at", "portal_session_blobs", ["expires_at"])


def downgrade() -> None:
    op.drop_table("portal_session_blobs")
    op.drop_table("portal_selector_defs")

