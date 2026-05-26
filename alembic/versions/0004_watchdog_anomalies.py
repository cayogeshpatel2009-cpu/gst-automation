"""watchdog anomalies and dedupe state

Revision ID: 0004_watchdog_anomalies
Revises: 0003_orchestration_hardening
Create Date: 2026-05-20
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0004_watchdog_anomalies"
down_revision = "0003_orchestration_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "watchdog_anomalies",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("anomaly_type", sa.String(length=128), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_watchdog_anomalies_anomaly_type", "watchdog_anomalies", ["anomaly_type"])
    op.create_index("ix_watchdog_anomalies_severity", "watchdog_anomalies", ["severity"])
    op.create_index("ix_watchdog_anomalies_created_at", "watchdog_anomalies", ["created_at"])

    op.create_table(
        "watchdog_anomaly_state",
        sa.Column("anomaly_type", sa.String(length=128), primary_key=True, nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_alerted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consecutive_count", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("watchdog_anomaly_state")
    op.drop_table("watchdog_anomalies")

