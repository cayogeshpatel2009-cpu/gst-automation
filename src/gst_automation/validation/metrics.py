from __future__ import annotations

from prometheus_client import Counter, Histogram


PORTAL_SMOKE_RUNS_TOTAL = Counter(
    "gst_portal_smoke_runs_total",
    "Total portal_smoke job runs",
    ["result"],
)

PORTAL_SMOKE_ACTIONS_TOTAL = Counter(
    "gst_portal_smoke_actions_total",
    "Total portal_smoke actions executed",
    ["kind", "result"],
)

PORTAL_SMOKE_ACTION_SECONDS = Histogram(
    "gst_portal_smoke_action_seconds",
    "portal_smoke action durations",
    ["kind"],
)

CHAOS_EVENTS_TOTAL = Counter(
    "gst_browser_chaos_events_total",
    "Total browser chaos injections executed",
    ["scenario", "result"],
)

