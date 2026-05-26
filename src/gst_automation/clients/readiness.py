from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.clients.excel_parser import EMAIL_RE, FINANCIAL_YEARS
from gst_automation.clients.folders import ClientFolderValidator
from gst_automation.core.settings import Settings
from gst_automation.db.models.client import Client
from gst_automation.db.models.clients.client_config import ClientConfig, ClientCredentialRef
from gst_automation.db.models.portal.selector_def import PortalSelectorDef
from gst_automation.db.models.portal.session_blob import PortalSessionBlob
from gst_automation.storage.folder_manager import FolderManager
from gst_automation.vault.base import SecretRef
from gst_automation.vault.factory import build_vault


REQUIRED_SELECTOR_KEYS = [
    "gst.nav.returns",
    "gst.nav.gstr2b",
    "gst.gstr2b.fy_dropdown",
    "gst.gstr2b.period_dropdown",
    "gst.gstr2b.generate",
    "gst.gstr2b.download_excel",
]


def current_period_yyyy_mm(settings: Settings) -> str:
    tz = ZoneInfo(settings.browser_timezone)
    now = datetime.now(tz)
    return f"{now.year:04d}-{now.month:02d}"


@dataclass(frozen=True, slots=True)
class ClientReadinessRow:
    client_id: str
    client_name: str
    gstin: str
    active: bool
    financial_year: str | None
    preferred_run_window: int | None
    onboarding_ok: bool
    execution_ready: bool
    blockers: list[str]
    missing_sessions: bool
    missing_selectors: list[str]


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    period_yyyy_mm: str
    total_clients: int
    active_clients: int
    ready_clients: int
    rows: list[ClientReadinessRow]

    def to_dict(self) -> dict[str, object]:
        return {
            "period_yyyy_mm": self.period_yyyy_mm,
            "total_clients": self.total_clients,
            "active_clients": self.active_clients,
            "ready_clients": self.ready_clients,
            "rows": [
                {
                    "client_id": r.client_id,
                    "client_name": r.client_name,
                    "gstin": r.gstin,
                    "active": r.active,
                    "financial_year": r.financial_year,
                    "preferred_run_window": r.preferred_run_window,
                    "onboarding_ok": r.onboarding_ok,
                    "execution_ready": r.execution_ready,
                    "blockers": r.blockers,
                    "missing_sessions": r.missing_sessions,
                    "missing_selectors": r.missing_selectors,
                }
                for r in self.rows
            ],
        }


async def _active_selector_keys(session: AsyncSession) -> set[str]:
    res = await session.execute(select(PortalSelectorDef.key).where(PortalSelectorDef.active == 1))
    return {str(k) for k in res.scalars().all()}


async def build_readiness_report(
    session: AsyncSession,
    *,
    settings: Settings,
    period_yyyy_mm: str | None = None,
) -> ReadinessReport:
    period = period_yyyy_mm or current_period_yyyy_mm(settings)

    res = await session.execute(select(Client))
    clients = list(res.scalars().all())
    cfg_res = await session.execute(select(ClientConfig))
    cfgs = {c.client_id: c for c in cfg_res.scalars().all()}
    cred_res = await session.execute(select(ClientCredentialRef))
    creds = {c.client_id: c for c in cred_res.scalars().all()}

    active_keys = await _active_selector_keys(session)
    vault = build_vault(settings)
    folder_validator = ClientFolderValidator()

    rows: list[ClientReadinessRow] = []
    ready_clients = 0
    active_clients = 0

    for c in clients:
        cfg = cfgs.get(c.id)
        cred = creds.get(c.id)
        active = bool(cfg.active) if cfg else False
        if c.status != "active":
            active = False

        if active:
            active_clients += 1

        blockers: list[str] = []

        # Basic onboarding checks.
        if cfg is None:
            blockers.append("missing client_config")
        if cred is None:
            blockers.append("missing credentials reference")
        if cfg is not None:
            # Email
            parts = [p.strip() for p in (cfg.client_email or "").split(",") if p.strip()]
            if not parts or any(not EMAIL_RE.match(p) for p in parts):
                blockers.append("invalid client_email")
            # Platform SMTP is optional; if client emails exist but SMTP is not configured, delivery will fail.
            if parts and (not settings.smtp_host or not settings.smtp_from):
                blockers.append("smtp not configured (email delivery disabled)")
            # FY
            if cfg.financial_year not in FINANCIAL_YEARS:
                blockers.append("invalid financial_year")
            # Run window
            if cfg.preferred_run_window not in {15, 16, 17, 18, 19, 20}:
                blockers.append("invalid preferred_run_window")

        # Vault secret existence (no secret value emitted).
        if cred is not None:
            try:
                namespace, key = cred.gst_password_secret_key.split(":", 1)
                _ = await vault.get_secret(SecretRef(namespace=namespace, key=key))
            except Exception:
                blockers.append("missing password in vault")

        onboarding_ok = len(blockers) == 0

        # Session existence (GST profile)
        sess_missing = True
        if cfg is not None and cred is not None:
            sess = await session.execute(
                select(PortalSessionBlob)
                .where(PortalSessionBlob.client_id == c.id)
                .where(PortalSessionBlob.profile == "gst")
                .order_by(desc(PortalSessionBlob.created_at))
                .limit(1)
            )
            blob = sess.scalars().first()
            if blob is not None and (blob.expires_at is None or blob.expires_at > datetime.now(UTC)):
                sess_missing = False

        # Selector readiness
        missing_selectors: list[str] = [k for k in REQUIRED_SELECTOR_KEYS if k not in active_keys]
        if cfg is not None:
            fy_key = f"gst.gstr2b.fy_option.{cfg.financial_year}"
            if fy_key not in active_keys:
                missing_selectors.append(fy_key)
            # Period option is required for deterministic navigation.
            period_key = f"gst.gstr2b.period_option.{period}"
            if period_key not in active_keys:
                missing_selectors.append(period_key)

        # Folder readiness
        if cfg is not None:
            try:
                layout = FolderManager(folder_root=Path(cfg.folder_root)).layout(
                    client_name=c.display_name,
                    gstin=c.gstin,
                    fy=cfg.financial_year,
                    period_yyyy_mm=period,
                )
                missing_paths = folder_validator.validate_layout(layout)
                if missing_paths:
                    blockers.append("missing client folders")
            except Exception:
                blockers.append("client folder layout error")

        if sess_missing and active:
            blockers.append("missing gst session")
        if missing_selectors:
            blockers.append("missing required selectors")

        execution_ready = active and (len(blockers) == 0)
        if execution_ready:
            ready_clients += 1

        rows.append(
            ClientReadinessRow(
                client_id=str(c.id),
                client_name=c.display_name,
                gstin=c.gstin,
                active=active,
                financial_year=cfg.financial_year if cfg else None,
                preferred_run_window=int(cfg.preferred_run_window) if cfg else None,
                onboarding_ok=onboarding_ok,
                execution_ready=execution_ready,
                blockers=blockers,
                missing_sessions=sess_missing,
                missing_selectors=sorted(set(missing_selectors)),
            )
        )

    return ReadinessReport(
        period_yyyy_mm=period,
        total_clients=len(clients),
        active_clients=active_clients,
        ready_clients=ready_clients,
        rows=rows,
    )
