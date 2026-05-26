from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


_BAD = re.compile(r"[^A-Za-z0-9._ -]+")


def _sanitize(segment: str) -> str:
    s = segment.strip().replace("/", "-").replace("\\", "-")
    s = _BAD.sub("_", s)
    s = re.sub(r"_+", "_", s)
    return s[:80] if len(s) > 80 else s


@dataclass(frozen=True, slots=True)
class FolderLayout:
    client_root: Path
    period_root: Path
    gstr2b_dir: Path
    logs_dir: Path
    replay_dir: Path
    screenshots_dir: Path
    downloads_dir: Path


@dataclass(frozen=True, slots=True)
class FolderManager:
    """Deterministic folder structure for per-client GST execution outputs."""

    folder_root: Path

    def layout(self, *, client_name: str, gstin: str, fy: str, period_yyyy_mm: str) -> FolderLayout:
        client_dir = self.folder_root / _sanitize(client_name) / _sanitize(gstin) / _sanitize(fy) / _sanitize(period_yyyy_mm)
        return FolderLayout(
            client_root=client_dir.parent.parent.parent,  # CLIENT/GSTIN/FY
            period_root=client_dir,
            gstr2b_dir=client_dir / "GSTR2B",
            logs_dir=client_dir / "LOGS",
            replay_dir=client_dir / "REPLAY",
            screenshots_dir=client_dir / "SCREENSHOTS",
            downloads_dir=client_dir / "DOWNLOADS",
        )

    def ensure(self, layout: FolderLayout) -> None:
        for p in [
            layout.period_root,
            layout.gstr2b_dir,
            layout.logs_dir,
            layout.replay_dir,
            layout.screenshots_dir,
            layout.downloads_dir,
        ]:
            p.mkdir(parents=True, exist_ok=True)

