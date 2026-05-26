from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.core.logging import get_logger
from gst_automation.core.settings import Settings
from gst_automation.db.models.browser.browser_artifact import BrowserArtifact
from gst_automation.db.models.browser.browser_context import BrowserContextRecord
from gst_automation.db.models.validation.health_and_leaks import ReplayIntegrityAudit


logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ReplayIntegrityResult:
    status: str
    issues: dict[str, object]


@dataclass(frozen=True, slots=True)
class ReplayIntegrityValidator:
    settings: Settings

    async def validate_job(self, session: AsyncSession, *, job_id: uuid.UUID, limit_contexts: int = 5) -> list[ReplayIntegrityResult]:
        res = await session.execute(
            select(BrowserContextRecord)
            .where(BrowserContextRecord.job_id == job_id)
            .order_by(BrowserContextRecord.created_at.desc())
            .limit(limit_contexts)
        )
        contexts = list(res.scalars().all())
        out: list[ReplayIntegrityResult] = []
        for c in contexts:
            out.append(await self.validate_context(session, job_id=job_id, context_id=c.id))
        return out

    async def validate_context(self, session: AsyncSession, *, job_id: uuid.UUID, context_id: uuid.UUID) -> ReplayIntegrityResult:
        artifacts_root = Path(self.settings.browser_artifacts_dir)
        replay_path = artifacts_root / str(job_id) / str(context_id) / "replay.jsonl"
        issues: dict[str, object] = {}

        if not replay_path.exists():
            issues["missing_replay"] = True
            return await self._record(session, job_id=job_id, context_id=context_id, status="violation", issues=issues)

        lines = replay_path.read_text(encoding="utf-8").splitlines()
        if not lines:
            issues["empty_replay"] = True
            return await self._record(session, job_id=job_id, context_id=context_id, status="violation", issues=issues)

        seen_start = False
        seen_done = False
        last_ts = -1
        parse_errors = 0
        types: list[str] = []
        for i, line in enumerate(lines[:5000]):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
                ts = int(obj.get("ts_ms", 0))
                typ = str(obj.get("type", ""))
                types.append(typ)
                if typ == "workflow.start":
                    seen_start = True
                if typ == "workflow.completed":
                    seen_done = True
                if ts < last_ts:
                    issues.setdefault("non_monotonic_ts", []).append({"line": i, "ts": ts, "prev": last_ts})
                last_ts = ts
            except Exception:
                parse_errors += 1
        if parse_errors:
            issues["parse_errors"] = parse_errors
        if not seen_start:
            issues["missing_workflow_start"] = True
        if not seen_done:
            issues["missing_workflow_completed"] = True

        # Artifact correlation: screenshots referenced should exist in DB index.
        missing_artifacts: list[str] = []
        referenced = []
        for line in lines:
            if '"artifact.screenshot"' in line and '"relpath"' in line:
                try:
                    obj = json.loads(line)
                    rel = obj.get("relpath")
                    if isinstance(rel, str):
                        referenced.append(rel)
                except Exception:
                    continue
        if referenced:
            res = await session.execute(
                select(BrowserArtifact.relpath).where(BrowserArtifact.relpath.in_(referenced))
            )
            indexed = {r[0] for r in res.all()}
            for rel in referenced:
                if rel not in indexed:
                    missing_artifacts.append(rel)
        if missing_artifacts:
            issues["missing_indexed_artifacts"] = missing_artifacts[:50]

        status = "ok"
        if issues:
            status = "violation"

        return await self._record(session, job_id=job_id, context_id=context_id, status=status, issues=issues)

    async def _record(
        self,
        session: AsyncSession,
        *,
        job_id: uuid.UUID,
        context_id: uuid.UUID,
        status: str,
        issues: dict[str, object],
    ) -> ReplayIntegrityResult:
        row = ReplayIntegrityAudit(
            job_id=job_id,
            context_id=context_id,
            status=status,
            issues_json=json.dumps(issues, sort_keys=True, separators=(",", ":")),
            created_at=datetime.now(UTC),
        )
        session.add(row)
        await session.flush()
        logger.info("replay.integrity", job_id=str(job_id), context_id=str(context_id), status=status)
        return ReplayIntegrityResult(status=status, issues=issues)

