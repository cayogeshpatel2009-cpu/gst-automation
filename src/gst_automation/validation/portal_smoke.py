from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from playwright.async_api import Page
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.browser.artifacts import ArtifactManager
from gst_automation.browser.lease_guard import LeaseGuard
from gst_automation.core.logging import get_logger
from gst_automation.core.settings import Settings
from gst_automation.portal.dsl import PortalDsl
from gst_automation.portal.selectors.registry import SelectorRegistry
from gst_automation.portal.selectors.types import SelectorDefinition
from gst_automation.validation.chaos import ChaosInjector
from gst_automation.validation.dto import PortalSmokePayload
from gst_automation.validation.metrics import (
    PORTAL_SMOKE_ACTION_SECONDS,
    PORTAL_SMOKE_ACTIONS_TOTAL,
    PORTAL_SMOKE_RUNS_TOTAL,
)
from gst_automation.validation.recorder import WorkflowRecorder


logger = get_logger(__name__)


def _default_selectors() -> SelectorRegistry:
    # Deterministic selectors for the internal test portal only.
    from gst_automation.portal.selectors.types import SelectorCandidate

    defs: dict[tuple[str, int], SelectorDefinition] = {
        ("login.username", 1): SelectorDefinition(
            key="login.username",
            version=1,
            candidates=(SelectorCandidate(kind="css", value="[data-testid='login-username']", weight=100),),
        ),
        ("login.password", 1): SelectorDefinition(
            key="login.password",
            version=1,
            candidates=(SelectorCandidate(kind="css", value="[data-testid='login-password']", weight=100),),
        ),
        ("login.submit", 1): SelectorDefinition(
            key="login.submit",
            version=1,
            candidates=(SelectorCandidate(kind="css", value="[data-testid='login-submit']", weight=100),),
        ),
        ("otp.code", 1): SelectorDefinition(
            key="otp.code",
            version=1,
            candidates=(SelectorCandidate(kind="css", value="[data-testid='otp-code']", weight=100),),
        ),
        ("otp.submit", 1): SelectorDefinition(
            key="otp.submit",
            version=1,
            candidates=(SelectorCandidate(kind="css", value="[data-testid='otp-submit']", weight=100),),
        ),
        ("download.link", 1): SelectorDefinition(
            key="download.link",
            version=1,
            candidates=(SelectorCandidate(kind="css", value="[data-testid='download-link']", weight=100),),
        ),
        ("modal.open", 1): SelectorDefinition(
            key="modal.open",
            version=1,
            candidates=(SelectorCandidate(kind="css", value="[data-testid='modal-open']", weight=100),),
        ),
    }
    return SelectorRegistry(definitions=defs)


@dataclass(frozen=True, slots=True)
class PortalSmokeWorkflow:
    settings: Settings
    artifacts: ArtifactManager

    async def run(
        self,
        session: AsyncSession,
        *,
        job_id: uuid.UUID,
        context_id: uuid.UUID,
        lease_token: str,
        fencing_token: int,
        base_artifacts_dir: Path,
        page: Page,
        payload: PortalSmokePayload,
        recorder: WorkflowRecorder,
    ) -> None:
        guard = LeaseGuard(
            session=session, job_id=job_id, lease_token=lease_token, expected_fencing_token=fencing_token
        )
        chaos = ChaosInjector(payload.chaos)

        start_url = payload.base_url.rstrip("/") + payload.start_path

        recorder.record(
            {
                "ts_ms": recorder.now_ms(),
                "type": "workflow.start",
                "job_id": str(job_id),
                "context_id": str(context_id),
                "start_url": start_url,
                "chaos": payload.chaos.model_dump(),
            }
        )

        await guard.assert_valid()
        await page.goto(start_url)
        if payload.take_screenshots:
            await self._screenshot(session, job_id=job_id, context_id=context_id, base_dir=base_artifacts_dir, page=page, name="start", recorder=recorder)

        dsl = PortalDsl(
            settings=self.settings, artifacts=self.artifacts, selectors=_default_selectors()
        )

        for idx, action in enumerate(payload.actions):
            await chaos.maybe_inject(step_index=idx, page=page)
            await guard.assert_valid()

            t0 = time.monotonic()
            result = "ok"
            try:
                await self._run_action(
                    session,
                    job_id=job_id,
                    context_id=context_id,
                    page=page,
                    dsl=dsl,
                    lease_token=lease_token,
                    fencing_token=fencing_token,
                    base_artifacts_dir=base_artifacts_dir,
                    idx=idx,
                    action=action,
                    recorder=recorder,
                )
            except Exception as exc:  # noqa: BLE001
                result = "error"
                recorder.record(
                    {
                        "ts_ms": recorder.now_ms(),
                        "type": "action.error",
                        "index": idx,
                        "kind": action.kind,
                        "error": str(exc),
                    }
                )
                raise
            finally:
                dt = time.monotonic() - t0
                PORTAL_SMOKE_ACTIONS_TOTAL.labels(kind=action.kind, result=result).inc()
                PORTAL_SMOKE_ACTION_SECONDS.labels(kind=action.kind).observe(dt)

        recorder.record({"ts_ms": recorder.now_ms(), "type": "workflow.completed"})

    async def _run_action(
        self,
        session: AsyncSession,
        *,
        job_id: uuid.UUID,
        context_id: uuid.UUID,
        page: Page,
        dsl: PortalDsl,
        lease_token: str,
        fencing_token: int,
        base_artifacts_dir: Path,
        idx: int,
        action: object,
        recorder: WorkflowRecorder,
    ) -> None:
        # Typed as object to keep import surface small.
        action_dict = action.model_dump()
        recorder.record({"ts_ms": recorder.now_ms(), "type": "action.start", "index": idx, **action_dict})

        kind = action.kind
        if kind == "goto":
            assert action.text is not None
            url = action.text
            await page.goto(url)
        elif kind == "fill":
            assert action.selector is not None
            assert action.value is not None
            await page.fill(action.selector, action.value)
        elif kind == "click":
            if action.selector_key:
                await dsl.safe_click(
                    session,
                    job_id=job_id,
                    context_id=context_id,
                    page=page,
                    selector_key=action.selector_key,
                    selector_version=action.selector_version,
                )
            else:
                assert action.selector is not None
                await page.click(action.selector)
        elif kind == "expect_text":
            assert action.text is not None
            body = await page.inner_text("body")
            if action.text not in body:
                raise AssertionError(f"expected text not found: {action.text!r}")
        elif kind == "sleep_ms":
            assert action.value is not None
            await page.wait_for_timeout(int(action.value))
        elif kind == "screenshot":
            await self._screenshot(
                session,
                job_id=job_id,
                context_id=context_id,
                base_dir=base_artifacts_dir,
                page=page,
                name=action.name or f"step_{idx}",
                recorder=recorder,
            )
        elif kind == "download":
            assert action.selector_key is not None or action.selector is not None
            selector = action.selector or "[data-testid='download-link']"
            async with page.expect_download() as dl_info:
                await page.click(selector)
            dl = await dl_info.value
            dest_dir = base_artifacts_dir / "downloads"
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest_path = dest_dir / (dl.suggested_filename or f"download_{idx}")
            await dl.save_as(dest_path)
            await self.artifacts.record_file(
                session,
                job_id=job_id,
                context_id=context_id,
                kind="download",
                path=dest_path,
                relpath=str(dest_path.relative_to(Path(self.settings.browser_artifacts_dir))),
            )
            recorder.record(
                {
                    "ts_ms": recorder.now_ms(),
                    "type": "download.saved",
                    "index": idx,
                    "suggested_filename": dl.suggested_filename,
                    "relpath": str(dest_path.relative_to(Path(self.settings.browser_artifacts_dir))),
                }
            )
        else:
            raise ValueError(f"unknown portal_smoke action kind: {kind}")

        recorder.record({"ts_ms": recorder.now_ms(), "type": "action.done", "index": idx, "kind": kind})

    async def _screenshot(
        self,
        session: AsyncSession,
        *,
        job_id: uuid.UUID,
        context_id: uuid.UUID,
        base_dir: Path,
        page: Page,
        name: str,
        recorder: WorkflowRecorder,
    ) -> None:
        path = base_dir / "screenshots" / f"{name}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(path), full_page=True)
        await self.artifacts.record_file(
            session,
            job_id=job_id,
            context_id=context_id,
            kind="screenshot",
            path=path,
            relpath=str(path.relative_to(Path(self.settings.browser_artifacts_dir))),
        )
        relpath = str(path.relative_to(Path(self.settings.browser_artifacts_dir)))
        recorder.record(
            {"ts_ms": recorder.now_ms(), "type": "artifact.screenshot", "name": name, "relpath": relpath}
        )


async def run_portal_smoke(
    session: AsyncSession,
    *,
    job_id: uuid.UUID,
    context_id: uuid.UUID,
    lease_token: str,
    fencing_token: int,
    artifacts_dir: Path,
    page: Page,
    payload_json: str,
    settings: Settings,
) -> None:
    payload = PortalSmokePayload.model_validate(json.loads(payload_json))

    recorder = WorkflowRecorder(path=artifacts_dir / "replay.jsonl")
    artifacts = ArtifactManager(artifacts_root=Path(settings.browser_artifacts_dir))
    wf = PortalSmokeWorkflow(settings=settings, artifacts=artifacts)

    logger.info(
        "portal_smoke.start",
        job_id=str(job_id),
        context_id=str(context_id),
        base_url=payload.base_url,
        start_path=payload.start_path,
    )
    try:
        await wf.run(
            session,
            job_id=job_id,
            context_id=context_id,
            lease_token=lease_token,
            fencing_token=fencing_token,
            base_artifacts_dir=artifacts_dir,
            page=page,
            payload=payload,
            recorder=recorder,
        )
        PORTAL_SMOKE_RUNS_TOTAL.labels(result="ok").inc()
        logger.info("portal_smoke.completed", job_id=str(job_id), context_id=str(context_id))
    except Exception as exc:  # noqa: BLE001
        PORTAL_SMOKE_RUNS_TOTAL.labels(result="error").inc()
        logger.exception("portal_smoke.failed", job_id=str(job_id), context_id=str(context_id), err=str(exc))
        raise
