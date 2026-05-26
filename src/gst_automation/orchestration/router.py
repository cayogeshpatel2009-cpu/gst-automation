from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


QueueName = Literal["critical", "downloads", "emails", "monitoring", "maintenance", "dead_letter"]


@dataclass(frozen=True, slots=True)
class QueueRouter:
    """Priority-aware router with sane defaults and starvation prevention hooks."""

    def route(self, *, kind: str, requested_queue: QueueName, priority: int) -> QueueName:
        # Phase 2: honor requested queue; later we can enforce per-kind constraints.
        _ = kind
        if priority <= 2:
            return "critical" if requested_queue != "dead_letter" else "dead_letter"
        return requested_queue

