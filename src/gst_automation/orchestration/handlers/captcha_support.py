"""Handler utilities for integrating Telegram CAPTCHA support into orchestration."""

from __future__ import annotations

import uuid
from pathlib import Path
from datetime import UTC, datetime

from playwright.async_api import Page
import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.core.logging import get_logger
from gst_automation.core.settings import Settings
from gst_automation.gst.captcha_handler import CaptchaHitlHandler
from gst_automation.db.models.gst.operator_checkpoint import OperatorCheckpoint
from gst_automation.db.models.orchestration.job import Job
from gst_automation.db.models.client import Client

logger = get_logger(__name__)


class HandlerCaptchaSupport:
    """Mixin for handlers to support Telegram-assisted CAPTCHA."""

    async def handle_captcha_if_present(
        self,
        *,
        session: AsyncSession,
        redis_client: redis.Redis,
        settings: Settings,
        job_id: uuid.UUID,
        context_id: uuid.UUID,
        page: Page,
        artifacts_dir: Path,
    ) -> bool:
        """
        Check for CAPTCHA on current page and handle via Telegram if present.
        
        Returns: True if CAPTCHA was successfully handled, False if not present or failed.
        """
        try:
            handler = CaptchaHitlHandler(settings, session, redis_client, page)
            
            # Check if CAPTCHA is visible
            if not await handler.detector.detect_captcha(page):
                return False
            
            logger.info(
                "handler.captcha_detected",
                job_id=str(job_id),
                page_url=page.url,
            )
            
            # Get client info for context
            job = await session.get(Job, job_id)
            client = None
            client_name = "Unknown"
            gstin = "UNKNOWN"
            
            if job and job.client_id:
                client = await session.get(Client, job.client_id)
                if client:
                    client_name = client.display_name
                    gstin = client.gstin
            
            # Create checkpoint for CAPTCHA
            checkpoint = OperatorCheckpoint(
                job_id=job_id,
                context_id=context_id,
                kind="telegram_captcha",
                status="pending",
                instructions="Operator to provide CAPTCHA text via Telegram",
                details_json=f'{{"client": "{client_name}", "gstin": "{gstin}", "url": "{page.url}"}}',
            )
            session.add(checkpoint)
            await session.flush()
            
            # Handle CAPTCHA via Telegram
            success = await handler.handle_captcha(
                checkpoint_id=checkpoint.id,
                job_id=job_id,
                client_display_name=client_name,
                gstin=gstin,
                artifacts_dir=artifacts_dir,
            )
            
            if success:
                checkpoint.status = "approved"
                checkpoint.resolved_at = datetime.now(UTC)
                await session.commit()
                logger.info(
                    "handler.captcha_resolved",
                    job_id=str(job_id),
                    checkpoint_id=str(checkpoint.id),
                )
                return True
            else:
                checkpoint.status = "rejected"
                checkpoint.resolved_at = datetime.now(UTC)
                await session.commit()
                logger.error(
                    "handler.captcha_failed",
                    job_id=str(job_id),
                    checkpoint_id=str(checkpoint.id),
                )
                return False
                
        except Exception as exc:
            logger.exception(
                "handler.captcha_support_error",
                job_id=str(job_id),
                err=str(exc),
            )
            return False

    async def wait_for_page_load_or_captcha(
        self,
        *,
        page: Page,
        timeout_ms: int = 15000,
        check_captcha: bool = True,
    ) -> str:
        """
        Wait for page to load or CAPTCHA to appear.
        
        Returns: "loaded" if page loaded, "captcha" if CAPTCHA detected.
        """
        try:
            # Start waiting for navigation with CAPTCHA check
            from playwright.async_api import TimeoutError as PlaywrightTimeoutError
            
            handler = CaptchaHitlHandler(
                self.settings,  # Assuming self.settings exists
                self.session,
                self.redis,
                page,
            )
            
            # Try to wait for load state
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
                
                # Check if CAPTCHA appeared after loading
                if check_captcha and await handler.detector.detect_captcha(page):
                    return "captcha"
                
                return "loaded"
            except PlaywrightTimeoutError:
                # Check if CAPTCHA appeared instead
                if check_captcha and await handler.detector.detect_captcha(page):
                    return "captcha"
                
                raise RuntimeError(f"Page load timeout after {timeout_ms}ms")
                
        except Exception as exc:
            logger.error(
                "handler.wait_for_page_error",
                err=str(exc),
            )
            raise


# Usage pattern in handlers:
# 
# class MyGstHandler(JobHandlerV2, HandlerCaptchaSupport):
#     async def run_with_context(self, job_id, payload_json, ctx):
#         # ... your handler code ...
#         
#         # After clicking login/submit:
#         captcha_handled = await self.handle_captcha_if_present(
#             session=ctx.session,
#             redis_client=...,  # Get from context if available
#             settings=ctx.settings,
#             job_id=job_id,
#             context_id=...,
#             page=page,
#             artifacts_dir=artifacts_dir,
#         )
#         
#         if captcha_handled:
#             # Continue with flow
#             pass
#         elif captcha_not_found:
#             # Continue normally
#             pass
#         else:
#             # CAPTCHA was found but failed to handle
#             raise RuntimeError("CAPTCHA handling failed")
