from __future__ import annotations

from pathlib import Path

from gst_automation.core.exceptions import ConfigurationError
from gst_automation.core.settings import Settings
from gst_automation.vault.base import Vault
from gst_automation.vault.file_vault import EncryptedFileVault
from gst_automation.vault.keyring_vault import KeyringVault


def build_vault(settings: Settings) -> Vault:
    """Build the vault implementation from settings."""
    if settings.vault_provider == "keyring":
        return KeyringVault(service_name="gst-automation-platform")
    if settings.vault_provider == "file":
        if not settings.vault_master_key:
            raise ConfigurationError("VAULT_MASTER_KEY is required when VAULT_PROVIDER=file")
        return EncryptedFileVault(vault_path=Path(settings.data_dir) / "vault.json", master_key=settings.vault_master_key)
    raise ConfigurationError(f"Unsupported VAULT_PROVIDER: {settings.vault_provider}")

