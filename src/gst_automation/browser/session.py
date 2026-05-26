from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from playwright.async_api import BrowserContext, Page
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.browser.metrics import CONTEXT_ACTIVE, CONTEXT_ALLOC_TOTAL
from gst_automation.browser.artifacts import ArtifactManager
from gst_automation.browser.pool import BrowserPool, _LiveBrowser
from gst_automation.browser.sandbox import DownloadSandbox
from gst_automation.core.logging import get_logger
from gst_automation.core.settings import Settings
from gst_automation.db.models.browser.browser_context import BrowserContextRecord


logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class BrowserSession:
    """Lease-bound isolated browser context for one job execution."""

    browser_id: uuid.UUID
    context_id: uuid.UUID
    context: BrowserContext
    workspace_dir: Path
    downloads_dir: Path
    artifacts_dir: Path


class ContextIsolationEngine:
    """Allocates isolated workspaces + Playwright contexts per job."""

    def __init__(self, settings: Settings, pool: BrowserPool) -> None:
        self._settings = settings
        self._pool = pool
        self._sandbox = DownloadSandbox(root=Path(settings.work_dir) / "browser", download_timeout_seconds=settings.browser_download_timeout_seconds)
        self._artifacts = ArtifactManager(artifacts_root=Path(settings.browser_artifacts_dir))

    async def allocate(
        self,
        session: AsyncSession,
        *,
        job_id: uuid.UUID,
        worker_name: str,
        worker_generation: int,
        lease_token: str,
        fencing_token: int,
        storage_state: dict | None = None,
    ) -> BrowserSession:
        live = await self._pool.acquire_browser(session, worker_name=worker_name)
        workspace_dir, downloads_dir = self._sandbox.allocate()
        artifacts_dir = Path(self._settings.browser_artifacts_dir) / str(job_id)
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        try:
            context_id = uuid.uuid4()
            har_path = artifacts_dir / str(context_id) / "network.har"
            har_path.parent.mkdir(parents=True, exist_ok=True)
            session_storage: dict[str, dict[str, str]] | None = None
            pw_storage_state = storage_state
            if isinstance(storage_state, dict) and "__sessionStorage" in storage_state:
                try:
                    session_storage = storage_state.get("__sessionStorage")  # type: ignore[assignment]
                except Exception:
                    session_storage = None
                # Playwright expects only cookies/origins in storage_state; strip any custom keys.
                pw_storage_state = {
                    "cookies": storage_state.get("cookies", []),
                    "origins": storage_state.get("origins", []),
                }
            try:
                ctx = await self._pool.new_context(
                    live=live, record_har_path=str(har_path), storage_state=pw_storage_state
                )
            except AttributeError as exc:
                # Playwright browser can become disconnected in long-running workers; restart pool and retry once.
                msg = str(exc)
                if "has no attribute 'send'" in msg or "Browser.new_context" in msg:
                    logger.warning("context.new_context_retry", job_id=str(job_id), err=msg)
                    await self._pool.restart(reason="new_context_failed")
                    live = await self._pool.acquire_browser(session, worker_name=worker_name)
                    ctx = await self._pool.new_context(
                        live=live, record_har_path=str(har_path), storage_state=pw_storage_state
                    )
                else:
                    raise
            if session_storage:
                # Restore sessionStorage deterministically for origins where GST stores auth tokens.
                # This is best-effort and does not bypass OTP/CAPTCHA; it only rehydrates client-side state.
                payload = json.dumps(session_storage, sort_keys=True, separators=(",", ":"))
                await ctx.add_init_script(
                    f"""
(() => {{
  try {{
    const data = {payload};
    const o = data[location.origin];
    if (!o) return;
    for (const [k, v] of Object.entries(o)) {{
      try {{ sessionStorage.setItem(k, String(v)); }} catch (_) {{}}
    }}
  }} catch (_) {{}}
}})();
"""
                )
            # Start tracing immediately to ensure full visibility on failures.
            trace_path = artifacts_dir / str(context_id) / "trace.zip"
            trace_path.parent.mkdir(parents=True, exist_ok=True)
            await ctx.tracing.start(screenshots=True, snapshots=True, sources=False)
            rec = BrowserContextRecord(
                id=context_id,
                browser_id=live.id,
                job_id=job_id,
                lease_token=lease_token,
                fencing_token=fencing_token,
                worker_name=worker_name,
                worker_generation=worker_generation,
                state="active",
                workspace_dir=str(workspace_dir),
                downloads_dir=str(downloads_dir),
                artifacts_dir=str(artifacts_dir / str(context_id)),
                created_at=datetime.now(UTC),
            )
            session.add(rec)
            await session.flush()
            CONTEXT_ACTIVE.inc()
            CONTEXT_ALLOC_TOTAL.labels(result="ok").inc()
            return BrowserSession(
                browser_id=live.id,
                context_id=context_id,
                context=ctx,
                workspace_dir=workspace_dir,
                downloads_dir=downloads_dir,
                artifacts_dir=artifacts_dir / str(context_id),
            )
        except Exception as exc:  # noqa: BLE001
            CONTEXT_ALLOC_TOTAL.labels(result="error").inc()
            self._sandbox.cleanup(workspace_dir)
            logger.exception("context.allocate_failed", job_id=str(job_id), err=str(exc))
            raise

    async def close(self, session: AsyncSession, bs: BrowserSession) -> None:
        try:
            # Stop tracing and persist an artifact record.
            trace_path = bs.artifacts_dir / "trace.zip"
            trace_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                await bs.context.tracing.stop(path=str(trace_path))
                await self._artifacts.record_file(
                    session,
                    job_id=uuid.UUID(bs.artifacts_dir.parent.name),
                    context_id=bs.context_id,
                    kind="trace",
                    path=trace_path,
                    relpath=str(trace_path.relative_to(Path(self._settings.browser_artifacts_dir))),
                )
            except Exception:
                pass
            # HAR is flushed on context close when record_har_path is used.
            await bs.context.close()
            try:
                har_path = bs.artifacts_dir / "network.har"
                if har_path.exists():
                    await self._artifacts.record_file(
                        session,
                        job_id=uuid.UUID(bs.artifacts_dir.parent.name),
                        context_id=bs.context_id,
                        kind="har",
                        path=har_path,
                        relpath=str(har_path.relative_to(Path(self._settings.browser_artifacts_dir))),
                    )
            except Exception:
                pass
            try:
                await session.execute(
                    BrowserContextRecord.__table__.update()
                    .where(BrowserContextRecord.id == bs.context_id)
                    .values(state="closed", closed_at=datetime.now(UTC))
                )
            except Exception:
                pass
        finally:
            CONTEXT_ACTIVE.dec()
            self._sandbox.cleanup(bs.workspace_dir)
            # DB record closed is handled by watchdog cleanup in later iteration (or can be extended).
