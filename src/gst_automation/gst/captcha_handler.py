"""CAPTCHA detection and Telegram-based HITL routing."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from datetime import UTC, datetime

from playwright.async_api import Page
import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.core.logging import get_logger
from gst_automation.core.settings import Settings
from gst_automation.telegram_bot.client import TelegramClient
from gst_automation.telegram_bot.scheduler import TelegramCaptchaService
from gst_automation.browser.artifacts import ArtifactManager

logger = get_logger(__name__)


class CaptchaDetector:
    """Detects CAPTCHA on GST pages."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def detect_captcha(self, page: Page) -> bool:
        """Check if CAPTCHA is visible on current page."""
        try:
            # Check for common CAPTCHA indicators on GST portal
            selectors = [
                "img[src*='captcha']",
                "div[id*='captcha']",
                "iframe[src*='captcha']",
                "div.captcha",
                "div.recaptcha",
                "#g-recaptcha",
                "div[class*='captcha']",
            ]

            for selector in selectors:
                try:
                    element = page.locator(selector).first
                    if await element.is_visible():
                        logger.info("gst.captcha_detected", selector=selector)
                        return True
                except Exception:
                    continue

            return False
        except Exception as exc:
            logger.warning("gst.captcha_detection_error", err=str(exc))
            return False

    async def capture_captcha_image(
        self,
        page: Page,
        artifacts_dir: Path,
    ) -> Path | None:
        """Capture CAPTCHA image and save to disk."""
        try:
            selectors = [
                "img[src*='captcha']",
                "div#captcha-image img",
                "img.captcha-image",
                "div.captcha img",
                "div.recaptcha",
                "iframe[src*='captcha']",
            ]

            for selector in selectors:
                try:
                    element = page.locator(selector).first
                    if await element.is_visible():
                        artifacts_dir.mkdir(parents=True, exist_ok=True)
                        captcha_path = artifacts_dir / "captcha.png"
                        await element.screenshot(path=captcha_path)
                        logger.info(
                            "gst.captcha_image_captured",
                            path=str(captcha_path),
                            selector=selector,
                        )
                        return captcha_path
                except Exception:
                    continue

            return None
        except Exception as exc:
            logger.error("gst.captcha_capture_failed", err=str(exc))
            return None

    async def capture_full_page_screenshot(
        self,
        page: Page,
        artifacts_dir: Path,
        name: str = "page",
    ) -> Path | None:
        """Capture full page screenshot for context."""
        try:
            artifacts_dir.mkdir(parents=True, exist_ok=True)
            screenshot_path = artifacts_dir / f"{name}_screenshot.png"
            await page.screenshot(path=screenshot_path)
            logger.info("gst.screenshot_captured", path=str(screenshot_path))
            return screenshot_path
        except Exception as exc:
            logger.error("gst.screenshot_capture_failed", err=str(exc))
            return None


class CaptchaHitlHandler:
    """Handles CAPTCHA HITL workflow via Telegram."""

    def __init__(
        self,
        settings: Settings,
        session: AsyncSession,
        redis_client: redis.Redis,
        page: Page,
    ) -> None:
        self.settings = settings
        self.session = session
        self.redis = redis_client
        self.page = page
        self.detector = CaptchaDetector(settings)
        self.captcha_service = TelegramCaptchaService(settings, session, redis_client)
        self.telegram = TelegramClient(settings, redis_client)

    async def handle_captcha(
        self,
        checkpoint_id: uuid.UUID,
        job_id: uuid.UUID,
        client_display_name: str,
        gstin: str,
        artifacts_dir: Path,
    ) -> bool:
        """Handle CAPTCHA: detect, screenshot, send to Telegram, wait for response, inject."""
        try:
            # Step 1: Verify CAPTCHA is present
            if not await self.detector.detect_captcha(self.page):
                logger.warning(
                    "gst.captcha_handle_not_visible",
                    checkpoint_id=str(checkpoint_id),
                    job_id=str(job_id),
                )
                return False

            # Step 2: Capture CAPTCHA image
            captcha_path = await self.detector.capture_captcha_image(self.page, artifacts_dir)
            if not captcha_path or not captcha_path.exists():
                logger.error(
                    "gst.captcha_capture_failed",
                    checkpoint_id=str(checkpoint_id),
                    job_id=str(job_id),
                )
                return False

            # Step 3: Send to Telegram
            sent = await self.captcha_service.send_captcha_request(
                checkpoint_id=checkpoint_id,
                job_id=job_id,
                client_display_name=client_display_name,
                gstin=gstin,
                captcha_image_path=str(captcha_path),
            )
            if not sent:
                logger.error(
                    "gst.captcha_telegram_send_failed",
                    checkpoint_id=str(checkpoint_id),
                    job_id=str(job_id),
                )
                return False

            # Step 4: Wait for operator response (with timeout)
            timeout = self.settings.telegram_captcha_timeout_seconds
            start_time = datetime.now(UTC)
            captcha_text = None

            while (datetime.now(UTC) - start_time).total_seconds() < timeout:
                captcha_text = await self.captcha_service.wait_for_captcha_response(
                    checkpoint_id=checkpoint_id,
                    timeout_seconds=min(30, timeout - int((datetime.now(UTC) - start_time).total_seconds())),
                )
                if captcha_text:
                    break

            if not captcha_text:
                logger.warning(
                    "gst.captcha_timeout",
                    checkpoint_id=str(checkpoint_id),
                    timeout_seconds=timeout,
                )
                return False

            # Step 5: Inject CAPTCHA into form
            success = await self._inject_captcha(captcha_text)
            if not success:
                logger.error(
                    "gst.captcha_inject_failed",
                    checkpoint_id=str(checkpoint_id),
                    job_id=str(job_id),
                )
                return False

            logger.info(
                "gst.captcha_handled",
                checkpoint_id=str(checkpoint_id),
                job_id=str(job_id),
            )
            return True

        except Exception as exc:
            logger.exception(
                "gst.captcha_handle_error",
                checkpoint_id=str(checkpoint_id),
                err=str(exc),
            )
            return False

    async def _inject_captcha(self, captcha_text: str) -> bool:
        """Inject CAPTCHA text into form and submit."""
        try:
            # Try common CAPTCHA field selectors
            selectors = [
                "#captcha",
                "input[name='captcha']",
                "input[name='userCaptcha']",
                "input[name='captchaText']",
                "input[id*='captcha']",
                "input[placeholder*='CAPTCHA']",
                "input[placeholder*='Captcha']",
            ]

            captcha_field = None
            for selector in selectors:
                try:
                    field = self.page.locator(selector).first
                    if await field.is_visible():
                        captcha_field = field
                        break
                except Exception:
                    continue

            if not captcha_field:
                logger.error("gst.captcha_field_not_found")
                return False

            # Clear and fill
            await captcha_field.clear()
            await captcha_field.type(captcha_text)

            # Look for submit button and click
            submit_selectors = [
                "button:has-text('Sign In')",
                "button:has-text('Login')",
                "button:has-text('SIGN IN')",
                "button:has-text('LOGIN')",
                "button[type='submit']",
                "button#loginBtn",
                "button#submitBtn",
            ]

            for selector in submit_selectors:
                try:
                    submit_btn = self.page.locator(selector).first
                    if await submit_btn.is_visible():
                        await submit_btn.click()
                        # Wait for navigation/loading
                        await asyncio.sleep(2)
                        return True
                except Exception:
                    continue

            logger.warning("gst.captcha_submit_button_not_found")
            return False

        except Exception as exc:
            logger.error("gst.captcha_inject_error", err=str(exc))
            return False
