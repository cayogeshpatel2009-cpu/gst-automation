from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from gst_automation.core.exceptions import StorageError
from gst_automation.storage.base import BlobStore, StoredBlob
from gst_automation.storage.sanitize import safe_segment


@dataclass(frozen=True, slots=True)
class LocalBlobStore(BlobStore):
    """Local filesystem store rooted at `root` for working artifacts."""

    root: Path

    def _resolve(self, relpath: str) -> Path:
        parts = [safe_segment(p) for p in relpath.replace("\\", "/").split("/") if p]
        if not parts:
            raise StorageError("Invalid relpath")
        return self.root.joinpath(*parts)

    async def put_bytes(self, *, relpath: str, payload: bytes) -> StoredBlob:
        dest = self._resolve(relpath)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        tmp.write_bytes(payload)
        tmp.replace(dest)
        return StoredBlob(path=dest, byte_size=dest.stat().st_size)

    async def put_file(self, *, relpath: str, source_path: Path) -> StoredBlob:
        if not source_path.exists() or not source_path.is_file():
            raise StorageError(f"Source path not found: {source_path}")
        dest = self._resolve(relpath)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        shutil.copy2(source_path, tmp)
        tmp.replace(dest)
        return StoredBlob(path=dest, byte_size=dest.stat().st_size)

    async def get_path(self, *, relpath: str) -> Path:
        dest = self._resolve(relpath)
        if not dest.exists():
            raise StorageError(f"Blob not found: {relpath}")
        return dest

