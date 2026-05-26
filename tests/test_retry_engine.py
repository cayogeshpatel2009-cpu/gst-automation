from __future__ import annotations

from gst_automation.core.exceptions import StorageError, VaultError
from gst_automation.retry.engine import RetryEngine


def test_retry_engine_storage_error_retries() -> None:
    eng = RetryEngine(max_backoff_seconds=60)
    d = eng.decide(StorageError("disk full"), attempt_no=1)
    assert d.action == "retry"
    assert d.classification == "storage_failure"
    assert d.backoff_seconds >= 5


def test_retry_engine_vault_error_dead_letters() -> None:
    eng = RetryEngine()
    d = eng.decide(VaultError("missing secret"), attempt_no=1)
    assert d.action == "dead_letter"
    assert d.classification == "vault_failure"

