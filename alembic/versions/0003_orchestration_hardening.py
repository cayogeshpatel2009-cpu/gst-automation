"""orchestration hardening (fsm, transitions, fencing, events v2)

Revision ID: 0003_orchestration_hardening
Revises: 0002_orchestration_core
Create Date: 2026-05-20
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0003_orchestration_hardening"
down_revision = "0002_orchestration_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("version", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("jobs", sa.Column("state_updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")))
    op.create_index("ix_jobs_state_updated_at", "jobs", ["state_updated_at"])

    op.add_column("job_leases", sa.Column("worker_generation", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("job_leases", sa.Column("fencing_token", sa.BigInteger(), nullable=False, server_default="0"))
    op.create_index("ix_job_leases_fencing_token", "job_leases", ["fencing_token"])

    op.add_column("workers", sa.Column("generation", sa.Integer(), nullable=False, server_default="0"))

    op.add_column("orchestration_events", sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("orchestration_events", sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"))
    op.add_column("orchestration_events", sa.Column("trace_id", sa.String(length=64), nullable=False, server_default=""))
    op.add_column("orchestration_events", sa.Column("correlation_id", sa.String(length=64), nullable=False, server_default=""))
    op.add_column("orchestration_events", sa.Column("run_id", sa.String(length=64), nullable=False, server_default=""))
    op.add_column("orchestration_events", sa.Column("actor", sa.String(length=128), nullable=False, server_default=""))
    op.create_index("ix_orchestration_events_trace_id", "orchestration_events", ["trace_id"])
    op.create_index("ix_orchestration_events_correlation_id", "orchestration_events", ["correlation_id"])
    op.create_index("ix_orchestration_events_run_id", "orchestration_events", ["run_id"])
    op.create_index("ix_orchestration_events_actor", "orchestration_events", ["actor"])

    op.create_table(
        "job_transitions",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("seq_no", sa.Integer(), nullable=False),
        sa.Column("from_state", sa.String(length=32), nullable=False),
        sa.Column("to_state", sa.String(length=32), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column("reason_details_json", sa.Text(), nullable=False),
        sa.Column("actor", sa.String(length=128), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("job_id", "seq_no", name="uq_job_transitions_job_seq"),
    )
    op.create_index("ix_job_transitions_job_id", "job_transitions", ["job_id"])
    op.create_index("ix_job_transitions_to_state", "job_transitions", ["to_state"])
    op.create_index("ix_job_transitions_actor", "job_transitions", ["actor"])
    op.create_index("ix_job_transitions_trace_id", "job_transitions", ["trace_id"])
    op.create_index("ix_job_transitions_correlation_id", "job_transitions", ["correlation_id"])
    op.create_index("ix_job_transitions_run_id", "job_transitions", ["run_id"])
    op.create_index("ix_job_transitions_created_at", "job_transitions", ["created_at"])


def downgrade() -> None:
    op.drop_table("job_transitions")

    op.drop_index("ix_orchestration_events_actor", table_name="orchestration_events")
    op.drop_index("ix_orchestration_events_run_id", table_name="orchestration_events")
    op.drop_index("ix_orchestration_events_correlation_id", table_name="orchestration_events")
    op.drop_index("ix_orchestration_events_trace_id", table_name="orchestration_events")
    op.drop_index("ix_orchestration_events_actor", table_name="orchestration_events")
    op.drop_column("orchestration_events", "actor")
    op.drop_column("orchestration_events", "run_id")
    op.drop_column("orchestration_events", "correlation_id")
    op.drop_column("orchestration_events", "trace_id")
    op.drop_column("orchestration_events", "metadata_json")
    op.drop_column("orchestration_events", "schema_version")

    op.drop_column("workers", "generation")

    op.drop_index("ix_job_leases_fencing_token", table_name="job_leases")
    op.drop_column("job_leases", "fencing_token")
    op.drop_column("job_leases", "worker_generation")

    op.drop_index("ix_jobs_state_updated_at", table_name="jobs")
    op.drop_column("jobs", "state_updated_at")
    op.drop_column("jobs", "version")

