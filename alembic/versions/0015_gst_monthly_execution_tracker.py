"""gst monthly execution tracker

Revision ID: 0015_gst_monthly_execution_tracker
Revises: 0014_client_config_onboarding_fields
Create Date: 2026-05-21
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0015_gst_monthly_execution_tracker"
down_revision = "0014_client_config_onboarding_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gst_monthly_executions",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("period", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("details_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_gst_monthly_executions_client_id", "gst_monthly_executions", ["client_id"])
    op.create_index("ix_gst_monthly_executions_period", "gst_monthly_executions", ["period"])
    op.create_index("ix_gst_monthly_executions_status", "gst_monthly_executions", ["status"])
    op.create_index("ix_gst_monthly_executions_job_id", "gst_monthly_executions", ["job_id"])
    op.create_index("ix_gst_monthly_executions_created_at", "gst_monthly_executions", ["created_at"])
    op.create_index("ix_gst_monthly_executions_updated_at", "gst_monthly_executions", ["updated_at"])
    op.create_unique_constraint("uq_gst_monthly_executions_client_period", "gst_monthly_executions", ["client_id", "period"])


def downgrade() -> None:
    op.drop_constraint("uq_gst_monthly_executions_client_period", "gst_monthly_executions", type_="unique")
    op.drop_table("gst_monthly_executions")

