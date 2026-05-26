# Albert Makefile
# Local Docker Compose stack + per-service test/lint.

.PHONY: up down logs build ps test lint

up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f

build:
	docker compose build

ps:
	docker compose ps

test:
	cd backend && uv run pytest
	cd modelserver && uv run pytest
	cd guardrails && uv run pytest

lint:
	cd backend && uv run ruff check .
	cd modelserver && uv run ruff check .
	cd guardrails && uv run ruff check .
