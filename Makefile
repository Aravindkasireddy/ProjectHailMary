# MAAS jobsearch — local pipeline & CI helpers
# Run from repo root: make pipeline | make test | make ci

PYTHON ?= python3

.PHONY: help install-py install-dashboard test lint-dashboard build-dashboard pipeline pipeline-py ci ci-check compile docker-setup docker-build docker-up docker-down docker-shell docker-pipeline

help:
	@echo "Targets:"
	@echo "  make install-py        - pip install -r requirements.txt (+ pytest for dev)"
	@echo "  make install-dashboard - npm ci in dashboard/"
	@echo "  make test              - pytest"
	@echo "  make compile           - byte-compile key Python modules"
	@echo "  make lint-dashboard    - eslint (dashboard)"
	@echo "  make build-dashboard   - next build (dashboard)"
	@echo "  make pipeline          - ./scripts/run_pipeline.sh (scrape → filter → classify)"
	@echo "  make pipeline-py       - same as pipeline (shell script; set PYTHON=... if needed)"
	@echo "  make docker-setup      - create .env from .env.example if needed, then docker compose build"
	@echo "  make docker-build      - docker compose build"
	@echo "  make docker-up         - docker compose up --build"
	@echo "  make docker-down       - docker compose down"
	@echo "  make docker-shell      - shell in api container (compose must be running)"
	@echo "  make docker-pipeline   - run ./scripts/run_pipeline.sh inside api container"
	@echo "  make ci-check          - test + compile + dashboard build (matches required GH CI)"
	@echo "  make ci                - ci-check + strict dashboard lint"

install-py:
	$(PYTHON) -m pip install -r requirements.txt
	$(PYTHON) -m pip install pytest

install-dashboard:
	cd dashboard && npm ci

test:
	$(PYTHON) -m pytest tests/ -q --tb=short

compile:
	$(PYTHON) -m compileall -q \
		jobsearch_paths.py jobsearch_webhook.py \
		dashboard_server.py find_and_scrape_jobs.py scrape_jobs.py \
		scripts/

lint-dashboard:
	cd dashboard && npm run lint

build-dashboard:
	cd dashboard && npm run build

pipeline:
	@chmod +x scripts/run_pipeline.sh 2>/dev/null || true
	@./scripts/run_pipeline.sh

pipeline-py:
	@chmod +x scripts/run_pipeline.sh 2>/dev/null || true
	@PYTHON=$(PYTHON) ./scripts/run_pipeline.sh

ci-check: test compile build-dashboard

ci: ci-check lint-dashboard

docker-setup:
	@chmod +x scripts/docker-setup.sh 2>/dev/null || true
	@./scripts/docker-setup.sh

docker-build:
	docker compose build

docker-up:
	docker compose up --build --remove-orphans

docker-down:
	docker compose down --remove-orphans

docker-shell:
	docker compose exec api bash

docker-pipeline:
	docker compose exec api bash -lc 'chmod +x scripts/run_pipeline.sh 2>/dev/null; ./scripts/run_pipeline.sh'
