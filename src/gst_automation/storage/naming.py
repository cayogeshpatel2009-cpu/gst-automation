from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from gst_automation.storage.sanitize import safe_segment


@dataclass(frozen=True, slots=True)
class FileNaming:
    """Centralized file naming rules for deterministic, testable outputs."""

    prefix: str = "gstr2b"

    def download_basename(self, gstin: str, period: str, source: str) -> str:
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        return f"{self.prefix}_{safe_segment(gstin)}_{safe_segment(period)}_{safe_segment(source)}_{ts}"

