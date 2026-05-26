from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


RetryAction = Literal["retry", "dead_letter", "fail"]


@dataclass(frozen=True, slots=True)
class RetryDecision:
    action: RetryAction
    classification: str
    backoff_seconds: int
    jitter_seconds: int
    reason: str

