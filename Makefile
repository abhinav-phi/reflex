# Reflex — developer commands (TechSpec §16: `make up && make seed && make demo`)
PY ?= python
PIP ?= pip

.PHONY: help up down migrate seed demo dev-install test test-unit lint type eval-smoke reproduce web-install web-dev web-build ci

help:
	@echo "make up           - docker compose (postgres/redis/api/workers)"
	@echo "make migrate      - apply Alembic migrations"
	@echo "make seed         - idempotent seed (users, merchant, policy v1, corpora)"
	@echo "make demo         - start demo slice (214 eps / Rs 2,41,000, seed demo-7, x100)"
	@echo "make dev-install  - editable install with dev tools"
	@echo "make test         - full backend suite"
	@echo "make lint / type  - ruff / mypy"
	@echo "make eval-smoke   - tiny in-process eval sanity run"
	@echo "make reproduce    - official pre-registered protocol via eval/reproduce.sh"

dev-install:
	$(PIP) install -e ".[dev]"

up:
	docker compose up -d --build
	$(MAKE) migrate
	$(MAKE) seed

down:
	docker compose down

migrate:
	$(PY) -m alembic upgrade head

seed:
	$(PY) -m reflex.eval.seed

demo:
	$(PY) scripts/start_demo.py

test:
	$(PY) -m pytest tests -m "not e2e and not ai_live"

test-unit:
	$(PY) -m pytest tests/unit tests/security tests/api -m "not integration and not load"

lint:
	ruff check packages apps tests

type:
	mypy packages apps

eval-smoke:
	$(PY) -m reflex.eval.cli smoke

reproduce:
	bash eval/reproduce.sh

web-install:
	cd apps/web && npm install

web-dev:
	cd apps/web && npm run dev

web-build:
	cd apps/web && npm run build
