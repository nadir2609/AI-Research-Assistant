# AI Research Assistant - Dockerfile for containerized deployment
# Default: offline demo (no API keys, no network).
# Override CMD for CLI or HTTP API (see README / comments below).

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Runtime + test deps (offline pytest in container; see requirements-test.txt)
COPY requirements-runtime.txt requirements-test.txt ./
RUN pip install --upgrade pip \
    && pip install -r requirements-runtime.txt -r requirements-test.txt

# Application code (ai/ is provided unmodified; SE layer in src/)
COPY ai/ ./ai/
COPY src/ ./src/
COPY tests/ ./tests/
COPY docker/ ./docker/
COPY data/ ./data/
COPY demo_ai.py researcher.py check_db.py pytest.ini ./

# Writable cache directory; entrypoint waits for Postgres when DATABASE_URL is set
RUN mkdir -p /app/.cache \
    && chmod +x /app/docker/entrypoint.sh \
    && adduser --disabled-password --gecos "" appuser \
    && chown -R appuser:appuser /app

USER appuser
ENTRYPOINT ["sh", "/app/docker/entrypoint.sh"]

# Standalone image (no Compose): offline demo. Prefer: docker compose up --build
CMD ["python", "demo_ai.py", "--offline", "--limit", "1"]
