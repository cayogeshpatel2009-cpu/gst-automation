from __future__ import annotations

from typing import Final


JOB_STATES: Final[set[str]] = {
    "pending",
    "queued",
    "leased",
    "running",
    "retrying",
    "paused",
    "completed",
    "failed",
    "dead_lettered",
    "cancelled",
}

