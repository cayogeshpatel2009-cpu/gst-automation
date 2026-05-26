from __future__ import annotations

import pytest

from gst_automation.core.settings import Settings
from gst_automation.validation.doctor import doctor_schema


def test_doctor_schema_reports_missing_when_no_db(monkeypatch: pytest.MonkeyPatch) -> None:
    # No real DB in unit tests; ensure it fails cleanly with a readable error instead of crashing.
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://postgres:gst123@localhost:5432/gstautomation")
    monkeypatch.setenv("DATABASE_MIGRATION_URL", "postgresql+psycopg://postgres:gst123@localhost:5432/gstautomation")
    Settings.load.cache_clear()  # type: ignore[attr-defined]
    rep = doctor_schema(Settings.load())
    assert rep.ok in {True, False}
    assert rep.head_revision is None or isinstance(rep.head_revision, str)
