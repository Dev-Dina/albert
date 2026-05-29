# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

# Install runtime dependencies first (cached unless lock changes)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Copy application code after dependencies
COPY app ./app

# Alembic migration files (so `alembic upgrade head` can run inside the container)
COPY alembic.ini ./
COPY alembic ./alembic

# Dev/ops scripts (e.g. seed_dev_user.py) so they can run via
# `docker compose exec backend python scripts/<script>.py`.
COPY scripts ./scripts

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
