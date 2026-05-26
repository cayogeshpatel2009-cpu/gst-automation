from __future__ import annotations

import os

import pytest

from gst_automation.core.exceptions import ConfigurationError
from gst_automation.core.settings import Settings
from gst_automation.core.db_diagnostics import validate_db_url


def test_settings_requires_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    # Force Settings.load() to *not* pick up the repo root `.env` during tests.
    monkeypatch.setenv("GST_AUTOMATION_ENV_FILE", str(os.path.join(os.getcwd(), "does-not-exist.env")))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    # Ensure cache doesn't pollute across tests.
    Settings.load.cache_clear()  # type: ignore[attr-defined]
    with pytest.raises(ConfigurationError):
        Settings.load()


def test_settings_loads_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:y@localhost:5432/z")
    Settings.load.cache_clear()  # type: ignore[attr-defined]
    s = Settings.load()
    assert str(s.database_url).startswith("postgresql+asyncpg://")


def test_validate_db_url_rejects_malformed() -> None:
    with pytest.raises(ConfigurationError):
        validate_db_url("postgresql+asyncpg://postgres:pw@local", label="DATABASE_URL")


def test_validate_db_url_rejects_missing_password() -> None:
    with pytest.raises(ConfigurationError):
        validate_db_url("postgresql+asyncpg://postgres@localhost:5432/gstautomation", label="DATABASE_URL")


def test_validate_db_url_rejects_invalid_scheme() -> None:
    with pytest.raises(ConfigurationError):
        validate_db_url("mysql+pymysql://u:p@localhost:3306/x", label="DATABASE_URL")


def test_validate_db_url_rejects_missing_dbname() -> None:
    with pytest.raises(ConfigurationError):
        validate_db_url("postgresql+asyncpg://postgres:pw@localhost:5432", label="DATABASE_URL")
