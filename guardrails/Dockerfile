# syntax=docker/dockerfile:1
# Multi-stage: the builder has a C++ toolchain (annoy, a transitive nemoguardrails
# dep, has no cp312 wheel and compiles from sdist); the runtime stays slim and
# never ships g++.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

RUN apt-get update \
    && apt-get install -y --no-install-recommends g++ \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# ---- runtime ----
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

ENV PATH="/app/.venv/bin:$PATH" \
    HF_HUB_OFFLINE=1 \
    GUARDRAILS_REQUIRE_NEMO=1

# Pre-built virtualenv from the builder (no compiler in the runtime image).
COPY --from=builder /app/.venv /app/.venv

# NeMo Guardrails config (tenant topical rails) + application code.
COPY config ./config
COPY app ./app

EXPOSE 8010

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8010"]
