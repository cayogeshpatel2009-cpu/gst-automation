from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class SecretRef:
    """Stable reference to a stored secret (no secret material)."""

    namespace: str
    key: str

    def to_id(self) -> str:
        return f"{self.namespace}:{self.key}"


class Vault(Protocol):
    """Vault contract for storing and retrieving sensitive secrets."""

    async def get_secret(self, ref: SecretRef) -> str: ...
    async def set_secret(self, ref: SecretRef, value: str) -> None: ...
    async def delete_secret(self, ref: SecretRef) -> None: ...

