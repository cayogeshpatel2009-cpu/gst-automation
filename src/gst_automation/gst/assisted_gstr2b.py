from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path

from playwright.async_api import Page
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.browser.artifacts import ArtifactManager
from gst_automation.core.logging import get_logger
from gst_automation.core.settings import Settings
from gst_automation.gst.auth_detection import GstAuthDetector
from gst_automation.gst.hitl_channel import HitlChannel, OperatorAction
from gst_automation.gst.operator_checkpoints import OperatorCheckpointService
from gst_automation.portal.sessions import SessionManager


logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class AssistedGstr2bPayload:
    client_id: str | None = None
    profile: str = "gst"
    start_url: str = ""
    checkpoint_timeout_seconds: int = 600


@dataclass(frozen=True, slots=True)
class AssistedGstr2bEngine:
    settings: Settings

    async def run(
        self,
        session: AsyncSession,
        redis_client: object,
        *,
        job_id: uuid.UUID,
        context_id: uuid.UUID,
        page: Page,
        artifacts_dir: Path,
        payload_json: str,
    ) -> None:
        payload = AssistedGstr2bPayload(**json.loads(payload_json))
        mgr = SessionManager(settings=self.settings)
        client_uuid = uuid.UUID(payload.client_id) if payload.client_id else None
        storage = await mgr.load_latest_storage_state(session, client_id=client_uuid, profile=payload.profile)
        if storage is None:
            raise RuntimeError("no stored session state available for assisted execution")

        # Apply storage state by setting it on context is not supported post-creation;
        # this engine assumes the context was created for assisted runs separately in later iteration.
        # For now, we validate navigation + auth state and fall back to HITL.
        detector = GstAuthDetector()
        artifacts = ArtifactManager(artifacts_root=Path(self.settings.browser_artifacts_dir))
        checkpoints = OperatorCheckpointService(session)
        channel = HitlChannel(redis_client)  # type: ignore[arg-type]

        if payload.start_url:
            await page.goto(payload.start_url, wait_until="domcontentloaded")

        state = await detector.detect(page)
        if state.state != "authenticated":
            checkpoint_id = await checkpoints.create(
                job_id=job_id,
                context_id=context_id,
                kind="assisted_gstr2b",
                instructions="Assisted GSTR-2B execution needs operator to bring session to authenticated state.",
                details={"url": page.url, "auth_state": state.state},
            )
            await session.commit()
            # Wait for operator to approve (after manual actions).
            deadline = __import__("time").time() + float(payload.checkpoint_timeout_seconds)
            while __import__("time").time() < deadline:
                row = await checkpoints.get(checkpoint_id)
                if row and row.status == "approved":
                    break
                act = await channel.pop_action(checkpoint_id=checkpoint_id, timeout_seconds=5)
                if act:
                    await self._apply_operator_action(page, act)
            state = await detector.detect(page)
            if state.state != "authenticated":
                raise RuntimeError("assisted run could not reach authenticated state")

        # Placeholder: actual navigation to GSTR-2B and download is implemented after observation stabilizes.
        await page.screenshot(path=str(artifacts_dir / "screenshots" / "assisted_ready.png"), full_page=True)
        await artifacts.record_file(
            session,
            job_id=job_id,
            context_id=context_id,
            kind="screenshot",
            path=artifacts_dir / "screenshots" / "assisted_ready.png",
            relpath=str((artifacts_dir / "screenshots" / "assisted_ready.png").relative_to(Path(self.settings.browser_artifacts_dir))),
        )
        logger.info("assisted_gstr2b.ready", job_id=str(job_id))

    async def _apply_operator_action(self, page: Page, act: OperatorAction) -> None:
        if act.kind == "type":
            await page.fill(act.selector or "", act.value or "")
        elif act.kind == "press":
            await page.press(act.selector or "", act.key or "Enter")
        elif act.kind == "click":
            await page.click(act.selector or "")

