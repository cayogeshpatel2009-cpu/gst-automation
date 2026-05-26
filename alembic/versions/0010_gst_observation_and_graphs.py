"""gst observation sessions and workflow graphs

Revision ID: 0010_gst_observation_and_graphs
Revises: 0009_gst_readiness_persistence
Create Date: 2026-05-21
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0010_gst_observation_and_graphs"
down_revision = "0009_gst_readiness_persistence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gst_observation_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("context_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("start_url", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("operator_checkpoint_id", sa.Uuid(), nullable=True),
        sa.Column("steps_total", sa.Integer(), nullable=False),
        sa.Column("downloads_total", sa.Integer(), nullable=False),
        sa.Column("selectors_total", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_gst_observation_sessions_job_id", "gst_observation_sessions", ["job_id"])
    op.create_index("ix_gst_observation_sessions_context_id", "gst_observation_sessions", ["context_id"])
    op.create_index("ix_gst_observation_sessions_status", "gst_observation_sessions", ["status"])
    op.create_index(
        "ix_gst_observation_sessions_operator_checkpoint_id",
        "gst_observation_sessions",
        ["operator_checkpoint_id"],
    )
    op.create_index("ix_gst_observation_sessions_created_at", "gst_observation_sessions", ["created_at"])
    op.create_index("ix_gst_observation_sessions_ended_at", "gst_observation_sessions", ["ended_at"])

    op.create_table(
        "gst_workflow_graphs",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("observation_id", sa.Uuid(), nullable=False),
        sa.Column("graph_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_gst_workflow_graphs_observation_id", "gst_workflow_graphs", ["observation_id"])
    op.create_index("ix_gst_workflow_graphs_created_at", "gst_workflow_graphs", ["created_at"])


def downgrade() -> None:
    op.drop_table("gst_workflow_graphs")
    op.drop_table("gst_observation_sessions")

