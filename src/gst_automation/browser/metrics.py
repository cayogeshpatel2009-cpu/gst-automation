from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram


BROWSER_LAUNCH_TOTAL = Counter(
    "gst_browser_launch_total",
    "Total browser launches",
    ["result"],
)

BROWSER_RESTART_TOTAL = Counter(
    "gst_browser_restart_total",
    "Total browser restarts",
    ["reason"],
)

CONTEXT_ALLOC_TOTAL = Counter(
    "gst_browser_context_alloc_total",
    "Total browser context allocations",
    ["result"],
)

CONTEXT_ACTIVE = Gauge(
    "gst_browser_context_active",
    "Active contexts in this worker process",
)

BROWSER_ACTIVE = Gauge(
    "gst_browser_active",
    "Active browsers in this worker process",
)

BROWSER_RSS_MB = Gauge(
    "gst_browser_rss_mb",
    "Browser process RSS (MB)",
    ["browser_id"],
)

NAVIGATION_SECONDS = Histogram(
    "gst_browser_navigation_seconds",
    "Navigation durations",
    buckets=(0.5, 1, 2, 5, 10, 20, 60, 120),
)

DOWNLOAD_SECONDS = Histogram(
    "gst_browser_download_seconds",
    "Download durations",
    buckets=(0.5, 1, 2, 5, 10, 20, 60, 120, 300),
)

ARTIFACTS_TOTAL = Counter(
    "gst_browser_artifacts_total",
    "Artifacts persisted",
    ["kind"],
)

