from __future__ import annotations

import os

from gst_automation.celery_app.app import build_celery
from gst_automation.core.settings import Settings


celery_app = build_celery(Settings.load())


def main() -> None:
    # Expose celery app for `celery -A gst_automation.cli.worker worker ...`
    os.environ.setdefault("C_FORCE_ROOT", "false")
    globals()["celery_app"] = celery_app


if __name__ == "__main__":
    main()
