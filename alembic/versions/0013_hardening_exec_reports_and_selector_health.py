"""hardening: execution reports + selector health + email idempotency

Revision ID: 0013_hardening_exec_reports_and_selector_health
Revises: 0012_email_delivery_audit
Create Date: 2026-05-21
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0013_hardening_exec_reports_and_selector_health"
down_revision = "0012_email_delivery_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gst_execution_reports",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("period", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("report_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_gst_execution_reports_job_id", "gst_execution_reports", ["job_id"])
    op.create_index("ix_gst_execution_reports_client_id", "gst_execution_reports", ["client_id"])
    op.create_index("ix_gst_execution_reports_period", "gst_execution_reports", ["period"])
    op.create_index("ix_gst_execution_reports_status", "gst_execution_reports", ["status"])
    op.create_index("ix_gst_execution_reports_created_at", "gst_execution_reports", ["created_at"])

    op.create_table(
        "selector_health_events",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("context_id", sa.Uuid(), nullable=False),
        sa.Column("selector_key", sa.String(length=256), nullable=False),
        sa.Column("selector_version", sa.Integer(), nullable=False),
        sa.Column("result", sa.String(length=16), nullable=False),
        sa.Column("candidate_index", sa.Integer(), nullable=False),
        sa.Column("candidates_total", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_selector_health_events_job_id", "selector_health_events", ["job_id"])
    op.create_index("ix_selector_health_events_context_id", "selector_health_events", ["context_id"])
    op.create_index("ix_selector_health_events_selector_key", "selector_health_events", ["selector_key"])
    op.create_index("ix_selector_health_events_selector_version", "selector_health_events", ["selector_version"])
    op.create_index("ix_selector_health_events_result", "selector_health_events", ["result"])
    op.create_index("ix_selector_health_events_created_at", "selector_health_events", ["created_at"])

    op.add_column("email_deliveries", sa.Column("idempotency_key", sa.String(length=256), nullable=True))
    op.create_unique_constraint("uq_email_deliveries_idempotency_key", "email_deliveries", ["idempotency_key"])


def downgrade() -> None:
    op.drop_constraint("uq_email_deliveries_idempotency_key", "email_deliveries", type_="unique")
    op.drop_column("email_deliveries", "idempotency_key")
    op.drop_table("selector_health_events")
    op.drop_table("gst_execution_reports")

