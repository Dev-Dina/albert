# Albert Makefile
# Local Docker Compose stack + per-service test/lint.

.PHONY: up down logs build ps test lint widget-build admin smoke eval

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

# Widget bundle build (esbuild). Outputs widget/dist/widget.js + bundle-<sha>.js.
widget-build:
	cd widget && npm install && node esbuild.config.mjs

# Run the Streamlit admin app locally (outside of Docker).
admin:
	cd admin && uv run streamlit run app/main.py --server.port 8501 --server.address 0.0.0.0

# Bring the stack up and verify backend/modelserver/guardrails health.
smoke:
	bash scripts/smoke_test.sh

# Run all CI eval gate harnesses locally.
eval:
	python -m evals.common.validate_thresholds
	python -m evals.classifier.run
	python -m evals.tool_selection.run
	python -m evals.rag.run
	python -m evals.redteam_cross_tenant.run
	python -m evals.redaction.run
