from __future__ import annotations

from dataclasses import dataclass

from gst_automation.portal.errors import SelectorNotFound
from gst_automation.portal.selectors.types import SelectorDefinition


@dataclass(frozen=True, slots=True)
class SelectorRegistry:
    """In-memory selector registry (can be hydrated from DB or files)."""

    definitions: dict[tuple[str, int], SelectorDefinition]

    def get(self, *, key: str, version: int) -> SelectorDefinition:
        d = self.definitions.get((key, version))
        if d is None:
            raise SelectorNotFound(f"selector not found: {key}@{version}")
        return d

    def latest(self, *, key: str) -> SelectorDefinition:
        versions = [v for (k, v) in self.definitions.keys() if k == key]
        if not versions:
            raise SelectorNotFound(f"selector not found: {key}")
        return self.get(key=key, version=max(versions))

