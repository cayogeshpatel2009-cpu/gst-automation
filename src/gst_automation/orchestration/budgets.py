from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TimeBudget:
    warn_seconds: int
    hard_seconds: int


class BudgetRegistry:
    """Registry of execution time budgets per job kind."""

    _budgets: dict[str, TimeBudget] = {
        # Placeholders; actual GST/browser budgets will be populated in Phase 4.
        "noop": TimeBudget(warn_seconds=10, hard_seconds=30),
        # Validation workflow: should finish quickly but allow traces/har/downloads.
        "portal_smoke": TimeBudget(warn_seconds=30, hard_seconds=180),
        "real_site_smoke": TimeBudget(warn_seconds=30, hard_seconds=180),
        "gst_safe_probe": TimeBudget(warn_seconds=60, hard_seconds=300),
        "gst_auth_session": TimeBudget(warn_seconds=300, hard_seconds=3600),
        "gst_observation_session": TimeBudget(warn_seconds=600, hard_seconds=7200),
        "assisted_gstr2b_execution": TimeBudget(warn_seconds=120, hard_seconds=900),
        "gstr2b_download": TimeBudget(warn_seconds=120, hard_seconds=900),
        "email_delivery": TimeBudget(warn_seconds=30, hard_seconds=120),
    }

    def budget_for(self, kind: str) -> TimeBudget:
        return self._budgets.get(kind, TimeBudget(warn_seconds=60, hard_seconds=300))
