from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


SelectorKind = Literal["css", "text", "role", "aria"]


@dataclass(frozen=True, slots=True)
class SelectorCandidate:
    kind: SelectorKind
    value: str
    weight: int = 100  # higher is preferred


@dataclass(frozen=True, slots=True)
class SelectorDefinition:
    key: str
    version: int
    candidates: tuple[SelectorCandidate, ...]

