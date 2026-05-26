from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram


JOB_TRANSITIONS_TOTAL = Counter(
    "gst_job_transitions_total",
    "Total job state transitions",
    ["from_state", "to_state", "reason_code"],
)

JOB_ENQUEUED_TOTAL = Counter(
    "gst_jobs_enqueued_total",
    "Total jobs enqueued to Celery",
    ["queue"],
)

LEASE_HEARTBEATS_TOTAL = Counter(
    "gst_job_lease_heartbeats_total",
    "Total job lease heartbeats",
    ["result"],
)

LOCK_ACQUIRE_TOTAL = Counter(
    "gst_lock_acquire_total",
    "Total distributed lock acquisitions",
    ["result"],
)

WATCHDOG_TICKS_TOTAL = Counter(
    "gst_watchdog_ticks_total",
    "Total watchdog ticks",
    ["result"],
)

SCHEDULER_SELECTED = Gauge(
    "gst_scheduler_selected_jobs",
    "Jobs selected per scheduling tick",
)

QUEUE_OVERLOAD = Gauge(
    "gst_queue_overload",
    "Backpressure overload flag (1/0)",
    ["queue"],
)

JOB_LATENCY_SECONDS = Histogram(
    "gst_job_latency_seconds",
    "Job latency from created_at to completion",
    buckets=(1, 5, 15, 30, 60, 120, 300, 600, 1800, 3600),
)

