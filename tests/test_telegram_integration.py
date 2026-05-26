"""Tests for Telegram bot integration."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gst_automation.telegram_bot.client import TelegramClient, OperatorAction, TelegramConfig
from gst_automation.telegram_bot.service import TelegramUserService, TelegramMessageService, TelegramAuditService
from gst_automation.telegram_bot.scheduler import TelegramReminderService, TelegramCaptchaService
from gst_automation.gst.captcha_handler import CaptchaDetector, CaptchaHitlHandler
from gst_automation.db.models.telegram import TelegramUser, TelegramMessage, TelegramAudit


class FakeRedis:
    """Mock Redis for testing."""

    def __init__(self):
        self._data: dict[str, list[str]] = {}

    async def rpush(self, key: str, value: str) -> int:
        self._data.setdefault(key, []).append(value)
        return len(self._data[key])

    async def blpop(self, key: str, timeout: int = 0):  # type: ignore
        items = self._data.get(key, [])
        if items:
            value = items.pop(0)
            return (key, value)
        return None

    async def expire(self, key: str, seconds: int) -> bool:
        return True

    async def close(self) -> None:
        pass


class FakeSettings:
    """Mock Settings for testing."""

    telegram_bot_token = "test_token_12345"
    telegram_webhook_url = None
    telegram_polling_timeout_seconds = 30
    telegram_image_upload_timeout_seconds = 60
    telegram_captcha_timeout_seconds = 600
    telegram_reminder_hour = 9
    telegram_reminder_minute = 0
    telegram_reminder_timezone = "Asia/Calcutta"


@pytest.mark.asyncio
async def test_telegram_client_send_message():
    """Test TelegramClient.send_message()."""
    settings = FakeSettings()
    redis_client = FakeRedis()

    with patch("gst_automation.telegram_bot.client.Bot") as mock_bot_class:
        mock_bot = AsyncMock()
        mock_bot_class.return_value = mock_bot
        mock_msg = MagicMock()
        mock_msg.message_id = 12345
        mock_bot.send_message.return_value = mock_msg

        client = TelegramClient(settings, redis_client)  # type: ignore
        msg_id = await client.send_message(
            telegram_user_id=999,
            text="Test message",
            buttons=[("Yes", "btn:yes"), ("No", "btn:no")],
        )

        assert msg_id == 12345
        mock_bot.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_operator_action_enqueue_dequeue():
    """Test TelegramClient action queue functionality."""
    settings = FakeSettings()
    redis_client = FakeRedis()

    with patch("gst_automation.telegram_bot.client.Bot"):
        client = TelegramClient(settings, redis_client)  # type: ignore
        checkpoint_id = uuid.uuid4()

        # Enqueue action
        action = OperatorAction(
            kind="captcha_reply",
            checkpoint_id=checkpoint_id,
            value="ABC123",
        )
        success = await client.enqueue_operator_action(checkpoint_id=checkpoint_id, action=action)
        assert success is True

        # Dequeue action
        retrieved = await client.pop_operator_action(checkpoint_id=checkpoint_id, timeout_seconds=1)
        assert retrieved is not None
        assert retrieved.kind == "captcha_reply"
        assert retrieved.value == "ABC123"


@pytest.mark.asyncio
async def test_telegram_user_service_register():
    """Test TelegramUserService user registration."""
    session = AsyncMock()
    session.execute = AsyncMock()
    session.flush = AsyncMock()

    service = TelegramUserService(session)

    # Mock the execute to return None (new user)
    from sqlalchemy import select

    async def mock_execute(query):
        result = AsyncMock()
        result.scalar_one_or_none = AsyncMock(return_value=None)
        return result

    session.execute = mock_execute

    user_info = await service.register_user(
        telegram_user_id=999,
        telegram_chat_id=999,
        telegram_username="testuser",
        telegram_first_name="Test",
    )

    assert user_info.telegram_user_id == 999
    assert user_info.telegram_username == "testuser"
    assert user_info.status == "active"


@pytest.mark.asyncio
async def test_operator_action_json_serialization():
    """Test that OperatorAction serializes/deserializes correctly."""
    checkpoint_id = uuid.uuid4()
    action = OperatorAction(
        kind="captcha_reply",
        checkpoint_id=checkpoint_id,
        value="XYZ789",
        timestamp=datetime.now(UTC),
    )

    # Simulate JSON serialization (as done in enqueue_operator_action)
    payload = json.dumps(
        {
            "kind": action.kind,
            "checkpoint_id": str(action.checkpoint_id),
            "value": action.value,
            "timestamp": action.timestamp.isoformat(),
        }
    )

    # Simulate JSON deserialization (as done in pop_operator_action)
    data = json.loads(payload)
    restored = OperatorAction(
        kind=data["kind"],
        checkpoint_id=uuid.UUID(data["checkpoint_id"]),
        value=data["value"],
        timestamp=datetime.fromisoformat(data["timestamp"]),
    )

    assert restored.kind == action.kind
    assert restored.checkpoint_id == action.checkpoint_id
    assert restored.value == action.value


@pytest.mark.asyncio
async def test_captcha_detector_with_mock_page():
    """Test CaptchaDetector with mocked Playwright page."""
    settings = FakeSettings()  # type: ignore
    detector = CaptchaDetector(settings)

    # Mock page
    mock_page = AsyncMock()
    mock_element = AsyncMock()
    mock_element.is_visible = AsyncMock(return_value=True)
    mock_page.locator = MagicMock(return_value=MagicMock(first=mock_element))

    # Test detection
    result = await detector.detect_captcha(mock_page)
    assert result is True


@pytest.mark.asyncio
async def test_captcha_detector_not_visible():
    """Test CaptchaDetector when CAPTCHA is not visible."""
    settings = FakeSettings()  # type: ignore
    detector = CaptchaDetector(settings)

    mock_page = AsyncMock()
    mock_element = AsyncMock()
    mock_element.is_visible = AsyncMock(return_value=False)
    mock_page.locator = MagicMock(return_value=MagicMock(first=mock_element))

    result = await detector.detect_captcha(mock_page)
    assert result is False


def test_telegram_config():
    """Test TelegramConfig initialization."""
    config = TelegramConfig(
        token="test_token",
        webhook_url="https://example.com/webhook",
        polling_timeout_seconds=30,
    )

    assert config.token == "test_token"
    assert config.webhook_url == "https://example.com/webhook"
    assert config.polling_timeout_seconds == 30


@pytest.mark.asyncio
async def test_telegram_message_service_log():
    """Test TelegramMessageService message logging."""
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()

    service = TelegramMessageService(session)
    checkpoint_id = uuid.uuid4()

    msg_id = await service.log_message(
        telegram_message_id=123,
        telegram_user_id=999,
        direction="send",
        message_type="text",
        content="Test message",
        checkpoint_id=checkpoint_id,
    )

    assert isinstance(msg_id, uuid.UUID)
    session.add.assert_called_once()


@pytest.mark.asyncio
async def test_audit_service_log_action():
    """Test TelegramAuditService action logging."""
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()

    service = TelegramAuditService(session)
    action_id = await service.log_action(
        telegram_user_id=999,
        action="captcha_response_submitted",
        details={"checkpoint_id": "abc123"},
    )

    assert isinstance(action_id, uuid.UUID)
    session.add.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
