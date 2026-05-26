from __future__ import annotations

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import redis.asyncio as redis
from playwright.async_api import Page
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.browser.artifacts import ArtifactManager
from gst_automation.core.logging import get_logger
from gst_automation.core.settings import Settings
from gst_automation.gst.auth_detection import GstAuthDetector
from gst_automation.gst.auth_fsm import AuthFsm
from gst_automation.gst.dto import GstAuthSessionPayload
from gst_automation.gst.hitl_channel import HitlChannel, OperatorAction
from gst_automation.gst.safe_policy import GstSafePolicy
from gst_automation.gst.operator_checkpoints import OperatorCheckpointService
from gst_automation.locks.redis_lock import RedisLockManager
from gst_automation.portal.sessions import SessionManager
from gst_automation.db.models.clients.client_config import ClientCredentialRef
from gst_automation.vault.base import SecretRef
from gst_automation.vault.factory import build_vault
from gst_automation.orchestration.dto import JobCreate, JobPriority
from gst_automation.orchestration.services.orchestrator_service import OrchestratorService
from gst_automation.celery_app.client import get_celery


logger = get_logger(__name__)

_CAPTCHA_PAGE_PATH = "current_auth_page.png"
_CAPTCHA_IMAGE_PATH = "current_captcha.png"
_CAPTCHA_STATE_PATH = "captcha_state.json"


@dataclass
class CaptchaHandler:
    """HITL-friendly CAPTCHA artifact flow for gst-auth (no OCR/solving)."""

    settings: Settings
    page: Page
    job_id: uuid.UUID
    checkpoint_id: uuid.UUID
    refresh_count: int = 0
    failure_count: int = 0

    @property
    def auth_page_path(self) -> Path:
        return Path(self.settings.data_dir) / _CAPTCHA_PAGE_PATH

    @property
    def captcha_image_path(self) -> Path:
        return Path(self.settings.data_dir) / _CAPTCHA_IMAGE_PATH

    @property
    def state_path(self) -> Path:
        return Path(self.settings.data_dir) / _CAPTCHA_STATE_PATH

    async def capture(self, *, status: str) -> None:
        Path(self.settings.data_dir).mkdir(parents=True, exist_ok=True)
        await self.page.screenshot(path=str(self.auth_page_path), full_page=True)
        await self._capture_captcha_image_best_effort()
        self._write_state(status=status)

    async def refresh(self) -> bool:
        attempted = await self._click_refresh_best_effort()
        if attempted:
            self.refresh_count += 1
            await self.capture(status="captcha_refreshed")
        return attempted

    def mark_failure(self, reason: str) -> None:
        self.failure_count += 1
        self._write_state(status=reason)

    async def _capture_captcha_image_best_effort(self) -> None:
        for sel in (
            "img[alt*='captcha' i]",
            "img[src*='captcha' i]",
        ):
            try:
                loc = self.page.locator(sel).first
                if await loc.count():
                    await loc.screenshot(path=str(self.captcha_image_path))
                    return
            except Exception:
                continue

    async def _click_refresh_best_effort(self) -> bool:
        for sel in (
            # Common patterns around CAPTCHA refresh buttons/icons.
            "button[title*='refresh' i]",
            "button[aria-label*='refresh' i]",
            "button[id*='refresh' i]",
            "button[class*='refresh' i]",
            "a[title*='refresh' i]",
            "a[aria-label*='refresh' i]",
            "a[id*='refresh' i]",
            "a[class*='refresh' i]",
            "xpath=//img[contains(translate(@alt,'REFSH','refsh'),'refresh')]/ancestor::button[1]",
            "xpath=//img[contains(translate(@alt,'REFSH','refsh'),'refresh')]",
            "xpath=//img[contains(translate(@src,'REFSH','refsh'),'refresh')]/ancestor::button[1]",
            "xpath=//img[contains(translate(@src,'REFSH','refsh'),'refresh')]",
            # Heuristic: refresh icon adjacent to CAPTCHA image.
            "xpath=(//img[contains(translate(@src,'CAPTCHA','captcha'),'captcha') or contains(translate(@alt,'CAPTCHA','captcha'),'captcha')])[1]/following::*[self::button or self::a or self::img][1]",
            # Some portals refresh CAPTCHA when clicking the image itself.
            "img[alt*='captcha' i]",
            "img[src*='captcha' i]",
        ):
            try:
                loc = self.page.locator(sel).first
                if await loc.count():
                    await loc.click(timeout=5000, no_wait_after=True)
                    return True
            except Exception:
                continue
        return False

    def _write_state(self, *, status: str) -> None:
        obj = {
            "job_id": str(self.job_id),
            "checkpoint_id": str(self.checkpoint_id),
            "url": self.page.url,
            "status": status,
            "refresh_count": int(self.refresh_count),
            "failure_count": int(self.failure_count),
            "updated_at": datetime.now(UTC).isoformat(),
            "auth_page_path": str(self.auth_page_path),
            "captcha_image_path": str(self.captcha_image_path),
        }
        self.state_path.write_text(json.dumps(obj, sort_keys=True, indent=2), encoding="utf-8")


@dataclass(frozen=True, slots=True)
class GstAuthSessionEngine:
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
        payload = GstAuthSessionPayload.model_validate(json.loads(payload_json))
        policy = GstSafePolicy(settings=self.settings)
        # Use same allowlist field for auth to prevent accidental prod runs without explicit config.
        policy.assert_url_allowed(payload.start_url)

        # GSTIN-level mutex to prevent parallel auth storms.
        lock_mgr = RedisLockManager(redis_client)
        lock_handle = None
        if payload.gstin:
            lock_handle = await lock_mgr.acquire(
                name=f"gst_auth:{payload.gstin}",
                owner=f"job:{job_id}",
                ttl_seconds=int(payload.checkpoint_timeout_seconds) + 60,
            )
            if lock_handle is None:
                raise RuntimeError("gst auth mutex busy (another auth session in progress)")

        artifacts = ArtifactManager(artifacts_root=Path(self.settings.browser_artifacts_dir))
        checkpoints = OperatorCheckpointService(session)
        channel = HitlChannel(redis_client)
        detector = GstAuthDetector()
        creds: tuple[str, str] | None = None

        try:
            # Safety: do not allow downloads.
            page.on("download", lambda d: logger.warning("gst_auth_session.download_blocked", url=d.url))

            await page.goto(payload.start_url, wait_until="domcontentloaded")
            await self._screenshot(artifacts, session, job_id=job_id, context_id=context_id, page=page, artifacts_dir=artifacts_dir, name="login")

            fsm = AuthFsm("anonymous")
            observed = (await detector.detect(page)).state
            fsm = fsm.transition(observed)

            # Credential-driven auto-login (OTP/CAPTCHA remain HITL only).
            if fsm.state == "login_page":
                creds = await self._load_client_credentials(session, payload=payload)
                if creds is not None:
                    username, password = creds
                    await self._autofill_login_form(page, username=username, password=password)
                    await self._screenshot(
                        artifacts,
                        session,
                        job_id=job_id,
                        context_id=context_id,
                        page=page,
                        artifacts_dir=artifacts_dir,
                        name="after_autofill",
                    )
                    # If CAPTCHA is visible, do NOT submit automatically. Operator must solve it.
                    observed = (await detector.detect(page)).state
                    fsm = fsm.transition(observed)
                    if fsm.state == "login_page":
                        # Best-effort: submit only when no CAPTCHA/OTP wall is visible.
                        await self._click_login_submit(page)
                        await self._screenshot(
                            artifacts,
                            session,
                            job_id=job_id,
                            context_id=context_id,
                            page=page,
                            artifacts_dir=artifacts_dir,
                            name="after_submit",
                        )
                        observed = (await detector.detect(page)).state
                        fsm = fsm.transition(observed)

            # If already authenticated (rare in fresh context), persist session.
            if fsm.state == "authenticated":
                await self._persist_session(session, page=page, payload=payload)
                await self._validate_persisted_session(session, payload=payload)
                await self._post_auth_continue(session, payload=payload, actor="gst_auth_session")
                return

            # Create a HITL checkpoint describing required operator action.
            checkpoint_kind = "gst_auth"
            if fsm.state in {"otp_required", "captcha_required"}:
                instructions = (
                    "OTP/CAPTCHA required. Provide supervised inputs via /auth/checkpoints/{id}/actions. "
                    "Username/password were autofilled automatically. "
                    "Do not attempt unattended execution."
                )
            elif fsm.state == "login_page":
                instructions = (
                    "Auto-login did not reach OTP/CAPTCHA/authenticated. This usually indicates wrong credentials "
                    "or an unexpected GST portal flow. Review artifacts; if credentials are wrong, fix Vault/username "
                    "and retry gst-auth. Operator actions should be limited to OTP/CAPTCHA or recovery clicks only."
                )
            else:
                instructions = (
                    f"Unexpected auth state detected: {fsm.state}. Provide supervised recovery via /auth/checkpoints/{{id}}/actions. "
                    "Do not enter username/password manually; those are sourced from onboarding."
                )
            checkpoint_id = await checkpoints.create(
                job_id=job_id,
                context_id=context_id,
                kind=checkpoint_kind,
                instructions=instructions,
                details={
                    "fsm_state": fsm.state,
                    "url": page.url,
                    "start_url": payload.start_url,
                    "gstin": payload.gstin,
                },
            )
            await session.commit()
            captcha = CaptchaHandler(settings=self.settings, page=page, job_id=job_id, checkpoint_id=checkpoint_id)
            await captcha.capture(status=f"waiting:{fsm.state}")

            deadline = datetime.now(UTC).timestamp() + float(payload.checkpoint_timeout_seconds)
            while datetime.now(UTC).timestamp() < deadline:
                # Execute operator-provided actions (ephemeral; do not persist secrets).
                act = await channel.pop_action(checkpoint_id=checkpoint_id, timeout_seconds=5)
                if act is None:
                    # Also allow "approve" resolution without actions.
                    row = await checkpoints.get(checkpoint_id)
                    if row and row.status == "approved":
                        break
                    if row and row.status == "rejected":
                        raise RuntimeError("operator rejected authentication")
                    continue

                await self._apply_operator_action(page, act, captcha=captcha)
                await self._screenshot(artifacts, session, job_id=job_id, context_id=context_id, page=page, artifacts_dir=artifacts_dir, name="after_operator_action")

                observed = (await detector.detect(page)).state
                fsm = fsm.transition(observed)
                # GST portal sometimes clears password after failed CAPTCHA/login attempts.
                # Operator never retypes credentials; deterministically re-fill if missing.
                if creds is not None and fsm.state in {"captcha_required", "login_page"}:
                    try:
                        username, password = creds
                        await self._ensure_login_filled(page, username=username, password=password)
                    except Exception:
                        pass
                # After operator provides OTP/CAPTCHA inputs, try submitting automatically.
                if fsm.state in {"otp_required", "captcha_required"}:
                    await self._maybe_submit_after_human(page, state=fsm.state)
                    await captcha.capture(status=f"submitted:{fsm.state}")
                    # If CAPTCHA remains required after submit, auto-refresh once on common invalid signals.
                    if fsm.state == "captcha_required":
                        try:
                            txt = await page.evaluate(
                                "() => (document.body && document.body.innerText ? document.body.innerText.toLowerCase().slice(0, 5000) : '')"
                            )
                        except Exception:
                            txt = ""
                        if "invalid captcha" in txt or "captcha invalid" in txt:
                            captcha.mark_failure("captcha_invalid")
                            if captcha.refresh_count < 10:
                                await captcha.refresh()
                if fsm.state == "authenticated":
                    await checkpoints.resolve(checkpoint_id=checkpoint_id, status="approved", resolved_by="operator_action")
                    await session.commit()
                    break
                if fsm.state in {"captcha_required", "login_page"}:
                    await captcha.capture(status=f"still:{fsm.state}")

            # Final verification
            observed = (await detector.detect(page)).state
            fsm = fsm.transition(observed)
            if fsm.state != "authenticated":
                raise RuntimeError(f"auth did not reach authenticated state (state={fsm.state})")

            # Ensure session is fully established (portal may show modal gates).
            await self._post_auth_stabilize(page)

            await self._persist_session(session, page=page, payload=payload)
            await self._validate_persisted_session(session, payload=payload)
            await self._screenshot(artifacts, session, job_id=job_id, context_id=context_id, page=page, artifacts_dir=artifacts_dir, name="authenticated")
            await self._post_auth_continue(session, payload=payload, actor="gst_auth_session")
        finally:
            if lock_handle is not None:
                await lock_mgr.release(lock_handle)

    async def _post_auth_stabilize(self, page: Page) -> None:
        # GST commonly shows post-login modals; dismiss to allow token/session finalization.
        try:
            for sel in (
                "button:has-text('REMIND ME LATER')",
                "button:has-text('Remind Me Later')",
                "button:has-text('CONTINUE TO DASHBOARD')",
                "button:has-text('Continue to Dashboard')",
                "text=/remind me later/i",
                "text=/continue to dashboard/i",
            ):
                try:
                    loc = page.locator(sel).first
                    if await loc.count():
                        await loc.click(timeout=3000, no_wait_after=True)
                        await page.wait_for_timeout(800)
                        break
                except Exception:
                    continue
            # Let async calls complete and cookies update.
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            await page.wait_for_timeout(1200)
        except Exception:
            return

    async def _persist_session(self, session: AsyncSession, *, page: Page, payload: GstAuthSessionPayload) -> None:
        storage = await page.context.storage_state()
        # Playwright storage_state should include cookies, but keep a defensive merge from the live cookie jar.
        try:
            live_cookies = await page.context.cookies()
            if isinstance(live_cookies, list):
                existing = storage.get("cookies") if isinstance(storage, dict) else None
                if not isinstance(existing, list):
                    existing = []
                    storage["cookies"] = existing
                seen = {(c.get("name"), c.get("domain"), c.get("path")) for c in existing if isinstance(c, dict)}
                for c in live_cookies:
                    if not isinstance(c, dict):
                        continue
                    key = (c.get("name"), c.get("domain"), c.get("path"))
                    if key not in seen:
                        existing.append(c)
                        seen.add(key)
        except Exception:
            pass
        # GST sometimes stores auth tokens in sessionStorage (not included in Playwright storage_state).
        # Capture it best-effort so later jobs can restore full client-side auth state.
        try:
            origin = await page.evaluate("() => location.origin")
            ss = await page.evaluate(
                "() => { const o = {}; for (let i=0;i<sessionStorage.length;i++){ const k=sessionStorage.key(i); if(k){ o[k]=sessionStorage.getItem(k)||''; } } return o; }"
            )
            if isinstance(ss, dict) and ss:
                storage["__sessionStorage"] = {str(origin): ss}
        except Exception:
            pass
        mgr = SessionManager(settings=self.settings)
        client_uuid = uuid.UUID(payload.client_id) if payload.client_id else None
        await mgr.save_storage_state(
            session,
            client_id=client_uuid,
            profile=payload.profile,
            storage_state=storage,
            ttl_days=int(payload.ttl_days),
        )

    async def _validate_persisted_session(self, session: AsyncSession, *, payload: GstAuthSessionPayload) -> None:
        client_uuid = uuid.UUID(payload.client_id) if payload.client_id else None
        state = await SessionManager(settings=self.settings).load_latest_storage_state(
            session,
            client_id=client_uuid,
            profile=payload.profile,
        )
        ok = bool(state and isinstance(state, dict) and ("cookies" in state or "origins" in state))
        if not ok:
            raise RuntimeError("persisted session storage_state failed validation (decrypt/shape)")
        cookies = state.get("cookies") if isinstance(state, dict) else None
        origins = state.get("origins") if isinstance(state, dict) else None
        logger.info(
            "gst.session_persisted",
            client_id=str(client_uuid) if client_uuid else None,
            cookies_count=len(cookies or []) if isinstance(cookies, list) else None,
            origins_count=len(origins or []) if isinstance(origins, list) else None,
        )

    async def _load_client_credentials(
        self, session: AsyncSession, *, payload: GstAuthSessionPayload
    ) -> tuple[str, str] | None:
        if not payload.client_id:
            return None
        client_uuid = uuid.UUID(payload.client_id)
        cref = await session.get(ClientCredentialRef, client_uuid)
        if cref is None:
            raise RuntimeError("client credentials missing (client_credential_refs row not found)")
        if not cref.gst_password_secret_key or ":" not in cref.gst_password_secret_key:
            raise RuntimeError("client password secret ref invalid (expected namespace:key)")
        namespace, key = cref.gst_password_secret_key.split(":", 1)
        vault = build_vault(self.settings)
        try:
            password = await vault.get_secret(SecretRef(namespace=namespace, key=key))
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"unable to load GST password from vault ({namespace}:{key})") from exc
        username = (cref.gst_username or "").strip()
        if not username:
            raise RuntimeError("client GST username missing")
        if not password:
            raise RuntimeError("client GST password missing in vault")
        return username, str(password)

    async def _attempt_autologin(self, page: Page, *, username: str, password: str) -> None:
        # Heuristic selectors; do not attempt OTP/CAPTCHA bypassing.
        # Some GST pages render hidden login inputs until a "Login" button is clicked.
        # Try to reveal the login form first (best-effort).
        for sel in ("button:has-text('Login')", "a:has-text('Login')", "text=/login/i"):
            try:
                loc = page.locator(sel).first
                if await loc.count():
                    await loc.click(timeout=2000)
                    break
            except Exception:
                continue

        user_loc = page.locator(
            "input[type='email']:visible, input[name*='user' i]:visible, input[id*='user' i]:visible, input[type='text']:visible"
        ).first
        pass_loc = page.locator("input[type='password']:visible").first
        try:
            await pass_loc.wait_for(state="visible", timeout=15000)
            await user_loc.fill(username)
            await pass_loc.fill(password)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "unable to autofill GST credentials (login fields not visible/interactive)"
            ) from exc

        # Try common submit patterns.
        await self._click_login_submit(page)

    async def _autofill_login_form(self, page: Page, *, username: str, password: str) -> None:
        # Heuristic selectors; do not attempt OTP/CAPTCHA bypassing.
        for sel in ("button:has-text('Login')", "a:has-text('Login')", "text=/login/i"):
            try:
                loc = page.locator(sel).first
                if await loc.count():
                    await loc.click(timeout=2000)
                    break
            except Exception:
                continue

        user_loc = page.locator(
            "input[type='email']:visible, input[name*='user' i]:visible, input[id*='user' i]:visible, input[type='text']:visible"
        ).first
        pass_loc = page.locator("input[type='password']:visible").first
        try:
            await pass_loc.wait_for(state="visible", timeout=15000)
            await user_loc.fill(username)
            await pass_loc.fill(password)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "unable to autofill GST credentials (login fields not visible/interactive)"
            ) from exc

    async def _ensure_login_filled(self, page: Page, *, username: str, password: str) -> None:
        user_loc = page.locator(
            "input[type='email']:visible, input[name*='user' i]:visible, input[id*='user' i]:visible, input[type='text']:visible"
        ).first
        pass_loc = page.locator("input[type='password']:visible").first
        try:
            val = await user_loc.input_value(timeout=1000)
            if not (val or "").strip():
                await user_loc.fill(username)
        except Exception:
            pass
        try:
            val = await pass_loc.input_value(timeout=1000)
            if not (val or "").strip():
                await pass_loc.fill(password)
        except Exception:
            pass

    async def _click_login_submit(self, page: Page) -> None:
        submit = page.locator("button[type='submit'],input[type='submit']").first
        try:
            await submit.click(timeout=5000)
            return
        except Exception:
            pass
        for sel in ("button:has-text('LOGIN')", "button:has-text('Login')", "text=/^login$/i"):
            try:
                await page.click(sel, timeout=5000)
                return
            except Exception:
                continue
        raise RuntimeError("unable to click GST login submit")

    async def _maybe_submit_after_human(self, page: Page, *, state: str) -> None:
        # After CAPTCHA/OTP is typed by operator, attempt to submit to advance state.
        try:
            if state == "captcha_required":
                cap = page.locator(
                    "input[placeholder*='characters' i]:visible, input[name*='captcha' i]:visible, input[id*='captcha' i]:visible"
                ).first
                val = await cap.input_value(timeout=2000)
                if val and val.strip():
                    await self._click_login_submit(page)
                    try:
                        await page.wait_for_load_state("domcontentloaded", timeout=10000)
                    except Exception:
                        pass
            elif state == "otp_required":
                otp = page.locator(
                    "input[inputmode='numeric']:visible, input[name*='otp' i]:visible, input[id*='otp' i]:visible"
                ).first
                val = await otp.input_value(timeout=2000)
                if val and len(val.strip()) >= 4:
                    await self._click_login_submit(page)
                    try:
                        await page.wait_for_load_state("domcontentloaded", timeout=10000)
                    except Exception:
                        pass
        except Exception:
            # Best-effort only.
            return

    async def _apply_operator_action(self, page: Page, act: OperatorAction, *, captcha: CaptchaHandler) -> None:
        # Safety: only allow minimal input actions; no clicking arbitrary buttons by default.
        if act.kind == "type":
            if not act.selector:
                raise ValueError("selector required")
            # Sensitive values (OTP/CAPTCHA) are used transiently; not persisted.
            await page.fill(act.selector, act.value or "")
        elif act.kind == "press":
            if not act.selector:
                raise ValueError("selector required")
            await page.press(act.selector, act.key or "Enter")
        elif act.kind == "click":
            # Allow only clicking within form controls explicitly provided by operator.
            if not act.selector:
                raise ValueError("selector required")
            try:
                await page.click(act.selector, timeout=5000, no_wait_after=True)
            except Exception:
                # Common operator action: click LOGIN. The portal sometimes renders as "Login" (case) or
                # uses different DOM for the submit. Fall back to our hardened submit helper.
                if "login" in (act.selector or "").lower():
                    await self._click_login_submit(page)
                else:
                    raise
            # Give the portal a moment to advance state after click-driven submits.
            try:
                await page.wait_for_timeout(800)
            except Exception:
                pass
        elif act.kind == "captcha_refresh":
            ok = await captcha.refresh()
            if not ok:
                captcha.mark_failure("captcha_refresh_not_found")
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

    async def _post_auth_continue(self, session: AsyncSession, *, payload: GstAuthSessionPayload, actor: str) -> None:
        # After successful auth, enqueue observation for selector capture (so monthly proving can proceed).
        if not payload.client_id:
            return
        try:
            orch = OrchestratorService(session=session, celery=get_celery())
            await orch.create_and_enqueue(
                JobCreate(
                    kind="gst_observation_session",
                    client_id=uuid.UUID(payload.client_id),
                    queue="downloads",
                    priority=JobPriority.P2_DOWNLOAD,
                    payload={
                        "start_url": self.settings.gst_probe_base_url or payload.start_url,
                        "checkpoint_timeout_seconds": 7200,
                        "notes": f"auto-continued from gst-auth (client_id={payload.client_id})",
                    },
                ),
                actor=actor,
            )
            await session.commit()
            logger.info("gst.auth_continue_observe_enqueued", client_id=payload.client_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("gst.auth_continue_observe_failed", client_id=payload.client_id, err=str(exc))
