from __future__ import annotations

from functools import lru_cache

from celery import Celery

from gst_automation.celery_app.app import build_celery
from gst_automation.core.settings import Settings


@lru_cache(maxsize=1)
def get_celery() -> Celery:
    return build_celery(Settings.load())

