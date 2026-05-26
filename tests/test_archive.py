from __future__ import annotations

from pathlib import Path

import pytest

from gst_automation.archive.archiver import ImmutableArchiver
from gst_automation.core.settings import Settings


def _settings(tmp_path: Path) -> Settings:
    return Settings.model_validate(
        {
            "DATABASE_URL": "postgresql+asyncpg://x:y@localhost:5432/z",
            "DATA_DIR": str(tmp_path / "data"),
            "ARCHIVE_DIR": str(tmp_path / "archive"),
            "WORK_DIR": str(tmp_path / "work"),
            "VAULT_PROVIDER": "keyring",
        }
    )


def test_archiver_writes_manifest(tmp_path: Path) -> None:
    src = tmp_path / "source.txt"
    src.write_text("hello", encoding="utf-8")

    settings = _settings(tmp_path)
    archiver = ImmutableArchiver(settings)
    result = archiver.archive_file(
        client_gstin="22AAAAA0000A1Z5",
        kind="gstr2b",
        source_path=src,
        original_filename="gstr2b.txt",
    )
    assert result.stored_path.exists()
    manifest = Path(settings.archive_dir) / "manifest.jsonl"
    assert manifest.exists()
    assert "sha256_hex" in manifest.read_text(encoding="utf-8")

