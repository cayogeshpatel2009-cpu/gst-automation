from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.archive.hashing import sha256_file
from gst_automation.browser.metrics import ARTIFACTS_TOTAL
from gst_automation.db.models.browser.browser_artifact import BrowserArtifact


@dataclass(frozen=True, slots=True)
class ArtifactManager:
    """Persist artifacts on disk and index them in DB."""

    artifacts_root: Path

    def context_root(self, *, job_id: uuid.UUID, context_id: uuid.UUID) -> Path:
        return self.artifacts_root / str(job_id) / str(context_id)

    async def record_file(
        self,
        session: AsyncSession,
        *,
        job_id: uuid.UUID,
        context_id: uuid.UUID,
        kind: str,
        path: Path,
        relpath: str,
    ) -> None:
        sha = sha256_file(path)
        size = path.stat().st_size
        row = BrowserArtifact(
            job_id=job_id,
            context_id=context_id,
            kind=kind,
            relpath=relpath,
            sha256_hex=sha,
            byte_size=size,
        )
        session.add(row)
        await session.flush()
        ARTIFACTS_TOTAL.labels(kind=kind).inc()

