from __future__ import annotations

import random

from gst_automation.core.exceptions import ArchiveError, StorageError, VaultError
from gst_automation.gst.errors import GstAuthRequired, GstDownloadCorrupt, GstDownloadInvalid
from gst_automation.retry.types import RetryDecision


class RetryEngine:
    """Classifies failures and produces retry decisions (exponential backoff + jitter)."""

    def __init__(self, *, max_backoff_seconds: int = 3600) -> None:
        self._max_backoff = max_backoff_seconds

    def decide(self, exc: BaseException, *, attempt_no: int) -> RetryDecision:
        classification = self._classify(exc)
        # Default budgets; later phases will introduce per-kind budgets and rolling windows.
        if classification in {
            "db_failure",
            "network_failure",
            "lock_contention",
            "storage_failure",
            "time_budget_exceeded",
            "auth_required",
        }:
            base = 300 if classification == "auth_required" else 5
            backoff = self._exp_backoff(attempt_no, base=base)
            jitter = random.randint(0, max(1, int(backoff * 0.2)))
            return RetryDecision(
                action="retry",
                classification=classification,
                backoff_seconds=backoff,
                jitter_seconds=jitter,
                reason=str(exc),
            )
        return RetryDecision(
            action="dead_letter",
            classification=classification,
            backoff_seconds=0,
            jitter_seconds=0,
            reason=str(exc),
        )

    def _exp_backoff(self, attempt_no: int, *, base: int) -> int:
        backoff = base * (2 ** max(attempt_no - 1, 0))
        return int(min(backoff, self._max_backoff))

    def _classify(self, exc: BaseException) -> str:
        # Playwright: map common transient failures to retryable classes.
        try:
            from playwright.async_api import TimeoutError as PlaywrightTimeoutError  # type: ignore
        except Exception:  # noqa: BLE001
            PlaywrightTimeoutError = None  # type: ignore[assignment]

        if PlaywrightTimeoutError is not None and isinstance(exc, PlaywrightTimeoutError):
            return "time_budget_exceeded"

        if isinstance(exc, TimeoutError):
            return "time_budget_exceeded"
        if isinstance(exc, VaultError):
            return "vault_failure"
        if isinstance(exc, ArchiveError):
            return "archive_failure"
        if isinstance(exc, StorageError):
            return "storage_failure"
        if isinstance(exc, GstAuthRequired):
            return "auth_required"
        if isinstance(exc, GstDownloadCorrupt):
            return "storage_failure"
        if isinstance(exc, GstDownloadInvalid):
            return "unknown_failure"
        # Later phases add portal/captcha/otp classifications.
        return "unknown_failure"
