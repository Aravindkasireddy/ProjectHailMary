# MAAS jobsearch — local pipeline & CI helpers
# Run from repo root: make pipeline | make test | make ci

PYTHON ?= python3

.PHONY: help install-py install-dashboard test lint-dashboard build-dashboard pipeline pipeline-py ci ci-check compile

help:
	@echo "Targets:"
	@echo "  make install-py        - pip install -r requirements.txt (+ pytest for dev)"
	@echo "  make install-dashboard - npm ci in dashboard/"
	@echo "  make test              - pytest"
	@echo "  make compile           - byte-compile key Python modules"
	@echo "  make lint-dashboard    - eslint (dashboard)"
	@echo "  make build-dashboard   - next build (dashboard)"
	@echo "  make pipeline          - ./scripts/run_pipeline.sh (scrape → filter → classify)"
	@echo "  make pipeline-py       - same stages via Makefile (no shell script)"
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
		jobsearch_paths.py jobsearch_webhook.py notion_sqlite_mirror.py \
		dashboard_server.py find_and_scrape_jobs.py save_to_notion.py scrape_jobs.py \
		scripts/

lint-dashboard:
	cd dashboard && npm run lint

build-dashboard:
	cd dashboard && npm run build

pipeline:
	@chmod +x scripts/run_pipeline.sh 2>/dev/null || true
	@./scripts/run_pipeline.sh

pipeline-py:
	@test -f find_and_scrape_jobs.py
	$(PYTHON) find_and_scrape_jobs.py
	$(PYTHON) scripts/scrape_and_filter_candidates.py
	$(PYTHON) scripts/classify_and_save.py

ci-check: test compile build-dashboard

ci: ci-check lint-dashboard
