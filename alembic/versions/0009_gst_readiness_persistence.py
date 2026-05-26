"""gst readiness persistence

Revision ID: 0009_gst_readiness_persistence
Revises: 0008_empirical_stability_proving
Create Date: 2026-05-21
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0009_gst_readiness_persistence"
down_revision = "0008_empirical_stability_proving"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gst_portal_profiles",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("context_id", sa.Uuid(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("dom_fingerprint_sha256", sa.String(length=64), nullable=False),
        sa.Column("redirect_count", sa.Integer(), nullable=False),
        sa.Column("timing_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_gst_portal_profiles_job_id", "gst_portal_profiles", ["job_id"])
    op.create_index("ix_gst_portal_profiles_context_id", "gst_portal_profiles", ["context_id"])
    op.create_index("ix_gst_portal_profiles_dom_fingerprint_sha256", "gst_portal_profiles", ["dom_fingerprint_sha256"])
    op.create_index("ix_gst_portal_profiles_created_at", "gst_portal_profiles", ["created_at"])

    op.create_table(
        "gst_dom_snapshots",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("context_id", sa.Uuid(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("dom_fingerprint_sha256", sa.String(length=64), nullable=False),
        sa.Column("artifact_relpath", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_gst_dom_snapshots_job_id", "gst_dom_snapshots", ["job_id"])
    op.create_index("ix_gst_dom_snapshots_context_id", "gst_dom_snapshots", ["context_id"])
    op.create_index("ix_gst_dom_snapshots_dom_fingerprint_sha256", "gst_dom_snapshots", ["dom_fingerprint_sha256"])
    op.create_index("ix_gst_dom_snapshots_created_at", "gst_dom_snapshots", ["created_at"])

    op.create_table(
        "gst_session_health",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("context_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_gst_session_health_job_id", "gst_session_health", ["job_id"])
    op.create_index("ix_gst_session_health_context_id", "gst_session_health", ["context_id"])
    op.create_index("ix_gst_session_health_state", "gst_session_health", ["state"])
    op.create_index("ix_gst_session_health_created_at", "gst_session_health", ["created_at"])

    op.create_table(
        "operator_checkpoints",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("context_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.String(length=128), nullable=True),
    )
    op.create_index("ix_operator_checkpoints_job_id", "operator_checkpoints", ["job_id"])
    op.create_index("ix_operator_checkpoints_context_id", "operator_checkpoints", ["context_id"])
    op.create_index("ix_operator_checkpoints_kind", "operator_checkpoints", ["kind"])
    op.create_index("ix_operator_checkpoints_status", "operator_checkpoints", ["status"])
    op.create_index("ix_operator_checkpoints_created_at", "operator_checkpoints", ["created_at"])
    op.create_index("ix_operator_checkpoints_resolved_at", "operator_checkpoints", ["resolved_at"])


def downgrade() -> None:
    op.drop_table("operator_checkpoints")
    op.drop_table("gst_session_health")
    op.drop_table("gst_dom_snapshots")
    op.drop_table("gst_portal_profiles")
