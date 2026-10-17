UV ?= $(if $(wildcard .tools/bin/uv),.tools/bin/uv,uv)
PYTHON ?= python3

.PHONY: dev dev-ui example init install migrate api worker web check format api-types up down logs

dev:
	$(PYTHON) scripts/dev.py

dev-ui:
	$(PYTHON) scripts/dev.py --no-worker

example:
	$(UV) run python -m backend.examples

init:
	$(PYTHON) scripts/init_env.py

install:
	$(UV) sync --frozen
	npm --prefix frontend ci

migrate:
	$(UV) run alembic upgrade head

api:
	$(UV) run uvicorn backend.api.main:app --reload --host 127.0.0.1 --port 8000

worker:
	$(UV) run python -m backend.worker

web:
	npm --prefix frontend run dev

check:
	$(UV) run ruff check backend scripts tests
	$(UV) run ruff format --check backend scripts tests
	$(UV) run pytest
	npm --prefix frontend run format:check
	npm --prefix frontend test
	npm --prefix frontend run build

format:
	$(UV) run ruff check backend scripts tests --fix
	$(UV) run ruff format backend scripts tests
	npm --prefix frontend run format

api-types:
	$(UV) run python scripts/export_openapi.py
	npm --prefix frontend run api:types

up:
	docker compose up --build -d --wait

down:
	docker compose down

logs:
	docker compose logs -f api worker
