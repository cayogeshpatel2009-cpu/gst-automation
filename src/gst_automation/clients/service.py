from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.core.logging import get_logger
from gst_automation.core.settings import Settings
from gst_automation.db.models.client import Client
from gst_automation.db.models.clients.client_config import ClientConfig, ClientCredentialRef
from gst_automation.vault.base import SecretRef
from gst_automation.vault.factory import build_vault
from gst_automation.storage.folder_manager import FolderManager


logger = get_logger(__name__)

PRIORITY_MAP: dict[str, int] = {"HIGH": 2, "MEDIUM": 5, "LOW": 8}


@dataclass(frozen=True, slots=True)
class ClientImportRow:
    client_id: uuid.UUID
    client_name: str
    gstin: str
    username: str
    password: str
    client_email: str
    financial_year: str
    active: bool
    priority: str
    tags: str | None
    preferred_run_window: int
    notes: str | None
    folder_root: str
    retry_policy: dict[str, object]
    session_reuse_enabled: bool


@dataclass(frozen=True, slots=True)
class ClientService:
    settings: Settings
    session: AsyncSession

    async def upsert_from_import(self, rows: list[ClientImportRow], *, actor: str = "import") -> dict[str, int]:
        vault = build_vault(self.settings)
        created = 0
        updated = 0
        for r in rows:
            client = await self.session.get(Client, r.client_id)
            if client is None:
                client = Client(id=r.client_id, gstin=r.gstin.upper(), display_name=r.client_name, status="active" if r.active else "disabled")
                self.session.add(client)
                created += 1
            else:
                client.display_name = r.client_name
                client.gstin = r.gstin.upper()
                client.status = "active" if r.active else "disabled"
                updated += 1

            cfg = await self.session.get(ClientConfig, r.client_id)
            if cfg is None:
                cfg = ClientConfig(
                    client_id=r.client_id,
                    client_email=r.client_email,
                    cc_email=None,
                    active=1 if r.active else 0,
                    priority=int(PRIORITY_MAP.get(r.priority.upper(), 5)),
                    folder_root=r.folder_root,
                    retry_policy_json=json.dumps(r.retry_policy, sort_keys=True, separators=(",", ":")),
                    session_reuse_enabled=1 if r.session_reuse_enabled else 0,
                    financial_year=r.financial_year,
                    preferred_run_window=int(r.preferred_run_window),
                    tags=r.tags,
                    notes=r.notes,
                )
                self.session.add(cfg)
            else:
                cfg.client_email = r.client_email
                cfg.cc_email = None
                cfg.active = 1 if r.active else 0
                cfg.priority = int(PRIORITY_MAP.get(r.priority.upper(), 5))
                cfg.folder_root = r.folder_root
                cfg.retry_policy_json = json.dumps(r.retry_policy, sort_keys=True, separators=(",", ":"))
                cfg.session_reuse_enabled = 1 if r.session_reuse_enabled else 0
                cfg.financial_year = r.financial_year
                cfg.preferred_run_window = int(r.preferred_run_window)
                cfg.tags = r.tags
                cfg.notes = r.notes

            # Store password in Vault, reference in DB.
            ref = SecretRef(namespace="client", key=f"{r.client_id}:gst_password")
            await vault.set_secret(ref, r.password)
            cref = await self.session.get(ClientCredentialRef, r.client_id)
            if cref is None:
                cref = ClientCredentialRef(
                    client_id=r.client_id, gst_username=r.username, gst_password_secret_key=ref.to_id()
                )
                self.session.add(cref)
            else:
                cref.gst_username = r.username
                cref.gst_password_secret_key = ref.to_id()

            # Deterministic folder bootstrap for current period (idempotent, overwrite-safe).
            try:
                fm = FolderManager(folder_root=Path(r.folder_root))
                tz = ZoneInfo(self.settings.browser_timezone)
                now = datetime.now(tz)
                period = f"{now.year:04d}-{now.month:02d}"
                layout = fm.layout(client_name=r.client_name, gstin=r.gstin.upper(), fy=r.financial_year, period_yyyy_mm=period)
                fm.ensure(layout)
            except Exception:
                # Non-fatal: folder issues should be surfaced by readiness validator.
                pass

        logger.info("clients.imported", created=created, updated=updated, actor=actor)
        return {"created": created, "updated": updated}

    async def get_credentials(self, client_id: uuid.UUID) -> tuple[str, str]:
        vault = build_vault(self.settings)
        cref = await self.session.get(ClientCredentialRef, client_id)
        if cref is None:
            raise RuntimeError("missing client credentials")
        namespace, key = cref.gst_password_secret_key.split(":", 1)
        pw = await vault.get_secret(SecretRef(namespace=namespace, key=key))
        return cref.gst_username, pw


def default_client_folder_root(settings: Settings) -> str:
    # Single deterministic root for all clients; stored in DB for compatibility with existing execution code.
    return str(Path(settings.data_dir) / "clients")
