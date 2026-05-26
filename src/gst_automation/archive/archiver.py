from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from gst_automation.archive.hashing import sha256_file
from gst_automation.archive.manifest import ArchiveManifestEntry, append_manifest_line
from gst_automation.core.exceptions import ArchiveError
from gst_automation.core.settings import Settings
from gst_automation.storage.naming import FileNaming
from gst_automation.storage.paths import ensure_directories, resolve_paths
from gst_automation.storage.sanitize import safe_segment


@dataclass(frozen=True, slots=True)
class ArchiveResult:
    stored_path: Path
    sha256_hex: str
    byte_size: int


class ImmutableArchiver:
    """Stores files into an append-only archive with hashing and read-only hardening."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        ensure_directories(settings)
        self._paths = resolve_paths(settings)
        self._naming = FileNaming()

    def archive_file(
        self,
        *,
        client_gstin: str,
        kind: str,
        source_path: Path,
        original_filename: str,
    ) -> ArchiveResult:
        if self._settings.archive_read_only:
            raise ArchiveError("Archive is configured read-only.")
        if not source_path.exists() or not source_path.is_file():
            raise ArchiveError(f"Source path not found: {source_path}")

        client_dir = self._paths.archive_dir / safe_segment(client_gstin) / safe_segment(kind)
        client_dir.mkdir(parents=True, exist_ok=True)

        basename = self._naming.download_basename(client_gstin, period="na", source=kind)
        ext = "".join(Path(original_filename).suffixes) or source_path.suffix
        filename = f"{basename}{ext}"

        dest = client_dir / filename
        tmp = client_dir / f".{filename}.tmp"
        try:
            shutil.copy2(source_path, tmp)
            sha256_hex = sha256_file(tmp)
            byte_size = tmp.stat().st_size
            tmp.replace(dest)

            # Append manifest entry (jsonl)
            rel = dest.relative_to(self._paths.archive_dir).as_posix()
            append_manifest_line(
                self._paths.archive_dir / "manifest.jsonl",
                ArchiveManifestEntry(
                    stored_relpath=rel,
                    sha256_hex=sha256_hex,
                    byte_size=byte_size,
                    created_at=ArchiveManifestEntry.now_iso(),
                    original_filename=original_filename,
                    kind=kind,
                ),
            )

            self._harden_readonly(dest)
            return ArchiveResult(stored_path=dest, sha256_hex=sha256_hex, byte_size=byte_size)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass

    def _harden_readonly(self, path: Path) -> None:
        """Best-effort immutability: chmod read-only on *nix; no-op on Windows."""
        if os.name == "nt":
            return
        path.chmod(0o440)

