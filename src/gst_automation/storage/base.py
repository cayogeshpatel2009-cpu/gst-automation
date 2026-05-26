from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True, slots=True)
class StoredBlob:
    """Reference to a stored blob (no open file handles)."""

    path: Path
    byte_size: int


class BlobStore(Protocol):
    """Storage contract for non-immutable working storage."""

    async def put_bytes(self, *, relpath: str, payload: bytes) -> StoredBlob: ...
    async def put_file(self, *, relpath: str, source_path: Path) -> StoredBlob: ...
    async def get_path(self, *, relpath: str) -> Path: ...

