"""
INTEGRATION GUIDE: How to use Telegram HITL in your orchestration handlers

This guide shows how to integrate Telegram CAPTCHA handling into existing GST handlers.
"""

# EXAMPLE 1: Using CAPTCHA Detection in GstAuthSessionEngine
# Location: src/gst_automation/gst/auth_session.py (MODIFY EXISTING)

"""
# Add this import at the top:
from gst_automation.gst.captcha_handler import CaptchaHitlHandler

# In the run() method of GstAuthSessionEngine, add CAPTCHA detection:

async def run(self, session, redis_client, *, job_id, context_id, page, artifacts_dir, payload_json):
    # ... existing auth code ...
    
    # After clicking login/submit button, check for CAPTCHA:
    import asyncio
    from pathlib import Path
    
    # Check if CAPTCHA appears (usually takes 1-2 seconds)
    await asyncio.sleep(2)
    
    captcha_handler = CaptchaHitlHandler(
        settings=self.settings,
        session=session,
        redis_client=redis_client,
        page=page,
    )
    
    # Check if CAPTCHA is visible
    detector = captcha_handler.detector
    if await detector.detect_captcha(page):
        # CAPTCHA detected! Use Telegram HITL
        
        # Get client info for context
        job = await session.get(Job, job_id)
        client = await session.get(Client, job.client_id) if job.client_id else None
        client_name = client.display_name if client else "Unknown"
        gstin = client.gstin if client else "UNKNOWN"
        
        # Create checkpoint for this CAPTCHA request
        checkpoint = OperatorCheckpoint(
            job_id=job_id,
            context_id=context_id,
            kind="captcha",
            status="pending",
            instructions="Operator to provide CAPTCHA text",
            details_json=json.dumps({
                "client_name": client_name,
                "gstin": gstin,
                "page_url": page.url,
            }),
        )
        session.add(checkpoint)
        await session.flush()
        
        # Handle CAPTCHA
        success = await captcha_handler.handle_captcha(
            checkpoint_id=checkpoint.id,
            job_id=job_id,
            client_display_name=client_name,
            gstin=gstin,
            artifacts_dir=Path(artifacts_dir),
        )
        
        if success:
            # CAPTCHA was filled and login attempted
            checkpoint.status = "approved"
            checkpoint.resolved_at = datetime.now(UTC)
            await session.commit()
            # Continue with rest of flow
        else:
            # CAPTCHA failed - mark checkpoint as rejected
            checkpoint.status = "rejected"
            checkpoint.resolved_at = datetime.now(UTC)
            await session.commit()
            raise RuntimeError("CAPTCHA handling failed - operator timeout or invalid response")
    
    # ... continue with rest of auth flow ...
"""

# EXAMPLE 2: Using Telegram in a GST observation session
# Location: src/gst_automation/gst/observation.py (ALREADY INTEGRATED)

"""
from gst_automation.gst.captcha_handler import CaptchaHitlHandler

# Within GstObservationEngine.run():
while deadline_not_reached:
    # Your observation code...
    
    # Check for CAPTCHA during observation
    captcha_handler = CaptchaHitlHandler(settings, session, redis_client, page)
    if await captcha_handler.detector.detect_captcha(page):
        checkpoint = OperatorCheckpoint(
            job_id=job_id,
            context_id=context_id,
            kind="gst_observation_captcha",
            status="pending",
        )
        session.add(checkpoint)
        await session.flush()
        
        success = await captcha_handler.handle_captcha(...)
        if not success:
            # Handle failure
            pass
"""

# EXAMPLE 3: Setting up operator user (via Python REPL or script)

"""
import asyncio
from gst_automation.core.settings import Settings
from gst_automation.db.session import Db
from gst_automation.telegram_bot.service import TelegramUserService

async def setup_operator():
    settings = Settings.load()
    db = Db(settings.database_url)
    
    async with db.session() as session:
        user_service = TelegramUserService(session)
        
        # Register operator
        # Get telegram_user_id from /start command message
        user_info = await user_service.register_user(
            telegram_user_id=123456789,  # From Telegram /start
            telegram_chat_id=123456789,  # Same as user_id for personal chat
            telegram_username="operator_john",
            telegram_first_name="John",
            role="operator",
        )
        
        await session.commit()
        print(f"Registered: {user_info}")

asyncio.run(setup_operator())
"""

# EXAMPLE 4: Checking audit log

"""
async def check_audit():
    settings = Settings.load()
    db = Db(settings.database_url)
    
    async with db.session() as session:
        audit_service = TelegramAuditService(session)
        
        actions = await audit_service.get_user_actions(
            telegram_user_id=123456789,
            action_type="captcha_response_submitted",
            limit=10,
        )
        
        for action in actions:
            print(f"{action.created_at}: {action.action} - {action.details_json}")
"""

# EXAMPLE 5: Environment setup (.env file)

"""
# Add to .env for Telegram integration:

TELEGRAM_BOT_TOKEN=<token-from-botfather>
TELEGRAM_WEBHOOK_URL=  # Leave empty for long polling
TELEGRAM_POLLING_TIMEOUT_SECONDS=30
TELEGRAM_CAPTCHA_TIMEOUT_SECONDS=600
TELEGRAM_REMINDER_HOUR=9
TELEGRAM_REMINDER_MINUTE=0
TELEGRAM_REMINDER_TIMEZONE=Asia/Calcutta
"""

# EXAMPLE 6: Testing the full flow locally

"""
# 1. Start Celery worker with Telegram tasks
celery -A gst_automation.celery_app.celery worker -Q downloads,monitoring -l debug

# 2. Start Celery Beat (for morning reminders)
celery -A gst_automation.celery_app.celery beat -l debug

# 3. Manually trigger reminder test
from gst_automation.celery_app.tasks.telegram import send_morning_reminder
send_morning_reminder.delay()

# 4. In Telegram, operator gets message and clicks YES START
# 5. Monitor logs for "telegram.reminder_sent" and "telegram.action_enqueued"
"""
