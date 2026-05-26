from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.core.logging import get_logger
from gst_automation.core.settings import Settings
from gst_automation.db.models.browser.browser_artifact import BrowserArtifact
from gst_automation.db.models.validation.retention import RetentionAction, RetentionPolicy
from gst_automation.watchdog.anomaly import AnomalyRecord, AnomalyService


logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RetentionEnforceResult:
    deleted: int
    kept: int
    errors: int


@dataclass(frozen=True, slots=True)
class RetentionService:
    settings: Settings

    async def ensure_defaults(self, session: AsyncSession) -> None:
        defaults = {
            "trace": 14,
            "har": 14,
            "screenshot": 14,
            "download": 7,
            "console": 7,
            "replay": 14,
        }
        for kind, ttl in defaults.items():
            existing = await session.get(RetentionPolicy, kind)
            if existing is None:
                session.add(RetentionPolicy(kind=kind, ttl_days=ttl, enabled=1, preserve=0))
        await session.flush()

    async def enforce(self, session: AsyncSession, *, dry_run: bool = True, limit: int = 500) -> RetentionEnforceResult:
        await self.ensure_defaults(session)
        now = datetime.now(UTC)

        policies = (await session.execute(select(RetentionPolicy))).scalars().all()
        policy_by_kind = {p.kind: p for p in policies}

        deleted = 0
        kept = 0
        errors = 0

        # Enforce by querying DB artifacts (authoritative index).
        for kind, pol in policy_by_kind.items():
            if not pol.enabled or pol.preserve:
                continue
            cutoff = now - timedelta(days=int(pol.ttl_days))
            res = await session.execute(
                select(BrowserArtifact)
                .where(BrowserArtifact.kind == kind)
                .where(BrowserArtifact.created_at < cutoff)
                .order_by(BrowserArtifact.created_at.asc())
                .limit(limit)
            )
            rows = list(res.scalars().all())
            for r in rows:
                root = Path(self.settings.browser_artifacts_dir).resolve()
                target = (root / r.relpath).resolve()
                if root not in target.parents and target != root:
                    errors += 1
                    session.add(
                        RetentionAction(
                            policy_kind=kind,
                            relpath=r.relpath,
                            action="error",
                            reason="path_escape",
                            details_json=json.dumps({"target": str(target)}, sort_keys=True, separators=(",", ":")),
                        )
                    )
                    continue

                if dry_run:
                    kept += 1
                    session.add(
                        RetentionAction(
                            policy_kind=kind,
                            relpath=r.relpath,
                            action="keep",
                            reason="dry_run",
                            details_json="{}",
                        )
                    )
                    continue

                try:
                    if target.exists():
                        target.unlink()
                    await session.execute(BrowserArtifact.__table__.delete().where(BrowserArtifact.id == r.id))
                    deleted += 1
                    session.add(
                        RetentionAction(
                            policy_kind=kind,
                            relpath=r.relpath,
                            action="delete",
                            reason="ttl_expired",
                            details_json=json.dumps(
                                {"created_at": r.created_at.isoformat()}, sort_keys=True, separators=(",", ":")
                            ),
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    errors += 1
                    session.add(
                        RetentionAction(
                            policy_kind=kind,
                            relpath=r.relpath,
                            action="error",
                            reason="delete_failed",
                            details_json=json.dumps({"err": str(exc)}, sort_keys=True, separators=(",", ":")),
                        )
                    )

        if errors:
            await AnomalyService(session).record(
                AnomalyRecord(
                    anomaly_type="retention_errors",
                    severity="WARNING",
                    score=50,
                    message="retention enforcement had errors",
                    details={"errors": errors},
                )
            )

        logger.info("retention.enforced", dry_run=dry_run, deleted=deleted, kept=kept, errors=errors)
        return RetentionEnforceResult(deleted=deleted, kept=kept, errors=errors)

