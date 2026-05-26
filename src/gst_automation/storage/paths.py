from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from gst_automation.core.settings import Settings
from gst_automation.storage.sanitize import safe_segment


@dataclass(frozen=True, slots=True)
class StoragePaths:
    """Resolved storage root paths."""

    data_dir: Path
    archive_dir: Path
    work_dir: Path

    def client_root(self, gstin: str) -> Path:
        return self.data_dir / "clients" / safe_segment(gstin)

    def client_work(self, gstin: str) -> Path:
        return self.work_dir / safe_segment(gstin)

    def client_archive(self, gstin: str) -> Path:
        return self.archive_dir / safe_segment(gstin)


def resolve_paths(settings: Settings) -> StoragePaths:
    return StoragePaths(
        data_dir=Path(settings.data_dir),
        archive_dir=Path(settings.archive_dir),
        work_dir=Path(settings.work_dir),
    )


def ensure_directories(settings: Settings) -> StoragePaths:
    """Ensure directories exist with safe defaults; does not create per-client directories."""
    paths = resolve_paths(settings)
    for p in (paths.data_dir, paths.archive_dir, paths.work_dir):
        p.mkdir(parents=True, exist_ok=True)
    # Harden: avoid inheriting broad permissions on *nix where possible.
    if os.name != "nt":
        for p in (paths.data_dir, paths.archive_dir, paths.work_dir):
            p.chmod(0o750)
    return paths

