from __future__ import annotations

import keyring

from gst_automation.core.exceptions import VaultError
from gst_automation.vault.base import SecretRef, Vault


class KeyringVault(Vault):
    """OS keyring-based vault (recommended for operators on workstations)."""

    def __init__(self, *, service_name: str) -> None:
        self._service = service_name

    async def get_secret(self, ref: SecretRef) -> str:
        value = keyring.get_password(self._service, ref.to_id())
        if value is None:
            raise VaultError(f"Secret not found: {ref.to_id()}")
        return value

    async def set_secret(self, ref: SecretRef, value: str) -> None:
        try:
            keyring.set_password(self._service, ref.to_id(), value)
        except Exception as exc:  # noqa: BLE001
            raise VaultError("Keyring set failed") from exc

    async def delete_secret(self, ref: SecretRef) -> None:
        try:
            keyring.delete_password(self._service, ref.to_id())
        except keyring.errors.PasswordDeleteError:
            return
        except Exception as exc:  # noqa: BLE001
            raise VaultError("Keyring delete failed") from exc

