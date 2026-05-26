from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ArchiveManifestEntry:
    stored_relpath: str
    sha256_hex: str
    byte_size: int
    created_at: str
    original_filename: str
    kind: str

    @staticmethod
    def now_iso() -> str:
        return datetime.now(UTC).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "stored_relpath": self.stored_relpath,
            "sha256_hex": self.sha256_hex,
            "byte_size": self.byte_size,
            "created_at": self.created_at,
            "original_filename": self.original_filename,
            "kind": self.kind,
        }


def append_manifest_line(manifest_path: Path, entry: ArchiveManifestEntry) -> None:
    """Append-only manifest (jsonl). Uses atomic append semantics best-effort per OS."""
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry.to_dict(), sort_keys=True, separators=(",", ":"))
    with manifest_path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(line + "\n")

