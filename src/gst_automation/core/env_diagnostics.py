from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gst_automation.core.env_bootstrap import resolve_env_file


@dataclass(frozen=True, slots=True)
class EnvDiagnostics:
    env_file_detected: bool
    resolved_env_path: str | None
    cwd: str
    database_url_loaded: bool
    migration_url_loaded: bool
    env_source: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "env_file_detected": self.env_file_detected,
            "resolved_env_path": self.resolved_env_path,
            "cwd": self.cwd,
            "database_url_loaded": self.database_url_loaded,
            "migration_url_loaded": self.migration_url_loaded,
            "env_source": self.env_source,
        }


def diagnose_env(*, cwd: Path | None = None) -> EnvDiagnostics:
    """
    Deterministic diagnostics for `.env` resolution and DB env var presence.

    Note: this reports what is present in the environment *at process runtime*.
    The effective Settings values may come from `.env` even if env vars are not exported.
    """
    base = (cwd or Path.cwd()).resolve()
    env_path = resolve_env_file(cwd=base)
    detected = bool(env_path and env_path.is_file())

    # Prefer actual environment var presence (what Alembic env.py historically depended on).
    database_url_loaded = bool(os.getenv("DATABASE_URL"))
    migration_url_loaded = bool(os.getenv("DATABASE_MIGRATION_URL"))

    source = "os.environ"
    if os.getenv("GST_AUTOMATION_ENV_FILE"):
        source = "GST_AUTOMATION_ENV_FILE"
    elif detected:
        source = "walk_upwards"

    return EnvDiagnostics(
        env_file_detected=detected,
        resolved_env_path=str(env_path) if env_path else None,
        cwd=str(base),
        database_url_loaded=database_url_loaded,
        migration_url_loaded=migration_url_loaded,
        env_source=source,
    )

