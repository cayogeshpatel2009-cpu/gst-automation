from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class WorkflowRecorder:
    """Append-only workflow recorder (JSONL) for replay/forensics.

    This intentionally stores events as an artifact file so failures are preserved even
    if the worker crashes before DB writes complete.
    """

    path: Path

    def record(self, event: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, sort_keys=True, separators=(",", ":")))
            f.write("\n")

    def now_ms(self) -> int:
        return int(time.time() * 1000)

