FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
  && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md LICENSE /app/
COPY src /app/src
COPY alembic /app/alembic
COPY alembic.ini /app/alembic.ini

RUN pip install --no-cache-dir -U pip setuptools wheel \
  && pip install --no-cache-dir .

# Optional: bake Playwright browsers into the image at build-time.
# Use `--build-arg INSTALL_PLAYWRIGHT_BROWSERS=1` in CI where network access is available.
ARG INSTALL_PLAYWRIGHT_BROWSERS=0
RUN if [ "$INSTALL_PLAYWRIGHT_BROWSERS" = "1" ]; then python -m playwright install --with-deps chromium; fi

EXPOSE 8000

CMD ["python", "-m", "gst_automation.cli.api"]
