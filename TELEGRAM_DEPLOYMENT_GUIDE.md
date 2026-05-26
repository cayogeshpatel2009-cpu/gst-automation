# TELEGRAM INTEGRATION - DEPLOYMENT GUIDE

**Last Updated:** 2026-05-25  
**Status:** Ready for Testing/UAT

---

## QUICK START

### 1. Prerequisites

```bash
# Ensure Python 3.10+ environment
python --version  # Must be 3.10+

# Install aiogram dependency
pip install aiogram

# Verify Redis is running
redis-cli ping  # Should output PONG

# Verify PostgreSQL is running and accessible
psql -h localhost -U gst_automation -d gst_automation -c "SELECT 1"
```

### 2. Configure Environment (.env)

```bash
# Add to your .env file:

# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN=your_bot_token_from_botfather
TELEGRAM_API_KEY=
TELEGRAM_WEBHOOK_URL=
TELEGRAM_POLLING_TIMEOUT_SECONDS=30
TELEGRAM_IMAGE_UPLOAD_TIMEOUT_SECONDS=60
TELEGRAM_CAPTCHA_TIMEOUT_SECONDS=600

# Morning Reminder Schedule (IST/Calcutta timezone)
TELEGRAM_REMINDER_HOUR=9
TELEGRAM_REMINDER_MINUTE=0
TELEGRAM_REMINDER_TIMEZONE=Asia/Calcutta

# Other existing configs (unchanged)
DATABASE_URL=postgresql+asyncpg://...
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/2
```

### 3. Get Telegram Bot Token

1. Open Telegram and search for @BotFather
2. Send `/newbot` command
3. Follow prompts to create bot
4. Copy the HTTP API token (looks like `123456789:ABCdefGHIjklMNOpqrSTUVWxyzABC`)
5. Paste into .env as `TELEGRAM_BOT_TOKEN`

### 4. Run Database Migration

```bash
# This creates telegram_users, telegram_messages, telegram_audit tables
python -m gst_automation.cli.db upgrade
```

### 5. Register Operators

```bash
# Method A: Using the API
curl -X POST http://localhost:8000/telegram/operators/register \
  -H "Content-Type: application/json" \
  -d '{
    "telegram_user_id": 123456789,
    "telegram_chat_id": 123456789,
    "telegram_username": "operator_john",
    "telegram_first_name": "John",
    "telegram_last_name": "Doe",
    "role": "operator"
  }'

# Method B: Using Python script
python -c "
import asyncio
from gst_automation.core.settings import Settings
from gst_automation.db.session import Db
from gst_automation.telegram_bot.service import TelegramUserService

async def register():
    settings = Settings.load()
    db = Db(settings.database_url)
    async with db.session() as session:
        svc = TelegramUserService(session)
        user = await svc.register_user(
            telegram_user_id=123456789,
            telegram_chat_id=123456789,
            telegram_username='operator_john',
            telegram_first_name='John'
        )
        await session.commit()
        print(f'Registered: {user}')

asyncio.run(register())
"
```

### 6. Start Services

```bash
# Terminal 1: FastAPI app
python -m uvicorn gst_automation.app.main:app --reload --host 0.0.0.0 --port 8000

# Terminal 2: Celery worker (with long polling for Telegram)
celery -A gst_automation.celery_app.celery worker -Q downloads,monitoring -l debug

# Terminal 3: Celery Beat (for scheduled reminders)
celery -A gst_automation.celery_app.celery beat -l debug
```

### 7. Verify Setup

```bash
# Check if Telegram bot is reachable
curl -X GET "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getMe"

# Check Telegram status endpoint
curl http://localhost:8000/telegram/status

# Check database tables exist
psql -h localhost -U gst_automation -d gst_automation -c \
  "SELECT * FROM telegram_users LIMIT 1;"

# Monitor Celery logs for "telegram.reminder_sent"
# Should appear at configured time (default 9:00 AM weekdays)
```

---

## MANUAL TESTING WORKFLOW

### Test 1: Morning Reminder

1. **Register yourself as operator** (see Step 5 above)
2. **Trigger reminder manually:**
   ```bash
   curl -X POST http://localhost:8000/telegram/operators/register \
     -H "Content-Type: application/json" \
     -d '{"telegram_user_id": YOUR_USER_ID, ...}'
   
   # Then trigger task:
   celery -A gst_automation.celery_app.celery call \
     gst_automation.celery_app.tasks.telegram.send_morning_reminder
   ```
3. **Check Telegram** - You should receive message with 3 buttons
4. **Click "✅ YES START"** - System should log the action
5. **Verify in database:**
   ```sql
   SELECT * FROM telegram_messages WHERE direction='send' 
     AND message_type='text' 
     ORDER BY created_at DESC LIMIT 1;
   ```

### Test 2: CAPTCHA Detection and Handling

1. **Start a GST job that will hit CAPTCHA**
2. **Monitor logs for "gst.captcha_detected"**
3. **Check if image was sent to Telegram** (should appear as photo)
4. **In Telegram, type CAPTCHA text and send**
5. **Monitor logs for:**
   - `"telegram.captcha_response_received"`
   - `"gst.captcha_inject_error"` or `"gst.captcha_resolved"`
6. **Verify CAPTCHA was filled and job continued**

### Test 3: Operator Management

```bash
# List all operators
curl http://localhost:8000/telegram/status

# Get specific operator
curl http://localhost:8000/telegram/operators/123456789

# Disable operator
curl -X POST http://localhost:8000/telegram/operators/123456789/disable

# View operator audit log
curl http://localhost:8000/telegram/operators/123456789/audit
```

---

## MONITORING AND LOGGING

### Key Log Patterns to Watch

```
# Success patterns:
telegram.reminder_sent - Morning reminder delivered
telegram.message_sent - Message successfully sent
telegram.action_enqueued - Operator action queued
gst.captcha_detected - CAPTCHA found on page
gst.captcha_image_captured - Screenshot taken
telegram.captcha_response_received - Operator replied
gst.captcha_resolved - CAPTCHA filled and submitted

# Error patterns:
telegram.reminder_no_operators - No operators registered
telegram.send_message_failed - Telegram API error
telegram.captcha_send_failed - Failed to send CAPTCHA image
gst.captcha_timeout - Operator didn't respond in time
gst.captcha_inject_error - Failed to fill CAPTCHA field
gst.captcha_submit_button_not_found - Couldn't click login
```

### Monitoring Commands

```bash
# Watch logs in real-time
tail -f logs/gst_automation.log | grep telegram

# Count CAPTCHA events today
grep "gst.captcha" logs/gst_automation.log | wc -l

# List all telegram actions
psql -h localhost -U gst_automation -d gst_automation -c \
  "SELECT action, COUNT(*) FROM telegram_audit GROUP BY action;"

# Check reminder delivery rate
psql -h localhost -U gst_automation -d gst_automation -c \
  "SELECT direction, COUNT(*) FROM telegram_messages 
   WHERE message_type='text' 
   AND created_at > NOW() - INTERVAL '1 day'
   GROUP BY direction;"
```

---

## TROUBLESHOOTING

### Problem: "No module named telegram_bot"

**Solution:**
```bash
# Ensure all new files are created and in correct location
ls -la src/gst_automation/telegram_bot/
# Should show: __init__.py, client.py, service.py, scheduler.py

# Verify Python can import
python -c "from gst_automation.telegram_bot import TelegramClient"
```

### Problem: "TELEGRAM_BOT_TOKEN not set"

**Solution:**
```bash
# Verify .env file exists and has token
cat .env | grep TELEGRAM_BOT_TOKEN

# If missing, add it:
echo "TELEGRAM_BOT_TOKEN=your_token" >> .env
```

### Problem: "Telegram API error: 404 Not Found"

**Solution:**
- Verify token is correct (check @BotFather)
- Ensure bot is enabled and not deleted
- Check internet connectivity

### Problem: "CAPTCHA detection not working"

**Solution:**
```bash
# Check CAPTCHA selectors match your environment
# Default selectors in captcha_handler.py:
#   img[src*='captcha']
#   div#captcha-image img
#   iframe[src*='captcha']

# Test selector manually:
python -c "
from playwright.async_api import async_playwright
import asyncio

async def test():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto('https://services.gst.gov.in/services/login')
        # Find actual CAPTCHA element
        elements = await page.locator('*:has-text(\"CAPTCHA\")').all()
        for el in elements:
            tag = await el.evaluate('(el) => el.tagName')
            print(f'Found: {tag}')
"
```

### Problem: "Operator not receiving messages"

**Solution:**
```bash
# Check if operator is registered
psql -h localhost -U gst_automation -d gst_automation -c \
  "SELECT * FROM telegram_users WHERE telegram_user_id=YOUR_ID;"

# Check if status is 'active' (not 'disabled')
# Check Telegram user ID is correct (should match /start message)
# Verify redis connectivity
redis-cli ping
```

---

## PRODUCTION CHECKLIST

- [ ] TELEGRAM_BOT_TOKEN set in production environment
- [ ] All .env variables configured
- [ ] Database migration 0016 applied (`alembic_version` table shows `0016_telegram_bot_integration`)
- [ ] All operators registered via API
- [ ] Redis replicated/backed up
- [ ] Celery Beat running in production (not just development)
- [ ] Long polling timeout set appropriately (30 seconds is default)
- [ ] CAPTCHA selectors verified for production GST environment
- [ ] Telegram bot is member of any required Telegram supergroups (if needed)
- [ ] Monitoring/alerting set up for telegram.* log patterns
- [ ] Backup strategy for telegram_messages table (audit trail)
- [ ] Rate limiting configured for Telegram API (default: 30 messages/second)

---

## PERFORMANCE TUNING

### Reduce Long Polling Latency

```python
# In .env, reduce polling timeout (faster response, higher CPU)
TELEGRAM_POLLING_TIMEOUT_SECONDS=10  # Default is 30
```

### Increase CAPTCHA Timeout for Slow Operators

```python
# In .env, allow more time for operator response
TELEGRAM_CAPTCHA_TIMEOUT_SECONDS=900  # 15 minutes (default is 10)
```

### Batch Morning Reminders (if > 100 operators)

```python
# Split into groups and stagger sending
# Modify TelegramReminderService.send_morning_reminder() to batch by 50
```

---

## SECURITY NOTES

### Never Log Credentials

- CAPTCHA text is NOT logged (only length is logged)
- Credentials are NOT stored in Telegram messages
- GSTIN is masked in displayed messages

### Telegram User Authorization

- Only registered operators can trigger actions
- Allowlist stored in database (not hardcoded)
- All actions audited with timestamp and user

### Database Backups

```bash
# Regular backups should include:
pg_dump gst_automation > backup.sql

# Specifically protect:
# - telegram_users (operator credentials/IDs)
# - telegram_audit (access log)
```

---

## NEXT STEPS AFTER TESTING

1. **Phase 4**: Integrate CAPTCHA response routing with job context
2. **Phase 5**: Add OTP support (similar to CAPTCHA)
3. **Phase 6**: Implement persistent browser workers
4. **Phase 7**: Add real-time dashboard
5. **Phase 8**: Enhanced failure recovery

---

## CONTACT & SUPPORT

For issues:
1. Check logs: `grep telegram logs/gst_automation.log`
2. Check database: `psql -d gst_automation -c "SELECT * FROM telegram_audit"`
3. Verify Redis: `redis-cli`
4. Test Telegram API: `curl https://api.telegram.org/botTOKEN/getMe`

---

**Deployment Date:** _________________  
**By:** _________________  
**Verification:** _________________
