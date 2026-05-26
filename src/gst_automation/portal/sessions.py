from __future__ import annotations

import base64
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.core.exceptions import ConfigurationError
from gst_automation.core.settings import Settings
from gst_automation.db.models.portal.session_blob import PortalSessionBlob
from gst_automation.portal.errors import SessionCorrupt


@dataclass(frozen=True, slots=True)
class SessionManager:
    """Encrypted session store for Playwright storage_state JSON."""

    settings: Settings

    def _fernet(self) -> Fernet:
        key = self.settings.vault_master_key
        if not key:
            raise ConfigurationError("VAULT_MASTER_KEY is required for encrypted portal sessions")
        return Fernet(key.encode("utf-8"))

    async def save_storage_state(
        self,
        session: AsyncSession,
        *,
        client_id: uuid.UUID | None,
        profile: str,
        storage_state: dict[str, Any],
        ttl_days: int = 7,
    ) -> None:
        payload = json.dumps(storage_state, sort_keys=True, separators=(",", ":")).encode("utf-8")
        token = self._fernet().encrypt(payload).decode("utf-8")
        row = PortalSessionBlob(
            client_id=client_id,
            profile=profile,
            encrypted_blob=token,
            key_id="default",
            version=1,
            created_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(days=ttl_days),
        )
        session.add(row)
        await session.flush()

    async def load_latest_storage_state(
        self,
        session: AsyncSession,
        *,
        client_id: uuid.UUID | None,
        profile: str,
    ) -> dict[str, Any] | None:
        stmt = (
            select(PortalSessionBlob)
            .where(PortalSessionBlob.client_id == client_id)
            .where(PortalSessionBlob.profile == profile)
            .order_by(PortalSessionBlob.created_at.desc())
            .limit(1)
        )
        res = await session.execute(stmt)
        row = res.scalar_one_or_none()
        if row is None:
            return None
        try:
            data = self._fernet().decrypt(row.encrypted_blob.encode("utf-8"))
            return json.loads(data.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise SessionCorrupt("session decrypt/parse failed") from exc

