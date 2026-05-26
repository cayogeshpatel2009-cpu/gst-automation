"""empirical stability proving tables

Revision ID: 0008_empirical_stability_proving
Revises: 0007_stabilization_validation_ops
Create Date: 2026-05-21
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0008_empirical_stability_proving"
down_revision = "0007_stabilization_validation_ops"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "soak_campaigns",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("rate_per_minute", sa.Integer(), nullable=False),
        sa.Column("chaos_percent", sa.Integer(), nullable=False),
        sa.Column("config_json", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_soak_campaigns_status", "soak_campaigns", ["status"])
    op.create_index("ix_soak_campaigns_started_at", "soak_campaigns", ["started_at"])
    op.create_index("ix_soak_campaigns_ended_at", "soak_campaigns", ["ended_at"])

    op.create_table(
        "soak_snapshots",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_soak_snapshots_campaign_id", "soak_snapshots", ["campaign_id"])
    op.create_index("ix_soak_snapshots_created_at", "soak_snapshots", ["created_at"])

    op.create_table(
        "soak_campaign_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_soak_campaign_jobs_campaign_id", "soak_campaign_jobs", ["campaign_id"])
    op.create_index("ix_soak_campaign_jobs_job_id", "soak_campaign_jobs", ["job_id"])
    op.create_index("ix_soak_campaign_jobs_created_at", "soak_campaign_jobs", ["created_at"])

    op.create_table(
        "stability_scores",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("scope_id", sa.Uuid(), nullable=True),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_stability_scores_scope", "stability_scores", ["scope"])
    op.create_index("ix_stability_scores_scope_id", "stability_scores", ["scope_id"])
    op.create_index("ix_stability_scores_created_at", "stability_scores", ["created_at"])

    op.create_table(
        "replay_certifications",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("context_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("report_json", sa.Text(), nullable=False),
        sa.Column("report_sha256_hex", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_replay_certifications_job_id", "replay_certifications", ["job_id"])
    op.create_index("ix_replay_certifications_context_id", "replay_certifications", ["context_id"])
    op.create_index("ix_replay_certifications_status", "replay_certifications", ["status"])
    op.create_index("ix_replay_certifications_created_at", "replay_certifications", ["created_at"])

    op.create_table(
        "replay_diff_reports",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("left_job_id", sa.Uuid(), nullable=False),
        sa.Column("right_job_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("diff_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_replay_diff_reports_left_job_id", "replay_diff_reports", ["left_job_id"])
    op.create_index("ix_replay_diff_reports_right_job_id", "replay_diff_reports", ["right_job_id"])
    op.create_index("ix_replay_diff_reports_status", "replay_diff_reports", ["status"])
    op.create_index("ix_replay_diff_reports_created_at", "replay_diff_reports", ["created_at"])

    op.create_table(
        "readiness_gate_results",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("gate_name", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("report_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_readiness_gate_results_gate_name", "readiness_gate_results", ["gate_name"])
    op.create_index("ix_readiness_gate_results_status", "readiness_gate_results", ["status"])
    op.create_index("ix_readiness_gate_results_created_at", "readiness_gate_results", ["created_at"])


def downgrade() -> None:
    op.drop_table("readiness_gate_results")
    op.drop_table("replay_diff_reports")
    op.drop_table("replay_certifications")
    op.drop_table("stability_scores")
    op.drop_table("soak_snapshots")
    op.drop_table("soak_campaign_jobs")
    op.drop_table("soak_campaigns")
