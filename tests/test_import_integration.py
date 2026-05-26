from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from openpyxl import Workbook
from alembic import command
from alembic.config import Config

from gst_automation.clients.excel_parser import COLUMNS
from gst_automation.clients.import_pipeline import ClientImportPipeline
from gst_automation.core.settings import Settings
from gst_automation.db.session import Db


@pytest.mark.integration
def test_fresh_db_migrate_and_import(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Opt-in integration test: requires a real Postgres configured via env.
    if not (os.getenv("DATABASE_URL") and os.getenv("DATABASE_MIGRATION_URL")):
        pytest.skip("Set DATABASE_URL and DATABASE_MIGRATION_URL to run integration test")

    # Use deterministic file-vault in tests (avoid OS keyring dependency).
    monkeypatch.setenv("VAULT_PROVIDER", "file")
    monkeypatch.setenv("VAULT_MASTER_KEY", "test-master-key-123")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))

    # Build sample workbook with 4 rows.
    p = tmp_path / "client_master.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "CLIENT_MASTER"
    ws.append(COLUMNS)
    for i in range(4):
        ws.append(
            [
                f"CLIENT{i+1:03d}",
                f"Client {i+1}",
                f"24ABCDE1234F1Z{i}",
                f"user{i+1}",
                "pw",
                "test@gmail.com",
                "2025-26",
                "TRUE",
                "MEDIUM",
                "",
                16,
                "",
            ]
        )
    wb.save(p)

    async def _run() -> None:
        settings = Settings.load()

        # Ensure migrations are applied.
        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", str(settings.database_migration_url))
        command.upgrade(cfg, "head")

        db = Db(str(settings.database_url))
        async with db.session() as session:
            rep = await ClientImportPipeline(settings=settings).import_xlsx(session, path=p, dry_run=False)
            await session.commit()
            assert rep.ok
            assert rep.created == 4
        await db.close()

    asyncio.run(_run())
