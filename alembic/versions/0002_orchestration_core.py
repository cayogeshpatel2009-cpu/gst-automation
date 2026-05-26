"""orchestration core schema

Revision ID: 0002_orchestration_core
Revises: 0001_foundation
Create Date: 2026-05-20
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0002_orchestration_core"
down_revision = "0001_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=128), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("queue", sa.String(length=64), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("idempotency_key", name="uq_jobs_idempotency_key"),
    )
    op.create_index("ix_jobs_state", "jobs", ["state"])
    op.create_index("ix_jobs_queue", "jobs", ["queue"])
    op.create_index("ix_jobs_priority", "jobs", ["priority"])
    op.create_index("ix_jobs_created_at", "jobs", ["created_at"])
    op.create_index("ix_jobs_updated_at", "jobs", ["updated_at"])
    op.create_index("ix_jobs_next_run_at", "jobs", ["next_run_at"])

    op.create_table(
        "job_leases",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("worker_name", sa.String(length=128), nullable=False),
        sa.Column("lease_token", sa.String(length=128), nullable=False),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("job_id", name="uq_job_leases_job_id"),
        sa.UniqueConstraint("lease_token", name="uq_job_leases_lease_token"),
    )
    op.create_index("ix_job_leases_job_id", "job_leases", ["job_id"])
    op.create_index("ix_job_leases_worker_name", "job_leases", ["worker_name"])
    op.create_index("ix_job_leases_expires_at", "job_leases", ["expires_at"])
    op.create_index("ix_job_leases_last_heartbeat_at", "job_leases", ["last_heartbeat_at"])

    op.create_table(
        "job_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("worker_name", sa.String(length=128), nullable=False),
        sa.Column("lease_token", sa.String(length=128), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_class", sa.String(length=256), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_details_json", sa.Text(), nullable=True),
    )
    op.create_index("ix_job_attempts_job_id", "job_attempts", ["job_id"])
    op.create_index("ix_job_attempts_status", "job_attempts", ["status"])
    op.create_index("ix_job_attempts_worker_name", "job_attempts", ["worker_name"])
    op.create_index("ix_job_attempts_lease_token", "job_attempts", ["lease_token"])
    op.create_index("ix_job_attempts_trace_id", "job_attempts", ["trace_id"])
    op.create_index("ix_job_attempts_correlation_id", "job_attempts", ["correlation_id"])
    op.create_index("ix_job_attempts_run_id", "job_attempts", ["run_id"])

    op.create_table(
        "workers",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("worker_name", sa.String(length=128), nullable=False),
        sa.Column("hostname", sa.String(length=255), nullable=False),
        sa.Column("pid", sa.Integer(), nullable=False),
        sa.Column("queues_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("worker_name", name="uq_workers_worker_name"),
    )
    op.create_index("ix_workers_worker_name", "workers", ["worker_name"])
    op.create_index("ix_workers_status", "workers", ["status"])
    op.create_index("ix_workers_last_heartbeat_at", "workers", ["last_heartbeat_at"])

    op.create_table(
        "worker_heartbeats",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("worker_name", sa.String(length=128), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cpu_percent", sa.Integer(), nullable=False),
        sa.Column("memory_rss_bytes", sa.Integer(), nullable=False),
        sa.Column("active_jobs", sa.Integer(), nullable=False),
        sa.Column("health_state", sa.String(length=32), nullable=False),
    )
    op.create_index("ix_worker_heartbeats_worker_name", "worker_heartbeats", ["worker_name"])
    op.create_index("ix_worker_heartbeats_heartbeat_at", "worker_heartbeats", ["heartbeat_at"])
    op.create_index("ix_worker_heartbeats_health_state", "worker_heartbeats", ["health_state"])

    op.create_table(
        "distributed_locks",
        sa.Column("name", sa.String(length=200), primary_key=True, nullable=False),
        sa.Column("owner_name", sa.String(length=128), nullable=False),
        sa.Column("token", sa.String(length=128), nullable=False),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("renewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("token", name="uq_distributed_locks_token"),
    )
    op.create_index("ix_distributed_locks_owner_name", "distributed_locks", ["owner_name"])
    op.create_index("ix_distributed_locks_token", "distributed_locks", ["token"])
    op.create_index("ix_distributed_locks_expires_at", "distributed_locks", ["expires_at"])

    op.create_table(
        "retry_history",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), nullable=True),
        sa.Column("classification", sa.String(length=64), nullable=False),
        sa.Column("backoff_seconds", sa.Integer(), nullable=False),
        sa.Column("jitter_seconds", sa.Integer(), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_retry_history_job_id", "retry_history", ["job_id"])
    op.create_index("ix_retry_history_attempt_id", "retry_history", ["attempt_id"])
    op.create_index("ix_retry_history_classification", "retry_history", ["classification"])
    op.create_index("ix_retry_history_scheduled_at", "retry_history", ["scheduled_at"])
    op.create_index("ix_retry_history_created_at", "retry_history", ["created_at"])

    op.create_table(
        "dead_letter_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("job_kind", sa.String(length=128), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("failure_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_dead_letter_jobs_job_id", "dead_letter_jobs", ["job_id"])
    op.create_index("ix_dead_letter_jobs_job_kind", "dead_letter_jobs", ["job_kind"])
    op.create_index("ix_dead_letter_jobs_created_at", "dead_letter_jobs", ["created_at"])

    op.create_table(
        "orchestration_events",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("client_id", sa.Uuid(), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_orchestration_events_event_type", "orchestration_events", ["event_type"])
    op.create_index("ix_orchestration_events_job_id", "orchestration_events", ["job_id"])
    op.create_index("ix_orchestration_events_client_id", "orchestration_events", ["client_id"])
    op.create_index("ix_orchestration_events_created_at", "orchestration_events", ["created_at"])
    op.create_index("ix_orchestration_events_processed_at", "orchestration_events", ["processed_at"])

    op.create_table(
        "queue_metrics",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("queue", sa.String(length=64), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("oldest_age_seconds", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_queue_metrics_queue", "queue_metrics", ["queue"])
    op.create_index("ix_queue_metrics_created_at", "queue_metrics", ["created_at"])


def downgrade() -> None:
    op.drop_table("queue_metrics")
    op.drop_table("orchestration_events")
    op.drop_table("dead_letter_jobs")
    op.drop_table("retry_history")
    op.drop_table("distributed_locks")
    op.drop_table("worker_heartbeats")
    op.drop_table("workers")
    op.drop_table("job_attempts")
    op.drop_table("job_leases")
    op.drop_table("jobs")

