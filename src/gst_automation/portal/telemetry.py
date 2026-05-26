from __future__ import annotations

from prometheus_client import Counter, Histogram


SELECTOR_ATTEMPTS_TOTAL = Counter(
    "gst_portal_selector_attempts_total",
    "Selector resolution attempts",
    ["key", "result"],
)

SELECTOR_FALLBACKS_TOTAL = Counter(
    "gst_portal_selector_fallbacks_total",
    "Selector fallbacks used",
    ["key"],
)

INTERACTIONS_TOTAL = Counter(
    "gst_portal_interactions_total",
    "Portal interactions",
    ["op", "result"],
)

NAVIGATIONS_TOTAL = Counter(
    "gst_portal_navigations_total",
    "Portal navigations",
    ["result"],
)

RECOVERY_ATTEMPTS_TOTAL = Counter(
    "gst_portal_recovery_attempts_total",
    "Recovery attempts",
    ["reason", "result"],
)

PORTAL_LATENCY_SECONDS = Histogram(
    "gst_portal_latency_seconds",
    "Navigation/portal latency observations",
    buckets=(0.5, 1, 2, 5, 10, 20, 60, 120),
)

