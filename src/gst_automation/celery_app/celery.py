from __future__ import annotations

from gst_automation.celery_app.app import build_celery
from gst_automation.core.settings import Settings

celery_app = build_celery(Settings.load())

