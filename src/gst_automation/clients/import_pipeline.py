from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import ProgrammingError, OperationalError

from gst_automation.clients.excel_parser import ClientMasterParser
from gst_automation.clients.security import mask_password
from gst_automation.clients.service import ClientImportRow, ClientService, default_client_folder_root
from gst_automation.core.settings import Settings
from gst_automation.db.models.client import Client
from gst_automation.core.exceptions import ConfigurationError


def _group_row_errors(errors: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[int, list[str]] = {}
    for e in errors:
        row = int(e.get("row") or 0)
        msg = str(e.get("message") or "")
        field = str(e.get("field") or "")
        label = msg if field in {"", "header"} else f"{field}: {msg}"
        grouped.setdefault(row, []).append(label)
    out = [{"row": row, "errors": msgs} for row, msgs in sorted(grouped.items(), key=lambda kv: kv[0])]
    return out


@dataclass(frozen=True, slots=True)
class ImportPreviewRow:
    row: int
    client_id: str
    client_name: str
    gstin: str
    username: str
    client_email: str
    financial_year: str
    active: bool
    priority: str
    tags: str | None
    preferred_run_window: int
    notes: str | None
    would_create: bool
    would_update: bool


@dataclass(frozen=True, slots=True)
class ImportSummary:
    total_rows: int
    active_rows: int
    inactive_rows: int
    would_create: int
    would_update: int
    imported_at_iso: str


@dataclass(frozen=True, slots=True)
class ImportReport:
    ok: bool
    created: int
    updated: int
    row_errors: list[dict[str, object]]
    preview: list[dict[str, object]]
    summary: dict[str, object]


@dataclass(frozen=True, slots=True)
class ClientImportPipeline:
    settings: Settings

    async def validate_xlsx(self, *, path: Path) -> ImportReport:
        return await self.import_xlsx(None, path=path, dry_run=True)

    def _derive_client_uuid(self, *, row: dict[str, Any]) -> uuid.UUID:
        raw = str(row.get("client_id") or "").strip()
        if raw:
            try:
                return uuid.UUID(raw)
            except Exception:
                # Allow operator-facing IDs like "CLIENT001" while still producing a stable UUID.
                pass
        gstin = str(row.get("gstin") or "").strip().upper()
        if not gstin:
            return uuid.uuid4()
        ns = uuid.UUID("f1bb4cb7-e63a-4a4c-8d82-5c1cb0fd7c03")
        return uuid.uuid5(ns, f"gstin:{gstin}")

    async def import_xlsx(
        self,
        session: AsyncSession | None,
        *,
        path: Path,
        dry_run: bool = True,
        actor: str = "xlsx_import",
    ) -> ImportReport:
        parsed = ClientMasterParser(path=path).parse()
        errs = [{"row": e.row, "field": e.field, "message": e.message} for e in parsed.errors]
        if not parsed.ok:
            return ImportReport(
                ok=False,
                created=0,
                updated=0,
                row_errors=_group_row_errors(errs),
                preview=[],
                summary={
                    "total_rows": 0,
                    "active_rows": 0,
                    "inactive_rows": 0,
                    "would_create": 0,
                    "would_update": 0,
                    "imported_at_iso": datetime.utcnow().isoformat() + "Z",
                },
            )

        # Normalize and coerce rows; client_id is optional (auto-generated / derived from GSTIN if non-UUID).
        typed_rows: list[tuple[int, ClientImportRow]] = []
        preview_base: list[tuple[int, dict[str, Any]]] = []
        for r in parsed.rows:
            idx = int(r.get("__rownum") or 0) or 0
            client_id = self._derive_client_uuid(row=r)
            active = str(r.get("active") or "FALSE").upper() == "TRUE"
            preferred_run_window = int(str(r.get("preferred_run_window") or "18"))
            tags = str(r.get("tags") or "").strip() or None
            notes = str(r.get("notes") or "").strip() or None

            row = ClientImportRow(
                client_id=client_id,
                client_name=str(r.get("client_name") or "").strip(),
                gstin=str(r.get("gstin") or "").strip().upper(),
                username=str(r.get("username") or "").strip(),
                password=str(r.get("password") or ""),
                client_email=str(r.get("client_email") or "").strip(),
                financial_year=str(r.get("financial_year") or "").strip(),
                active=active,
                priority=str(r.get("priority") or "MEDIUM").strip().upper(),
                tags=tags,
                preferred_run_window=preferred_run_window,
                notes=notes,
                folder_root=default_client_folder_root(self.settings),
                retry_policy={"max_retry_count": 3, "backoff_seconds": 60},
                session_reuse_enabled=True,
            )
            typed_rows.append((idx, row))
            preview_base.append(
                (
                    idx,
                    {
                        "row": idx or None,
                        "client_id": str(client_id),
                        "client_name": row.client_name,
                        "gstin": row.gstin,
                        "username": row.username,
                        "password": mask_password(row.password),
                        "client_email": row.client_email,
                        "financial_year": row.financial_year,
                        "active": row.active,
                        "priority": row.priority,
                        "tags": row.tags,
                        "preferred_run_window": row.preferred_run_window,
                        "notes": row.notes,
                    },
                )
            )

        # Determine create/update in DB for preview.
        would_create = 0
        would_update = 0
        existing_by_gstin: set[str] = set()
        existing_by_id: set[uuid.UUID] = set()
        if session is not None:
            gstins = [r.gstin for _i, r in typed_rows if r.gstin]
            try:
                if gstins:
                    res = await session.execute(select(Client.gstin).where(Client.gstin.in_(gstins)))
                    existing_by_gstin = {str(v).upper() for v in res.scalars().all()}
                ids = [r.client_id for _i, r in typed_rows]
                if ids:
                    res2 = await session.execute(select(Client.id).where(Client.id.in_(ids)))
                    existing_by_id = set(res2.scalars().all())
            except (ProgrammingError, OperationalError) as exc:
                msg = str(exc).lower()
                if "relation" in msg and "does not exist" in msg and "clients" in msg:
                    raise ConfigurationError(
                        "Database schema is not initialized (missing table 'clients'). "
                        "Run: python -m gst_automation.cli.db upgrade"
                    ) from exc
                raise

        preview: list[dict[str, object]] = []
        for idx, base in preview_base:
            gstin_u = str(base.get("gstin") or "").upper()
            cid = uuid.UUID(str(base["client_id"]))
            is_existing = (gstin_u in existing_by_gstin) or (cid in existing_by_id)
            base["would_create"] = not is_existing
            base["would_update"] = is_existing
            preview.append(base)
            would_create += 0 if is_existing else 1
            would_update += 1 if is_existing else 0

        total_rows = len(typed_rows)
        active_rows = sum(1 for _i, r in typed_rows if r.active)
        inactive_rows = total_rows - active_rows

        summary = ImportSummary(
            total_rows=total_rows,
            active_rows=active_rows,
            inactive_rows=inactive_rows,
            would_create=would_create,
            would_update=would_update,
            imported_at_iso=datetime.utcnow().isoformat() + "Z",
        )

        if dry_run:
            return ImportReport(
                ok=True,
                created=0,
                updated=0,
                row_errors=[],
                preview=preview,
                summary=asdict(summary),
            )

        if session is None:
            raise RuntimeError("session is required for non-dry-run import")

        svc = ClientService(settings=self.settings, session=session)
        res = await svc.upsert_from_import([r for _i, r in typed_rows], actor=actor)
        return ImportReport(
            ok=True,
            created=int(res["created"]),
            updated=int(res["updated"]),
            row_errors=[],
            preview=[],
            summary=asdict(summary),
        )
