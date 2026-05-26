from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.db.models.client import Client
from gst_automation.db.models.clients.client_config import ClientConfig
from gst_automation.storage.folder_manager import FolderLayout, FolderManager


@dataclass(frozen=True, slots=True)
class FolderBootstrapResult:
    bootstrapped: int
    skipped: int
    errors: list[dict[str, object]]


@dataclass(frozen=True, slots=True)
class ClientFolderValidator:
    def validate_layout(self, layout: FolderLayout) -> list[str]:
        missing: list[str] = []
        for p in [
            layout.period_root,
            layout.gstr2b_dir,
            layout.logs_dir,
            layout.replay_dir,
            layout.screenshots_dir,
            layout.downloads_dir,
        ]:
            if not p.exists() or not p.is_dir():
                missing.append(str(p))
        return missing


@dataclass(frozen=True, slots=True)
class ClientFolderBootstrapper:
    """Creates deterministic client execution folders in an idempotent, duplicate-safe way."""

    session: AsyncSession

    async def bootstrap(self, *, period_yyyy_mm: str, only_active: bool = True) -> FolderBootstrapResult:
        res = await self.session.execute(select(Client))
        clients = list(res.scalars().all())
        cfg_res = await self.session.execute(select(ClientConfig))
        cfgs = {c.client_id: c for c in cfg_res.scalars().all()}

        bootstrapped = 0
        skipped = 0
        errors: list[dict[str, object]] = []
        validator = ClientFolderValidator()

        for c in clients:
            cfg = cfgs.get(c.id)
            if cfg is None:
                skipped += 1
                continue
            if only_active and (not bool(cfg.active) or c.status != "active"):
                skipped += 1
                continue

            try:
                fm = FolderManager(folder_root=Path(cfg.folder_root))
                layout = fm.layout(
                    client_name=c.display_name,
                    gstin=c.gstin,
                    fy=cfg.financial_year,
                    period_yyyy_mm=period_yyyy_mm,
                )
                fm.ensure(layout)
                missing = validator.validate_layout(layout)
                if missing:
                    errors.append(
                        {
                            "client_id": str(c.id),
                            "gstin": c.gstin,
                            "client_name": c.display_name,
                            "error": "folder_integrity_failed",
                            "missing": missing,
                        }
                    )
                else:
                    bootstrapped += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(
                    {
                        "client_id": str(c.id),
                        "gstin": c.gstin,
                        "client_name": c.display_name,
                        "error": "folder_bootstrap_failed",
                        "detail": str(exc),
                    }
                )

        return FolderBootstrapResult(bootstrapped=bootstrapped, skipped=skipped, errors=errors)


@dataclass(frozen=True, slots=True)
class OrphanFolderDetector:
    """Detects orphan folders under ROOT that do not map to any known client GSTIN."""

    session: AsyncSession

    async def find_orphans(self, *, folder_root: Path) -> list[dict[str, object]]:
        res = await self.session.execute(select(Client.gstin))
        known = {str(g).upper() for g in res.scalars().all()}

        if not folder_root.exists() or not folder_root.is_dir():
            return [{"error": "folder_root_missing", "folder_root": str(folder_root)}]

        orphans: list[dict[str, object]] = []
        for client_dir in folder_root.iterdir():
            if not client_dir.is_dir():
                continue
            for gstin_dir in client_dir.iterdir():
                if not gstin_dir.is_dir():
                    continue
                gstin = gstin_dir.name.strip().upper()
                # We store sanitized names on disk; GSTIN itself should remain exact and is a good anchor.
                if gstin and gstin not in known:
                    orphans.append({"client_dir": str(client_dir), "gstin_dir": str(gstin_dir), "gstin": gstin})
        return orphans


def expected_gstr2b_path(*, folder_root: Path, client_name: str, gstin: str, fy: str, period_yyyy_mm: str) -> Path:
    layout = FolderManager(folder_root=folder_root).layout(
        client_name=client_name, gstin=gstin, fy=fy, period_yyyy_mm=period_yyyy_mm
    )
    return layout.gstr2b_dir / f"GSTR2B_{gstin}_{period_yyyy_mm}.xlsx"


def validate_period_format(period_yyyy_mm: str) -> None:
    if len(period_yyyy_mm) != 7 or period_yyyy_mm[4] != "-":
        raise ValueError("period must be YYYY-MM")
    y, m = period_yyyy_mm.split("-", 1)
    if not (y.isdigit() and m.isdigit()):
        raise ValueError("period must be YYYY-MM")
    month = int(m)
    if month < 1 or month > 12:
        raise ValueError("period month must be 01..12")

