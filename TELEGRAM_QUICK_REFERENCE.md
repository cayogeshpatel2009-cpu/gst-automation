# TELEGRAM INTEGRATION - QUICK REFERENCE

## Module Imports

```python
# Core client
from gst_automation.telegram_bot import (
    TelegramClient,
    TelegramConfig,
    OperatorAction,
)

# Services
from gst_automation.telegram_bot.service import (
    TelegramUserService,
    TelegramMessageService,
    TelegramAuditService,
)

# Schedulers
from gst_automation.telegram_bot.scheduler import (
    TelegramReminderService,
    TelegramCaptchaService,
)

# CAPTCHA Handler
from gst_automation.gst.captcha_handler import (
    CaptchaDetector,
    CaptchaHitlHandler,
)

# Handler Mixin
from gst_automation.orchestration.handlers.captcha_support import (
    HandlerCaptchaSupport,
)
```

## Environment Setup

```bash
# 1. Get bot token from @BotFather
# 2. Add to .env:
TELEGRAM_BOT_TOKEN=123456:ABCdef...
TELEGRAM_REMINDER_HOUR=9
TELEGRAM_REMINDER_MINUTE=0

# 3. Run migration
python -m gst_automation.cli.db upgrade

# 4. Register operator
curl -X POST http://localhost:8000/telegram/operators/register \
  -H "Content-Type: application/json" \
  -d '{
    "telegram_user_id": YOUR_ID,
    "telegram_chat_id": YOUR_ID,
    "telegram_username": "YOUR_HANDLE"
  }'
```

## Common Tasks

### Send Message to Operator
```python
from gst_automation.telegram_bot import TelegramClient
from gst_automation.core.settings import Settings

settings = Settings.load()
client = TelegramClient(settings, redis_client)

msg_id = await client.send_message(
    telegram_user_id=123456789,
    text="Hello operator!",
    buttons=[("OK", "btn:ok"), ("Skip", "btn:skip")]
)
```

### Register Operator (Python)
```python
from gst_automation.telegram_bot.service import TelegramUserService

svc = TelegramUserService(session)
user = await svc.register_user(
    telegram_user_id=123456789,
    telegram_chat_id=123456789,
    telegram_username="operator_john"
)
```

### Check if User is Allowed
```python
svc = TelegramUserService(session)
allowed = await svc.is_allowed(telegram_user_id=123456789)
if not allowed:
    # User not registered or disabled
    pass
```

### Handle CAPTCHA in Handler
```python
from gst_automation.orchestration.handlers.captcha_support import HandlerCaptchaSupport

class MyHandler(JobHandlerV2, HandlerCaptchaSupport):
    async def run_with_context(self, job_id, payload_json, ctx):
        # ... your code ...
        
        # Try to handle CAPTCHA if it appears
        success = await self.handle_captcha_if_present(
            session=ctx.session,
            redis_client=redis_client,
            settings=ctx.settings,
            job_id=job_id,
            context_id=context_id,
            page=page,
            artifacts_dir=artifacts_dir,
        )
        
        if not success and await detector.detect_captcha(page):
            # CAPTCHA was found but handling failed
            raise RuntimeError("CAPTCHA handling failed")
```

### Log Audit Event
```python
from gst_automation.telegram_bot.service import TelegramAuditService

audit_svc = TelegramAuditService(session)
await audit_svc.log_action(
    telegram_user_id=123456789,
    action="my_action",
    details={"key": "value"}
)
```

## Database Queries

### Check registered operators
```sql
SELECT COUNT(*) FROM telegram_users WHERE status = 'active';
```

### View recent messages
```sql
SELECT created_at, direction, message_type, checkpoint_id 
FROM telegram_messages 
ORDER BY created_at DESC 
LIMIT 10;
```

### View audit trail
```sql
SELECT created_at, action, details_json 
FROM telegram_audit 
WHERE telegram_user_id = 123456789
ORDER BY created_at DESC;
```

### Find CAPTCHA checkpoints
```sql
SELECT job_id, status, created_at 
FROM operator_checkpoints 
WHERE kind = 'telegram_captcha' 
ORDER BY created_at DESC 
LIMIT 10;
```

## API Endpoints Quick Reference

```bash
# Register operator
curl -X POST http://localhost:8000/telegram/operators/register \
  -H "Content-Type: application/json" \
  -d '{...}'

# Get operator info
curl http://localhost:8000/telegram/operators/123456789

# Get system status
curl http://localhost:8000/telegram/status

# Disable operator
curl -X POST http://localhost:8000/telegram/operators/123456789/disable

# View audit log
curl http://localhost:8000/telegram/operators/123456789/audit
```

## Troubleshooting Commands

```bash
# Test Telegram API
curl -X GET "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getMe"

# Check if bot is reachable
python -c "from gst_automation.telegram_bot import TelegramClient; print('OK')"

# Test Redis queue
redis-cli KEYS "*telegram*"
redis-cli LRANGE "telegram:action:checkpoint-id" 0 -1

# Check Celery Beat tasks
celery -A gst_automation.celery_app.celery inspect active_queues

# View logs for Telegram events
tail -f logs/gst_automation.log | grep -i telegram
```

## Key Classes

### TelegramClient
- `send_message(telegram_user_id, text, buttons)`
- `send_photo(telegram_user_id, photo_path, caption, buttons)`
- `enqueue_operator_action(checkpoint_id, action)`
- `pop_operator_action(checkpoint_id, timeout_seconds)`

### TelegramUserService
- `register_user(telegram_user_id, telegram_chat_id, ...)`
- `get_user(telegram_user_id)`
- `is_allowed(telegram_user_id)`
- `list_operators()`
- `disable_user(telegram_user_id)`
- `update_last_seen(telegram_user_id)`

### CaptchaDetector
- `detect_captcha(page)`
- `capture_captcha_image(page, artifacts_dir)`
- `capture_full_page_screenshot(page, artifacts_dir)`

### CaptchaHitlHandler
- `handle_captcha(checkpoint_id, job_id, client_name, gstin, artifacts_dir)`

## Common Error Handling

```python
try:
    await client.send_message(user_id, "text")
except Exception as e:
    logger.error("telegram.send_message_failed", err=str(e))
    # Message send failed - may need retry
```

## Configuration Validation

```python
# Check if Telegram is configured
settings = Settings.load()
if not settings.telegram_bot_token:
    logger.warning("Telegram bot is not configured")
    # Fall back to manual handling
```

## Performance Tips

1. **Reduce polling latency:** `TELEGRAM_POLLING_TIMEOUT_SECONDS=10` (default 30)
2. **Increase CAPTCHA timeout:** `TELEGRAM_CAPTCHA_TIMEOUT_SECONDS=900` for slow operators
3. **Batch operators:** Split large operator lists into groups for reminders
4. **Cache user list:** Call `list_operators()` once per broadcast

## Links

- **Full Status:** [TELEGRAM_FINAL_SUMMARY.md](TELEGRAM_FINAL_SUMMARY.md)
- **Deployment:** [TELEGRAM_DEPLOYMENT_GUIDE.md](TELEGRAM_DEPLOYMENT_GUIDE.md)
- **Integration:** [TELEGRAM_INTEGRATION_GUIDE.md](TELEGRAM_INTEGRATION_GUIDE.md)
- **Tests:** [tests/test_telegram_integration.py](tests/test_telegram_integration.py)

---

Last Updated: 2026-05-25
