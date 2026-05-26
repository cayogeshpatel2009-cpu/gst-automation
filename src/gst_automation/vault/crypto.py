from __future__ import annotations

from cryptography.fernet import Fernet


def build_fernet(master_key: str) -> Fernet:
    """Create a Fernet instance from a urlsafe base64-encoded 32-byte key."""
    return Fernet(master_key.encode("utf-8"))

