# Developer commands. Run from the repository root.
# On Windows without GNU make: run the commands shown in each target directly (see README).

BACKEND := backend
FRONTEND := frontend
PY := $(BACKEND)/.venv/bin/python
ifeq ($(OS),Windows_NT)
PY := $(BACKEND)/.venv/Scripts/python.exe
endif

.PHONY: help install dev dev-backend dev-frontend test lint migrate seed token-dev docker-up

help:
	@echo "install       create venv, install backend (pinned) and frontend deps"
	@echo "dev           run backend (8000) and frontend (3000) locally"
	@echo "test          run backend tests (offline; AWS tests excluded)"
	@echo "lint          ruff (backend) and eslint (frontend)"
	@echo "migrate       alembic upgrade head"
	@echo "seed          insert roles and sample taxonomy (idempotent)"
	@echo "token-dev     DEV ONLY: print signed tokens for each role"
	@echo "docker-up     docker compose up --build"

install:
	cd $(BACKEND) && python -m venv .venv
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e "$(BACKEND)[dev]"
	cd $(FRONTEND) && npm ci

migrate:
	cd $(BACKEND) && ../$(PY) -m alembic upgrade head

seed:
	cd $(BACKEND) && ../$(PY) scripts/seed.py

token-dev:
	cd $(BACKEND) && ENV=development ../$(PY) scripts/dev_token_issuer.py

dev-backend:
	cd $(BACKEND) && ../$(PY) -m uvicorn app.main:app --reload --port 8000

dev-frontend:
	cd $(FRONTEND) && npm run dev

dev:
	$(MAKE) -j2 dev-backend dev-frontend

test:
	cd $(BACKEND) && ../$(PY) -m pytest

lint:
	cd $(BACKEND) && ../$(PY) -m ruff check . && ../$(PY) -m ruff format --check .
	cd $(FRONTEND) && npm run lint

docker-up:
	docker compose -f infra/docker-compose.yml up --build
