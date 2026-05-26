from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import Field
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from gst_automation.core.exceptions import ConfigurationError
from gst_automation.core.env_bootstrap import resolve_env_file
from gst_automation.core.dotenv_loader import ensure_dotenv_loaded


Environment = Literal["local", "staging", "production"]
LogFormat = Literal["json", "console"]
VaultProvider = Literal["keyring", "file"]


class Settings(BaseSettings):
    """Typed configuration loaded from environment and optional `.env` file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Environment = Field(default="local", validation_alias="ENVIRONMENT")
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    log_format: LogFormat = Field(default="json", validation_alias="LOG_FORMAT")

    database_url: str = Field(validation_alias="DATABASE_URL")
    database_migration_url: str | None = Field(
        default=None, validation_alias="DATABASE_MIGRATION_URL"
    )
    redis_url: str = Field(default="redis://localhost:6379/0", validation_alias="REDIS_URL")

    celery_broker_url: str = Field(
        default="redis://localhost:6379/1", validation_alias="CELERY_BROKER_URL"
    )
    celery_result_backend: str = Field(
        default="redis://localhost:6379/2", validation_alias="CELERY_RESULT_BACKEND"
    )
    celery_prefetch_multiplier: int = Field(
        default=1, validation_alias="CELERY_PREFETCH_MULTIPLIER"
    )
    celery_acks_late: bool = Field(default=True, validation_alias="CELERY_ACKS_LATE")
    celery_task_time_limit_seconds: int = Field(
        default=900, validation_alias="CELERY_TASK_TIME_LIMIT_SECONDS"
    )
    celery_task_soft_time_limit_seconds: int = Field(
        default=840, validation_alias="CELERY_TASK_SOFT_TIME_LIMIT_SECONDS"
    )

    # Orchestration hardening
    scheduler_max_enqueue_per_tick: int = Field(default=200, validation_alias="SCHEDULER_MAX_ENQUEUE_PER_TICK")
    scheduler_per_client_concurrency: int = Field(default=1, validation_alias="SCHEDULER_PER_CLIENT_CONCURRENCY")
    backpressure_queue_depth_limit: int = Field(default=5000, validation_alias="BACKPRESSURE_QUEUE_DEPTH_LIMIT")
    backpressure_pause_low_priority: bool = Field(
        default=True, validation_alias="BACKPRESSURE_PAUSE_LOW_PRIORITY"
    )

    # Browser infrastructure
    browser_max_browsers_per_worker: int = Field(
        default=2, validation_alias="BROWSER_MAX_BROWSERS_PER_WORKER"
    )
    browser_max_contexts_per_browser: int = Field(
        default=8, validation_alias="BROWSER_MAX_CONTEXTS_PER_BROWSER"
    )
    browser_browser_ttl_seconds: int = Field(
        default=3600, validation_alias="BROWSER_BROWSER_TTL_SECONDS"
    )
    browser_max_rss_mb: int = Field(default=1200, validation_alias="BROWSER_MAX_RSS_MB")
    browser_headless: bool = Field(default=True, validation_alias="BROWSER_HEADLESS")
    browser_locale: str = Field(default="en-IN", validation_alias="BROWSER_LOCALE")
    browser_timezone: str = Field(default="Asia/Calcutta", validation_alias="BROWSER_TIMEZONE")
    browser_viewport_width: int = Field(default=1366, validation_alias="BROWSER_VIEWPORT_WIDTH")
    browser_viewport_height: int = Field(default=768, validation_alias="BROWSER_VIEWPORT_HEIGHT")
    browser_navigation_timeout_ms: int = Field(default=60000, validation_alias="BROWSER_NAVIGATION_TIMEOUT_MS")
    browser_action_timeout_ms: int = Field(default=30000, validation_alias="BROWSER_ACTION_TIMEOUT_MS")
    browser_download_timeout_seconds: int = Field(
        default=300, validation_alias="BROWSER_DOWNLOAD_TIMEOUT_SECONDS"
    )
    browser_artifacts_dir: Path = Field(
        default=Path("./data/artifacts"), validation_alias="BROWSER_ARTIFACTS_DIR"
    )

    # Real-site validation (safe allowlist; no GST automation).
    real_site_allowlist: str = Field(
        default="https://example.com,https://httpbin.org,https://playwright.dev,https://developer.mozilla.org",
        validation_alias="REAL_SITE_ALLOWLIST",
    )

    # GST readiness probing (safe, read-only).
    gst_probe_allowlist: str = Field(default="", validation_alias="GST_PROBE_ALLOWLIST")
    gst_probe_base_url: str = Field(default="", validation_alias="GST_PROBE_BASE_URL")

    # SMTP (optional) for delivery; password should live in Vault and be referenced via secret id.
    smtp_host: str | None = Field(default=None, validation_alias="SMTP_HOST")
    smtp_port: int = Field(default=587, validation_alias="SMTP_PORT")
    smtp_user: str | None = Field(default=None, validation_alias="SMTP_USER")
    smtp_password_secret: str | None = Field(default=None, validation_alias="SMTP_PASSWORD_SECRET")  # e.g. "smtp:default"
    smtp_from: str | None = Field(default=None, validation_alias="SMTP_FROM")

    data_dir: Path = Field(default=Path("./data"), validation_alias="DATA_DIR")
    archive_dir: Path = Field(default=Path("./data/archive"), validation_alias="ARCHIVE_DIR")
    work_dir: Path = Field(default=Path("./data/work"), validation_alias="WORK_DIR")

    vault_provider: VaultProvider = Field(default="keyring", validation_alias="VAULT_PROVIDER")
    vault_master_key: str | None = Field(default=None, validation_alias="VAULT_MASTER_KEY")

    archive_read_only: bool = Field(default=False, validation_alias="ARCHIVE_READ_ONLY")

    # Telegram bot integration
    telegram_enabled: bool = Field(default=False, validation_alias="TELEGRAM_ENABLED")
    telegram_polling_enabled: bool = Field(default=False, validation_alias="TELEGRAM_POLLING_ENABLED")
    telegram_bot_token: str | None = Field(default=None, validation_alias="TELEGRAM_BOT_TOKEN")
    telegram_allowed_user_ids: list[int] = Field(default_factory=list, validation_alias="TELEGRAM_ALLOWED_USER_IDS")
    telegram_api_key: str | None = Field(default=None, validation_alias="TELEGRAM_API_KEY")
    telegram_webhook_url: str | None = Field(default=None, validation_alias="TELEGRAM_WEBHOOK_URL")
    telegram_polling_timeout_seconds: int = Field(default=30, validation_alias="TELEGRAM_POLLING_TIMEOUT_SECONDS")
    telegram_image_upload_timeout_seconds: int = Field(
        default=60, validation_alias="TELEGRAM_IMAGE_UPLOAD_TIMEOUT_SECONDS"
    )
    telegram_captcha_timeout_seconds: int = Field(
        default=600, validation_alias="TELEGRAM_CAPTCHA_TIMEOUT_SECONDS"
    )
    telegram_reminder_hour: int = Field(default=9, validation_alias="TELEGRAM_REMINDER_HOUR")
    telegram_reminder_minute: int = Field(default=0, validation_alias="TELEGRAM_REMINDER_MINUTE")
    telegram_reminder_timezone: str = Field(default="Asia/Calcutta", validation_alias="TELEGRAM_REMINDER_TIMEZONE")

    @field_validator("telegram_allowed_user_ids", mode="before")
    @classmethod
    def _parse_allowed_user_ids(cls, v: Any) -> list[int]:
        if v is None:
            return []
        if isinstance(v, list):
            out: list[int] = []
            for x in v:
                try:
                    out.append(int(x))
                except Exception:
                    continue
            return out
        if isinstance(v, str):
            s = v.strip()
            if not s:
                return []
            parts = [p.strip() for p in s.replace(";", ",").split(",")]
            out2: list[int] = []
            for p in parts:
                if not p:
                    continue
                try:
                    out2.append(int(p))
                except Exception:
                    continue
            return out2
        try:
            return [int(v)]
        except Exception:
            return []

    @classmethod
    @lru_cache(maxsize=1)
    def load(cls) -> "Settings":
        try:
            # Ensure `.env` is applied to os.environ for CLI/migration contexts that still read env vars.
            ensure_dotenv_loaded()
            env_file = resolve_env_file()
            if env_file is not None:
                return cls(_env_file=env_file)
            return cls()
        except Exception as exc:  # noqa: BLE001
            raise ConfigurationError(f"Invalid settings: {exc}") from exc
