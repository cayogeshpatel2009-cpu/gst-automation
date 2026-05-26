"""browser infrastructure schema

Revision ID: 0005_browser_infra
Revises: 0004_watchdog_anomalies
Create Date: 2026-05-20
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0005_browser_infra"
down_revision = "0004_watchdog_anomalies"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "browser_instances",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("worker_name", sa.String(length=128), nullable=False),
        sa.Column("worker_generation", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("browser_type", sa.String(length=32), nullable=False),
        sa.Column("headless", sa.Integer(), nullable=False),
        sa.Column("launch_config_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_browser_instances_worker_name", "browser_instances", ["worker_name"])
    op.create_index("ix_browser_instances_worker_generation", "browser_instances", ["worker_generation"])
    op.create_index("ix_browser_instances_state", "browser_instances", ["state"])
    op.create_index("ix_browser_instances_created_at", "browser_instances", ["created_at"])
    op.create_index("ix_browser_instances_last_heartbeat_at", "browser_instances", ["last_heartbeat_at"])

    op.create_table(
        "browser_contexts",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("browser_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("lease_token", sa.String(length=128), nullable=False),
        sa.Column("fencing_token", sa.Integer(), nullable=False),
        sa.Column("worker_name", sa.String(length=128), nullable=False),
        sa.Column("worker_generation", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("workspace_dir", sa.Text(), nullable=False),
        sa.Column("downloads_dir", sa.Text(), nullable=False),
        sa.Column("artifacts_dir", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_browser_contexts_browser_id", "browser_contexts", ["browser_id"])
    op.create_index("ix_browser_contexts_job_id", "browser_contexts", ["job_id"])
    op.create_index("ix_browser_contexts_lease_token", "browser_contexts", ["lease_token"])
    op.create_index("ix_browser_contexts_fencing_token", "browser_contexts", ["fencing_token"])
    op.create_index("ix_browser_contexts_worker_name", "browser_contexts", ["worker_name"])
    op.create_index("ix_browser_contexts_worker_generation", "browser_contexts", ["worker_generation"])
    op.create_index("ix_browser_contexts_state", "browser_contexts", ["state"])
    op.create_index("ix_browser_contexts_created_at", "browser_contexts", ["created_at"])

    op.create_table(
        "browser_artifacts",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("context_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("relpath", sa.Text(), nullable=False),
        sa.Column("sha256_hex", sa.String(length=64), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_browser_artifacts_job_id", "browser_artifacts", ["job_id"])
    op.create_index("ix_browser_artifacts_context_id", "browser_artifacts", ["context_id"])
    op.create_index("ix_browser_artifacts_kind", "browser_artifacts", ["kind"])
    op.create_index("ix_browser_artifacts_created_at", "browser_artifacts", ["created_at"])

    op.create_table(
        "browser_crashes",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("browser_id", sa.Uuid(), nullable=True),
        sa.Column("context_id", sa.Uuid(), nullable=True),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("crash_type", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_browser_crashes_browser_id", "browser_crashes", ["browser_id"])
    op.create_index("ix_browser_crashes_context_id", "browser_crashes", ["context_id"])
    op.create_index("ix_browser_crashes_job_id", "browser_crashes", ["job_id"])
    op.create_index("ix_browser_crashes_crash_type", "browser_crashes", ["crash_type"])
    op.create_index("ix_browser_crashes_severity", "browser_crashes", ["severity"])
    op.create_index("ix_browser_crashes_created_at", "browser_crashes", ["created_at"])


def downgrade() -> None:
    op.drop_table("browser_crashes")
    op.drop_table("browser_artifacts")
    op.drop_table("browser_contexts")
    op.drop_table("browser_instances")

