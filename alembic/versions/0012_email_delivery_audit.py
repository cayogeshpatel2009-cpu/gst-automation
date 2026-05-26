"""email delivery audit

Revision ID: 0012_email_delivery_audit
Revises: 0011_client_master_onboarding
Create Date: 2026-05-21
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0012_email_delivery_audit"
down_revision = "0011_client_master_onboarding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_deliveries",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("to_email", sa.String(length=256), nullable=False),
        sa.Column("cc_email", sa.String(length=256), nullable=True),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("attachment_path", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_email_deliveries_client_id", "email_deliveries", ["client_id"])
    op.create_index("ix_email_deliveries_status", "email_deliveries", ["status"])
    op.create_index("ix_email_deliveries_created_at", "email_deliveries", ["created_at"])
    op.create_index("ix_email_deliveries_sent_at", "email_deliveries", ["sent_at"])


def downgrade() -> None:
    op.drop_table("email_deliveries")

