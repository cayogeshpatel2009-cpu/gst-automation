from __future__ import annotations

from prometheus_client import Counter, Histogram


GSTR2B_RUNS_TOTAL = Counter(
    "gst_gstr2b_runs_total",
    "Total gstr2b_download runs",
    ["result"],
)

GSTR2B_DOWNLOAD_SECONDS = Histogram(
    "gst_gstr2b_download_seconds",
    "Time spent waiting for GSTR2B download",
    buckets=(1, 5, 15, 30, 60, 120, 300, 600),
)

GSTR2B_XLSX_VALIDATION_TOTAL = Counter(
    "gst_gstr2b_xlsx_validation_total",
    "XLSX validation outcomes for GSTR2B",
    ["result"],
)

