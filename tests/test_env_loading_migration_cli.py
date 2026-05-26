from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_migration_cli_loads_env_file(tmp_path: Path) -> None:
    """
    Regression: migration CLI must work from a fresh shell without manual env exports.

    We run `upgrade --sql` so Alembic executes in offline mode (no DB required),
    but still exercises `.env` loading and URL resolution inside alembic/env.py.
    """
    env_file = tmp_path / "test.env"
    env_file.write_text(
        "\n".join(
            [
                "DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/dbname",
                "DATABASE_MIGRATION_URL=postgresql+psycopg://user:pass@localhost:5432/dbname",
                "",
            ]
        ),
        encoding="utf-8",
    )

    repo_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["GST_AUTOMATION_ENV_FILE"] = str(env_file)
    env.pop("DATABASE_URL", None)
    env.pop("DATABASE_MIGRATION_URL", None)

    proc = subprocess.run(
        [sys.executable, "-m", "gst_automation.cli.db", "upgrade", "--sql"],
        cwd=str(repo_root),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert proc.returncode == 0, proc.stderr
    # Ensure env diagnostics were printed and URLs were resolved via Settings/.env.
    assert "[env]" in proc.stderr
    assert "settings_migration_url_present" in proc.stderr

