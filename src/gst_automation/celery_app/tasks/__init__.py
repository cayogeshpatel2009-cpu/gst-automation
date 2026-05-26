"""Celery tasks (thin wrappers only).

Celery task registration happens at import time. Keep explicit imports here so
`gst_automation.celery_app.tasks` import deterministically registers all tasks.
"""

from gst_automation.celery_app.tasks import job_runner as _job_runner  # noqa: F401
from gst_automation.celery_app.tasks import maintenance as _maintenance  # noqa: F401
from gst_automation.celery_app.tasks import telegram as _telegram  # noqa: F401
