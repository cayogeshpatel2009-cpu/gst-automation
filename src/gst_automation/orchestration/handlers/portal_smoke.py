from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from playwright.async_api import Page

from gst_automation.browser.artifacts import ArtifactManager
from gst_automation.core.logging import get_logger
from gst_automation.orchestration.handlers.base import JobHandlerV2
from gst_automation.orchestration.handlers.context import JobRunContext
from gst_automation.validation.portal_smoke import run_portal_smoke


logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class PortalSmokeJobHandler(JobHandlerV2):
    """Portal execution validation job handler (no GST workflows)."""

    async def run_with_context(
        self, *, job_id: uuid.UUID, payload_json: str, ctx: JobRunContext
    ) -> None:
        bs = ctx.browser_session
        page: Page = await bs.context.new_page()

        # Console capture is always-on for now; per-job toggles can be added in a later iteration.
        console_path = bs.artifacts_dir / "console.log"
        console_path.parent.mkdir(parents=True, exist_ok=True)

        def _write(line: str) -> None:
            with console_path.open("a", encoding="utf-8") as f:
                f.write(line)
                f.write("\n")

        page.on("console", lambda msg: _write(f"[{msg.type}] {msg.text}"))
        page.on("pageerror", lambda exc: _write(f"[pageerror] {exc}"))

        await run_portal_smoke(
            ctx.session,
            job_id=job_id,
            context_id=bs.context_id,
            lease_token=ctx.lease_token,
            fencing_token=ctx.fencing_token,
            artifacts_dir=Path(bs.artifacts_dir),
            page=page,
            payload_json=payload_json,
            settings=ctx.settings,
        )

        # Index workflow artifacts (best-effort).
        try:
            artifacts = ArtifactManager(artifacts_root=Path(ctx.settings.browser_artifacts_dir))
            if console_path.exists():
                await artifacts.record_file(
                    ctx.session,
                    job_id=job_id,
                    context_id=bs.context_id,
                    kind="console",
                    path=console_path,
                    relpath=str(console_path.relative_to(Path(ctx.settings.browser_artifacts_dir))),
                )
            replay_path = Path(bs.artifacts_dir) / "replay.jsonl"
            if replay_path.exists():
                await artifacts.record_file(
                    ctx.session,
                    job_id=job_id,
                    context_id=bs.context_id,
                    kind="replay",
                    path=replay_path,
                    relpath=str(replay_path.relative_to(Path(ctx.settings.browser_artifacts_dir))),
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("portal_smoke.console_index_failed", job_id=str(job_id), err=str(exc))
