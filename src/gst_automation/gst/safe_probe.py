from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
import hashlib
from pathlib import Path

from playwright.async_api import Page
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.browser.artifacts import ArtifactManager
from gst_automation.core.logging import get_logger
from gst_automation.core.settings import Settings
from gst_automation.gst.auth_detection import GstAuthDetector
from gst_automation.gst.dto import GstSafeProbePayload
from gst_automation.gst.profiling import GstPortalProfiler
from gst_automation.gst.safe_policy import GstSafePolicy
from gst_automation.gst.selectors_discovery import SelectorCandidateSet, SelectorDiscoveryEngine
from gst_automation.db.models.gst.dom_snapshot import GstDomSnapshot
from gst_automation.db.models.gst.session_health import GstSessionHealth


logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class GstSafeProbeWorkflow:
    settings: Settings
    artifacts: ArtifactManager
    policy: GstSafePolicy

    async def run(
        self,
        session: AsyncSession,
        *,
        job_id: uuid.UUID,
        context_id: uuid.UUID,
        page: Page,
        artifacts_dir: Path,
        payload_json: str,
    ) -> None:
        payload = GstSafeProbePayload.model_validate(json.loads(payload_json))
        self.policy.assert_url_allowed(payload.start_url)

        # Hard guardrails: never allow downloads during GST probe.
        page.on("download", lambda d: logger.warning("gst_safe_probe.download_blocked", url=d.url))

        await page.goto(payload.start_url, wait_until="domcontentloaded")
        await self._screenshot(session, job_id=job_id, context_id=context_id, page=page, artifacts_dir=artifacts_dir, name="start")

        profiler = GstPortalProfiler(settings=self.settings, artifacts=self.artifacts)
        detector = GstAuthDetector()

        # Baseline profile snapshot.
        await profiler.snapshot(session, job_id=job_id, context_id=context_id, page=page, name="start", artifacts_dir=artifacts_dir)
        auth = await detector.detect(page)
        await self._write_json_artifact(
            session,
            job_id=job_id,
            context_id=context_id,
            artifacts_dir=artifacts_dir,
            kind="gst_auth_state",
            filename="auth_state.json",
            payload={"state": auth.state, "details": auth.details},
        )
        session.add(
            GstSessionHealth(
                job_id=job_id,
                context_id=context_id,
                state=auth.state,
                score=100 if auth.state in {"unknown", "login"} else 50,
                details_json=json.dumps(auth.details, sort_keys=True, separators=(",", ":")),
            )
        )

        if payload.capture_dom:
            html = await page.content()
            path = artifacts_dir / "gst_dom" / "page.html"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(html, encoding="utf-8")
            await self.artifacts.record_file(
                session,
                job_id=job_id,
                context_id=context_id,
                kind="gst_dom",
                path=path,
                relpath=str(path.relative_to(Path(self.settings.browser_artifacts_dir))),
            )
            dom_fp = hashlib.sha256(html[:200_000].encode("utf-8")).hexdigest()
            session.add(
                GstDomSnapshot(
                    job_id=job_id,
                    context_id=context_id,
                    url=page.url,
                    dom_fingerprint_sha256=dom_fp,
                    artifact_relpath=str(path.relative_to(Path(self.settings.browser_artifacts_dir))),
                )
            )

        if payload.selector_discovery:
            candidates = await self._discover_selectors(page)
            ids = await SelectorDiscoveryEngine().store_snapshot(session, candidates=candidates, prefix="gst")
            await self._write_json_artifact(
                session,
                job_id=job_id,
                context_id=context_id,
                artifacts_dir=artifacts_dir,
                kind="gst_selector_snapshot",
                filename="selector_snapshot.json",
                payload={"count": len(ids), "selector_def_ids": [str(x) for x in ids]},
            )

        # Execute optional read-only steps.
        for i, step in enumerate(payload.steps):
            self.policy.assert_read_only_action(step.kind)
            if step.kind == "goto":
                assert step.url is not None
                self.policy.assert_url_allowed(step.url)
                await page.goto(step.url, wait_until="domcontentloaded")
                await profiler.snapshot(session, job_id=job_id, context_id=context_id, page=page, name=f"goto_{i}", artifacts_dir=artifacts_dir)
            elif step.kind == "wait_ms":
                await page.wait_for_timeout(int(step.ms or 0))
            elif step.kind == "wait_for_domcontentloaded":
                await page.wait_for_load_state("domcontentloaded")
            elif step.kind == "screenshot":
                await self._screenshot(
                    session,
                    job_id=job_id,
                    context_id=context_id,
                    page=page,
                    artifacts_dir=artifacts_dir,
                    name=step.name or f"step_{i}",
                )
            elif step.kind == "capture_dom":
                html = await page.content()
                path = artifacts_dir / "gst_dom" / f"page_{i}.html"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(html, encoding="utf-8")
                await self.artifacts.record_file(
                    session,
                    job_id=job_id,
                    context_id=context_id,
                    kind="gst_dom",
                    path=path,
                    relpath=str(path.relative_to(Path(self.settings.browser_artifacts_dir))),
                )
            elif step.kind == "detect_auth_state":
                a = await detector.detect(page)
                await self._write_json_artifact(
                    session,
                    job_id=job_id,
                    context_id=context_id,
                    artifacts_dir=artifacts_dir,
                    kind="gst_auth_state",
                    filename=f"auth_state_{i}.json",
                    payload={"state": a.state, "details": a.details},
                )
            elif step.kind == "measure_latency":
                # Use navigation timing snapshot (already captured); emit a quick performance mark.
                perf = await page.evaluate("() => performance.now()")
                await self._write_json_artifact(
                    session,
                    job_id=job_id,
                    context_id=context_id,
                    artifacts_dir=artifacts_dir,
                    kind="gst_latency",
                    filename=f"latency_{i}.json",
                    payload={"performance_now_ms": float(perf)},
                )
            elif step.kind == "selector_probe":
                assert step.selector is not None
                count = await page.locator(step.selector).count()
                await self._write_json_artifact(
                    session,
                    job_id=job_id,
                    context_id=context_id,
                    artifacts_dir=artifacts_dir,
                    kind="gst_selector_probe",
                    filename=f"selector_probe_{i}.json",
                    payload={"selector": step.selector, "count": int(count)},
                )
            else:
                raise ValueError(f"unsupported gst_safe_probe step: {step.kind}")

    async def _discover_selectors(self, page: Page) -> list[SelectorCandidateSet]:
        # Read-only: extract likely auth-related selectors for later operator review.
        data = await page.evaluate(
            """() => {
              function sel(el) {
                const out = [];
                if (el.id) out.push('#' + CSS.escape(el.id));
                const name = el.getAttribute('name');
                if (name) out.push(`${el.tagName.toLowerCase()}[name="${name}"]`);
                const aria = el.getAttribute('aria-label');
                if (aria) out.push(`${el.tagName.toLowerCase()}[aria-label="${aria}"]`);
                const ph = el.getAttribute('placeholder');
                if (ph) out.push(`${el.tagName.toLowerCase()}[placeholder="${ph}"]`);
                return out.slice(0, 4);
              }
              const inputs = Array.from(document.querySelectorAll('input')).slice(0, 20);
              const buttons = Array.from(document.querySelectorAll('button, input[type="submit"]')).slice(0, 20);
              return {
                inputs: inputs.map(el => ({type: el.getAttribute('type') || 'text', candidates: sel(el)})),
                buttons: buttons.map(el => ({text: (el.innerText || el.value || '').slice(0, 40), candidates: sel(el)})),
              };
            }"""
        )
        out: list[SelectorCandidateSet] = []
        try:
            inputs = data.get("inputs", [])
            for idx, it in enumerate(inputs):
                cands = [c for c in it.get("candidates", []) if isinstance(c, str)]
                if cands:
                    out.append(SelectorCandidateSet(key=f"input_{idx}", candidates=cands, notes={"type": it.get("type")}))
            buttons = data.get("buttons", [])
            for idx, it in enumerate(buttons):
                cands = [c for c in it.get("candidates", []) if isinstance(c, str)]
                if cands:
                    out.append(SelectorCandidateSet(key=f"button_{idx}", candidates=cands, notes={"text": it.get("text")}))
        except Exception:
            pass
        return out[:50]

    async def _screenshot(
        self,
        session: AsyncSession,
        *,
        job_id: uuid.UUID,
        context_id: uuid.UUID,
        page: Page,
        artifacts_dir: Path,
        name: str,
    ) -> None:
        path = artifacts_dir / "screenshots" / f"{name}.png"
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

    async def _write_json_artifact(
        self,
        session: AsyncSession,
        *,
        job_id: uuid.UUID,
        context_id: uuid.UUID,
        artifacts_dir: Path,
        kind: str,
        filename: str,
        payload: dict[str, object],
    ) -> None:
        path = artifacts_dir / kind / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")
        await self.artifacts.record_file(
            session,
            job_id=job_id,
            context_id=context_id,
            kind=kind,
            path=path,
            relpath=str(path.relative_to(Path(self.settings.browser_artifacts_dir))),
        )


async def run_gst_safe_probe(
    session: AsyncSession,
    *,
    job_id: uuid.UUID,
    context_id: uuid.UUID,
    page: Page,
    payload_json: str,
    settings: Settings,
    artifacts_dir: Path,
) -> None:
    policy = GstSafePolicy(settings=settings)
    artifacts = ArtifactManager(artifacts_root=Path(settings.browser_artifacts_dir))
    wf = GstSafeProbeWorkflow(settings=settings, artifacts=artifacts, policy=policy)
    t0 = time.monotonic()
    await wf.run(
        session,
        job_id=job_id,
        context_id=context_id,
        page=page,
        artifacts_dir=artifacts_dir,
        payload_json=payload_json,
    )
    logger.info("gst_safe_probe.completed", job_id=str(job_id), seconds=time.monotonic() - t0)
