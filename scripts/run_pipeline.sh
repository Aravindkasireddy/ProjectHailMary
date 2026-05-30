#!/usr/bin/env bash
# Run the full job-sourcing pipeline from repo root (same stages as dashboard_server scraper).
# Stops on first failing step (set -e).
#
# Optional skips (non-empty = skip that stage):
#   SKIP_SCRAPE=1   — skip find_and_scrape_jobs.py
#   SKIP_FILTER=1   — skip scrape_and_filter_candidates.py
#   SKIP_CLASSIFY=1 — skip classify_and_save.py
#
# Usage:
#   ./scripts/run_pipeline.sh
#   JOBSEARCH_ROOT=/path/to/repo ./scripts/run_pipeline.sh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export JOBSEARCH_ROOT="${JOBSEARCH_ROOT:-$ROOT}"

PY="${PYTHON:-python3}"
echo "[pipeline] ROOT=$JOBSEARCH_ROOT"

run_stage() {
  local name="$1"
  shift
  echo "[pipeline] === $name ==="
  "$PY" "$@"
}

if [[ -z "${SKIP_SCRAPE:-}" ]]; then
  run_stage "scrape (Yahoo + ATS)" "$ROOT/find_and_scrape_jobs.py"
else
  echo "[pipeline] SKIP_SCRAPE set — skipping find_and_scrape_jobs.py"
fi

if [[ -z "${SKIP_FILTER:-}" ]]; then
  run_stage "filter" "$ROOT/scripts/scrape_and_filter_candidates.py"
else
  echo "[pipeline] SKIP_FILTER set — skipping scrape_and_filter_candidates.py"
fi

if [[ -z "${SKIP_CLASSIFY:-}" ]]; then
  run_stage "classify" "$ROOT/scripts/classify_and_save.py"
else
  echo "[pipeline] SKIP_CLASSIFY set — skipping classify_and_save.py"
fi

echo "[pipeline] Done."
