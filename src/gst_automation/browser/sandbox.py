from __future__ import annotations

import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from gst_automation.archive.hashing import sha256_file
from gst_automation.core.exceptions import StorageError


@dataclass(frozen=True, slots=True)
class DownloadResult:
    path: Path
    sha256_hex: str
    byte_size: int


@dataclass(frozen=True, slots=True)
class DownloadSandbox:
    """Per-context download sandbox with atomic finalization and hashing."""

    root: Path
    download_timeout_seconds: int

    def allocate(self) -> tuple[Path, Path]:
        workspace = self.root / f"ws_{uuid.uuid4()}"
        downloads = workspace / "downloads"
        workspace.mkdir(parents=True, exist_ok=False)
        downloads.mkdir(parents=True, exist_ok=False)
        return workspace, downloads

    def finalize_file(self, *, tmp_path: Path, final_dir: Path, final_name: str) -> DownloadResult:
        if not tmp_path.exists() or not tmp_path.is_file():
            raise StorageError("download missing")
        final_dir.mkdir(parents=True, exist_ok=True)
        dest = final_dir / final_name
        tmp_dest = final_dir / f".{final_name}.tmp"
        shutil.copy2(tmp_path, tmp_dest)
        sha = sha256_file(tmp_dest)
        size = tmp_dest.stat().st_size
        tmp_dest.replace(dest)
        return DownloadResult(path=dest, sha256_hex=sha, byte_size=size)

    def cleanup(self, workspace: Path) -> None:
        shutil.rmtree(workspace, ignore_errors=True)

