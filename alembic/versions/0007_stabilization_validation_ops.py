"""stabilization validation ops tables

Revision ID: 0007_stabilization_validation_ops
Revises: 0006_portal_framework
Create Date: 2026-05-21
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0007_stabilization_validation_ops"
down_revision = "0006_portal_framework"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "validation_runs",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("run_kind", sa.String(length=32), nullable=False),
        sa.Column("scenario", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("config_json", sa.Text(), nullable=False),
        sa.Column("summary_json", sa.Text(), nullable=False),
        sa.Column("jobs_total", sa.Integer(), nullable=False),
        sa.Column("jobs_completed", sa.Integer(), nullable=False),
        sa.Column("jobs_failed", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_validation_runs_run_kind", "validation_runs", ["run_kind"])
    op.create_index("ix_validation_runs_scenario", "validation_runs", ["scenario"])
    op.create_index("ix_validation_runs_status", "validation_runs", ["status"])
    op.create_index("ix_validation_runs_started_at", "validation_runs", ["started_at"])
    op.create_index("ix_validation_runs_ended_at", "validation_runs", ["ended_at"])

    op.create_table(
        "validation_run_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_validation_run_jobs_run_id", "validation_run_jobs", ["run_id"])
    op.create_index("ix_validation_run_jobs_job_id", "validation_run_jobs", ["job_id"])
    op.create_index("ix_validation_run_jobs_created_at", "validation_run_jobs", ["created_at"])

    op.create_table(
        "cleanup_audits",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("audit_scope", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("findings_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_cleanup_audits_run_id", "cleanup_audits", ["run_id"])
    op.create_index("ix_cleanup_audits_audit_scope", "cleanup_audits", ["audit_scope"])
    op.create_index("ix_cleanup_audits_status", "cleanup_audits", ["status"])
    op.create_index("ix_cleanup_audits_created_at", "cleanup_audits", ["created_at"])

    op.create_table(
        "retention_policies",
        sa.Column("kind", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("ttl_days", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Integer(), nullable=False),
        sa.Column("preserve", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_retention_policies_updated_at", "retention_policies", ["updated_at"])

    op.create_table(
        "retention_actions",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("policy_kind", sa.String(length=64), nullable=False),
        sa.Column("relpath", sa.Text(), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_retention_actions_policy_kind", "retention_actions", ["policy_kind"])
    op.create_index("ix_retention_actions_created_at", "retention_actions", ["created_at"])

    op.create_table(
        "browser_health_snapshots",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("browser_id", sa.Uuid(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_browser_health_snapshots_browser_id", "browser_health_snapshots", ["browser_id"])
    op.create_index("ix_browser_health_snapshots_created_at", "browser_health_snapshots", ["created_at"])

    op.create_table(
        "leak_findings",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("leak_type", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_leak_findings_leak_type", "leak_findings", ["leak_type"])
    op.create_index("ix_leak_findings_severity", "leak_findings", ["severity"])
    op.create_index("ix_leak_findings_created_at", "leak_findings", ["created_at"])

    op.create_table(
        "replay_integrity_audits",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("context_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("issues_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_replay_integrity_audits_job_id", "replay_integrity_audits", ["job_id"])
    op.create_index("ix_replay_integrity_audits_context_id", "replay_integrity_audits", ["context_id"])
    op.create_index("ix_replay_integrity_audits_status", "replay_integrity_audits", ["status"])
    op.create_index("ix_replay_integrity_audits_created_at", "replay_integrity_audits", ["created_at"])


def downgrade() -> None:
    op.drop_table("replay_integrity_audits")
    op.drop_table("leak_findings")
    op.drop_table("browser_health_snapshots")
    op.drop_table("retention_actions")
    op.drop_table("retention_policies")
    op.drop_table("cleanup_audits")
    op.drop_table("validation_run_jobs")
    op.drop_table("validation_runs")

