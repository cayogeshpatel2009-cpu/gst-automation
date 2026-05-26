from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import redis.asyncio as redis
from playwright.async_api import Page
from sqlalchemy.ext.asyncio import AsyncSession
import asyncio

from gst_automation.browser.artifacts import ArtifactManager
from gst_automation.core.logging import get_logger
from gst_automation.core.settings import Settings
from gst_automation.db.models.gst.observation import GstObservationSession, GstWorkflowGraph
from gst_automation.db.models.orchestration.job import Job
from gst_automation.db.models.client import Client
from gst_automation.gst.auth_detection import AuthState, GstAuthDetector
from gst_automation.gst.auth_session import GstAuthSessionEngine
from gst_automation.gst.hitl_channel import HitlChannel, OperatorAction
from gst_automation.gst.operator_checkpoints import OperatorCheckpointService
from gst_automation.gst.safe_policy import GstSafePolicy
from gst_automation.validation.recorder import WorkflowRecorder


logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class GstObservationPayload:
    start_url: str
    checkpoint_timeout_seconds: int = 3600
    notes: str = ""


@dataclass(frozen=True, slots=True)
class GstObservationEngine:
    settings: Settings

    async def run(
        self,
        session: AsyncSession,
        redis_client: redis.Redis,
        *,
        job_id: uuid.UUID,
        context_id: uuid.UUID,
        page: Page,
        artifacts_dir: Path,
        payload_json: str,
    ) -> None:
        payload = GstObservationPayload(**json.loads(payload_json))
        policy = GstSafePolicy(settings=self.settings)
        policy.assert_url_allowed(payload.start_url)

        artifacts = ArtifactManager(artifacts_root=Path(self.settings.browser_artifacts_dir))
        recorder = WorkflowRecorder(path=artifacts_dir / "replay.jsonl")
        detector = GstAuthDetector()
        checkpoints = OperatorCheckpointService(session)
        channel = HitlChannel(redis_client)

        obs = GstObservationSession(
            job_id=job_id,
            context_id=context_id,
            status="running",
            start_url=payload.start_url,
            notes=payload.notes or "",
            operator_checkpoint_id=None,
            steps_total=0,
            downloads_total=0,
            selectors_total=0,
        )
        session.add(obs)
        await session.flush()

        # Capture console to artifact.
        console_path = artifacts_dir / "console.log"
        console_path.parent.mkdir(parents=True, exist_ok=True)

        def _write(line: str) -> None:
            with console_path.open("a", encoding="utf-8") as f:
                f.write(line)
                f.write("\n")

        page.on("console", lambda msg: _write(f"[{msg.type}] {msg.text}"))
        page.on("pageerror", lambda exc: _write(f"[pageerror] {exc}"))
        page.on("dialog", lambda dlg: _write(f"[dialog] {dlg.type}: {dlg.message}"))

        # Download observation.
        download_events: list[dict[str, object]] = []

        async def _on_download(d: Any) -> None:
            # Note: Playwright emits Download object; we record metadata only.
            download_events.append({"url": getattr(d, "url", None), "suggested_filename": d.suggested_filename})

        page.on("download", _on_download)

        recorder.record(
            {
                "ts_ms": recorder.now_ms(),
                "type": "gst_observation.start",
                "job_id": str(job_id),
                "context_id": str(context_id),
                "start_url": payload.start_url,
            }
        )

        # Navigate to start URL and capture baseline artifacts.
        page.on("framenavigated", lambda frame: recorder.record({"ts_ms": recorder.now_ms(), "type": "nav", "url": frame.url}))
        await page.goto(payload.start_url, wait_until="domcontentloaded")
        await self._screenshot(artifacts, session, job_id=job_id, context_id=context_id, page=page, artifacts_dir=artifacts_dir, name="start")

        try:
            state = await asyncio.wait_for(detector.detect(page), timeout=10.0)
        except Exception:
            state = AuthState("unknown", {"url": page.url, "title": ""})
        recorder.record({"ts_ms": recorder.now_ms(), "type": "auth.state", "state": state.state, "url": page.url})

        # If this job is scoped to a client (job.client_id), perform inline credential-driven gst-auth
        # in the SAME browser context. This avoids relying on cross-context session export/import, and
        # keeps HITL strictly to OTP/CAPTCHA.
        if state.state != "authenticated":
            try:
                job_row = await session.get(Job, job_id)
                if job_row and job_row.client_id:
                    client = await session.get(Client, job_row.client_id)
                else:
                    client = None
                if job_row and job_row.client_id and client and client.gstin:
                    logger.warning("gst.observe_inline_auth_start", job_id=str(job_id), client_id=str(job_row.client_id), state=state.state)
                    await GstAuthSessionEngine(settings=self.settings).run(
                        session=session,
                        redis_client=redis_client,
                        job_id=job_id,
                        context_id=context_id,
                        page=page,
                        artifacts_dir=artifacts_dir,
                        payload_json=json.dumps(
                            {
                                "start_url": "https://services.gst.gov.in/services/login",
                                "client_id": str(job_row.client_id),
                                "gstin": client.gstin,
                                "profile": "gst",
                                "ttl_days": 7,
                                "checkpoint_timeout_seconds": int(payload.checkpoint_timeout_seconds),
                            },
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    )
                    state = await detector.detect(page)
                    recorder.record({"ts_ms": recorder.now_ms(), "type": "auth.state", "state": state.state, "url": page.url})
            except Exception as exc:  # noqa: BLE001
                logger.warning("gst.observe_inline_auth_failed", job_id=str(job_id), err=str(exc))

        # Session-reuse hardening: with a valid storage_state loaded into the context,
        # GST may still land on /services/login briefly. Probe an authenticated landing
        # page before declaring the session "login".
        if state.state == "login":
            try:
                # Important: a direct page.goto() to /services/auth/fowelcome often yields
                # AccessDenied even with valid cookies because GST expects navigation via
                # its auth root redirect chain (login -> /services/auth/ -> fowelcome).
                # Use same-origin navigation from the current page to preserve the normal
                # fetch-metadata/referrer behavior.
                try:
                    await page.evaluate("window.location.href = '/services/auth/'")
                    await page.wait_for_load_state("domcontentloaded", timeout=15000)
                except Exception:
                    await page.goto("https://services.gst.gov.in/services/auth/", wait_until="domcontentloaded")
                await self._screenshot(
                    artifacts,
                    session,
                    job_id=job_id,
                    context_id=context_id,
                    page=page,
                    artifacts_dir=artifacts_dir,
                    name="auth_probe",
                )
                try:
                    state2 = await asyncio.wait_for(detector.detect(page), timeout=10.0)
                except Exception:
                    state2 = AuthState("unknown", {"url": page.url, "title": ""})
                recorder.record(
                    {"ts_ms": recorder.now_ms(), "type": "auth.state", "state": state2.state, "url": page.url}
                )
                state = state2
            except Exception:
                pass

        checkpoint_id = await checkpoints.create(
            job_id=job_id,
            context_id=context_id,
            kind="gst_observation",
            instructions=(
                "Operator-driven GST observation session. Send operator actions via /auth/checkpoints/{id}/actions. "
                "Perform full login + navigate to GSTR-2B + trigger ONE download. "
                "Do not perform filing/submission beyond download."
            ),
            details={"start_url": payload.start_url, "artifacts_dir": str(artifacts_dir)},
        )
        obs.operator_checkpoint_id = checkpoint_id
        await session.commit()

        deadline = datetime.now(UTC).timestamp() + float(payload.checkpoint_timeout_seconds)
        steps = 0
        selectors_seen: dict[str, int] = {}
        while datetime.now(UTC).timestamp() < deadline:
            row = await checkpoints.get(checkpoint_id)
            if row and row.status == "rejected":
                raise RuntimeError("operator aborted observation session")
            if row and row.status == "approved":
                break

            act = await channel.pop_action(checkpoint_id=checkpoint_id, timeout_seconds=5)
            if act is None:
                continue

            # Apply operator actions (these are the "manual workflow" inputs).
            await self._apply_operator_action(page, act)
            steps += 1

            # Observe selectors touched.
            if act.selector:
                selectors_seen[act.selector] = selectors_seen.get(act.selector, 0) + 1

            # Snapshot state after each step (bounded).
            if steps <= 250:
                state = await detector.detect(page)
                recorder.record(
                    {
                        "ts_ms": recorder.now_ms(),
                        "type": "operator.action",
                        "kind": act.kind,
                        "selector": act.selector,
                        "sensitive": bool(act.sensitive),
                        "url": page.url,
                        "auth_state": state.state,
                    }
                )
                await self._screenshot(
                    artifacts,
                    session,
                    job_id=job_id,
                    context_id=context_id,
                    page=page,
                    artifacts_dir=artifacts_dir,
                    name=f"step_{steps}",
                )
                # DOM fingerprint (lightweight) as artifact
                await self._dom_fingerprint_artifact(
                    artifacts,
                    session,
                    job_id=job_id,
                    context_id=context_id,
                    page=page,
                    artifacts_dir=artifacts_dir,
                    name=f"step_{steps}",
                )

            # If downloads happened, persist download metadata.
            if download_events:
                obs.downloads_total += len(download_events)
                path = artifacts_dir / "gst_downloads" / f"downloads_{steps}.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(download_events, sort_keys=True, indent=2), encoding="utf-8")
                await artifacts.record_file(
                    session,
                    job_id=job_id,
                    context_id=context_id,
                    kind="gst_downloads",
                    path=path,
                    relpath=str(path.relative_to(Path(self.settings.browser_artifacts_dir))),
                )
                recorder.record({"ts_ms": recorder.now_ms(), "type": "download.observed", "count": len(download_events)})
                download_events.clear()

            obs.steps_total = steps
            obs.selectors_total = len(selectors_seen)
            await session.flush()

        # Finalize: write selector observation artifact and graph.
        sel_path = artifacts_dir / "gst_selectors" / "selectors_observed.json"
        sel_path.parent.mkdir(parents=True, exist_ok=True)
        sel_path.write_text(json.dumps(selectors_seen, sort_keys=True, indent=2), encoding="utf-8")
        await artifacts.record_file(
            session,
            job_id=job_id,
            context_id=context_id,
            kind="gst_selectors",
            path=sel_path,
            relpath=str(sel_path.relative_to(Path(self.settings.browser_artifacts_dir))),
        )

        graph = self._build_graph_from_replay(recorder.path)
        session.add(GstWorkflowGraph(observation_id=obs.id, graph_json=json.dumps(graph, sort_keys=True)))

        # Index console log.
        if console_path.exists():
            await artifacts.record_file(
                session,
                job_id=job_id,
                context_id=context_id,
                kind="console",
                path=console_path,
                relpath=str(console_path.relative_to(Path(self.settings.browser_artifacts_dir))),
            )

        obs.status = "finished"
        obs.ended_at = datetime.now(UTC)
        recorder.record({"ts_ms": recorder.now_ms(), "type": "gst_observation.done"})
        await session.flush()

    async def _apply_operator_action(self, page: Page, act: OperatorAction) -> None:
        # Observation mode is operator-driven, but still enforce safety by requiring explicit selectors.
        if act.kind == "type":
            if not act.selector:
                raise ValueError("selector required")
            await page.fill(act.selector, act.value or "")
        elif act.kind == "press":
            if not act.selector:
                raise ValueError("selector required")
            await page.press(act.selector, act.key or "Enter")
        elif act.kind == "click":
            if not act.selector:
                raise ValueError("selector required")
            await page.click(act.selector)
        elif act.kind in {"approve", "reject"}:
            return
        else:
            raise ValueError(f"unsupported operator action: {act.kind}")

    async def _screenshot(
        self,
        artifacts: ArtifactManager,
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
        await artifacts.record_file(
            session,
            job_id=job_id,
            context_id=context_id,
            kind="screenshot",
            path=path,
            relpath=str(path.relative_to(Path(self.settings.browser_artifacts_dir))),
        )

    async def _dom_fingerprint_artifact(
        self,
        artifacts: ArtifactManager,
        session: AsyncSession,
        *,
        job_id: uuid.UUID,
        context_id: uuid.UUID,
        page: Page,
        artifacts_dir: Path,
        name: str,
    ) -> None:
        html = await page.content()
        fp = __import__("hashlib").sha256(html[:200_000].encode("utf-8")).hexdigest()
        path = artifacts_dir / "gst_dom_fp" / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"url": page.url, "sha256": fp}, sort_keys=True, indent=2), encoding="utf-8")
        await artifacts.record_file(
            session,
            job_id=job_id,
            context_id=context_id,
            kind="gst_dom_fp",
            path=path,
            relpath=str(path.relative_to(Path(self.settings.browser_artifacts_dir))),
        )

    def _build_graph_from_replay(self, replay_path: Path) -> dict[str, object]:
        # Simple navigation graph from replay JSONL: nodes=urls, edges=sequence.
        if not replay_path.exists():
            return {"nodes": [], "edges": []}
        urls: list[str] = []
        for line in replay_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if obj.get("type") in {"nav", "auth.state"} and isinstance(obj.get("url"), str):
                urls.append(obj["url"])
        # Dedup consecutive repeats.
        seq: list[str] = []
        for u in urls:
            if not seq or seq[-1] != u:
                seq.append(u)
        nodes = sorted(set(seq))
        edges: list[dict[str, str]] = []
        for a, b in zip(seq, seq[1:]):
            edges.append({"from": a, "to": b})
        return {"nodes": nodes, "edges": edges, "sequence": seq}
