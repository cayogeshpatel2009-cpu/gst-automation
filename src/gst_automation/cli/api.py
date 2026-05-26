from __future__ import annotations

import uvicorn

from gst_automation.app.main import build_app


def main() -> None:
    app = build_app()
    uvicorn.run(app, host="0.0.0.0", port=8000, log_config=None)


if __name__ == "__main__":
    main()

