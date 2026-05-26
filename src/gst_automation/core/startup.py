from __future__ import annotations

from dataclasses import dataclass

from gst_automation.core.exceptions import StartupValidationError
from gst_automation.core.settings import Settings
from gst_automation.core.db_diagnostics import validate_db_url
from gst_automation.storage.paths import ensure_directories
from gst_automation.vault.factory import build_vault
from gst_automation.celery_app.client import get_celery


@dataclass(frozen=True, slots=True)
class StartupValidator:
    """Performs startup validation in a deterministic, testable way."""

    settings: Settings

    async def validate_or_raise(self) -> None:
        errors: list[str] = []

        try:
            validate_db_url(str(self.settings.database_url), label="DATABASE_URL")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"db: {exc}")

        try:
            if self.settings.database_migration_url:
                validate_db_url(str(self.settings.database_migration_url), label="DATABASE_MIGRATION_URL")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"db_migration: {exc}")

        try:
            ensure_directories(self.settings)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"storage: {exc}")

        try:
            build_vault(self.settings)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"vault: {exc}")

        try:
            # Validates that Celery config can be constructed (broker connection checked by workers).
            get_celery()
        except Exception as exc:  # noqa: BLE001
            errors.append(f"celery: {exc}")

        if errors:
            raise StartupValidationError("; ".join(errors))
