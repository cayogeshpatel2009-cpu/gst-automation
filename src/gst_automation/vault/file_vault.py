from __future__ import annotations

import json
from pathlib import Path

from gst_automation.core.exceptions import VaultError
from gst_automation.vault.base import SecretRef, Vault
from gst_automation.vault.crypto import build_fernet


class EncryptedFileVault(Vault):
    """Encrypted file-backed vault for local/dev usage (Fernet)."""

    def __init__(self, *, vault_path: Path, master_key: str) -> None:
        self._path = vault_path
        self._fernet = build_fernet(master_key)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    async def get_secret(self, ref: SecretRef) -> str:
        data = self._read_all()
        token = data.get(ref.to_id())
        if token is None:
            raise VaultError(f"Secret not found: {ref.to_id()}")
        try:
            return self._fernet.decrypt(token.encode("utf-8")).decode("utf-8")
        except Exception as exc:  # noqa: BLE001
            raise VaultError("Secret decrypt failed") from exc

    async def set_secret(self, ref: SecretRef, value: str) -> None:
        data = self._read_all()
        token = self._fernet.encrypt(value.encode("utf-8")).decode("utf-8")
        data[ref.to_id()] = token
        self._write_all(data)

    async def delete_secret(self, ref: SecretRef) -> None:
        data = self._read_all()
        data.pop(ref.to_id(), None)
        self._write_all(data)

    def _read_all(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise VaultError("Vault read failed") from exc

    def _write_all(self, data: dict[str, str]) -> None:
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        tmp.replace(self._path)

