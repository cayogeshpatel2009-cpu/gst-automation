from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TimingProfile:
    key_delay_ms_min: int = 35
    key_delay_ms_max: int = 110
    action_jitter_ms_min: int = 50
    action_jitter_ms_max: int = 250


class Humanizer:
    """Deterministic humanization helper (no CAPTCHA bypass)."""

    def __init__(self, *, seed: str, profile: TimingProfile | None = None) -> None:
        self._rng = random.Random(seed)
        self._profile = profile or TimingProfile()

    def key_delay_ms(self) -> int:
        return self._rng.randint(self._profile.key_delay_ms_min, self._profile.key_delay_ms_max)

    def action_jitter_ms(self) -> int:
        return self._rng.randint(self._profile.action_jitter_ms_min, self._profile.action_jitter_ms_max)

