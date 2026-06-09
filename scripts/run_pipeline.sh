#!/usr/bin/env bash
# Run the full job-sourcing pipeline from repo root (same stages as dashboard_server scraper).
# Stops on first failing step (set -e).
#
# Optional skips (non-empty = skip that stage):
#   SKIP_SCRAPE=1   — skip find_and_scrape_jobs.py
#   SKIP_FILTER=1   — skip scrape_and_filter_candidates.py
#   SKIP_CLASSIFY=1 — skip classify_and_save.py
#
# Optional Supabase publish (merge scoped JSON → public.jobs after each completed stage):
#   MAAS_USER_ID     — Supabase auth.users.id (UUID)
#   MAAS_USER_EMAIL  — same email used for scoped filenames (e.g. user@example.com)
# Requires .env with SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY (see supabase_client).
#
# Usage:
#   ./scripts/run_pipeline.sh
#   JOBSEARCH_ROOT=/path/to/repo ./scripts/run_pipeline.sh
#   MAAS_USER_ID=... MAAS_USER_EMAIL=you@example.com ./scripts/run_pipeline.sh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export JOBSEARCH_ROOT="${JOBSEARCH_ROOT:-$ROOT}"

PY="${PYTHON:-python3}"
echo "[pipeline] ROOT=$JOBSEARCH_ROOT"

append_pipeline_shell_metric() {
  local step="$1" rc="${2:-0}"
  PIPELINE_METRIC_STEP="$step" PIPELINE_METRIC_RC="$rc" "$PY" -c "
import os, sys
root = os.environ.get('JOBSEARCH_ROOT', '.')
sys.path.insert(0, os.path.join(root, 'scripts'))
from pipeline_metrics import append_pipeline_metric
append_pipeline_metric(
    root,
    'pipeline_shell_step',
    {
        'step': os.environ.get('PIPELINE_METRIC_STEP', ''),
        'returncode': int(os.environ.get('PIPELINE_METRIC_RC', '0')),
    },
)
" || true
}

run_stage() {
  local name="$1"
  shift
  echo "[pipeline] === $name ==="
  "$PY" "$@"
}

sync_supabase() {
  local reason="$1"
  if [[ -z "${MAAS_USER_ID:-}" ]]; then
    return 0
  fi
  if [[ -z "${MAAS_USER_EMAIL:-}" ]]; then
    echo "[pipeline] WARN: MAAS_USER_ID set but MAAS_USER_EMAIL empty — skip Supabase sync ($reason)"
    return 0
  fi
  echo "[pipeline] === sync → Supabase ($reason) ==="
  if ! "$PY" "$ROOT/scripts/sync_jobs_to_supabase.py" --reason "$reason"; then
    echo "[pipeline] WARN: Supabase sync failed ($reason) — local JSON is still updated"
  fi
}

if [[ -z "${SKIP_SCRAPE:-}" ]]; then
  if run_stage "scrape (Yahoo + ATS)" "$ROOT/find_and_scrape_jobs.py"; then
    append_pipeline_shell_metric scrape 0
    sync_supabase "after scrape"
  else
    exit 1
  fi
else
  echo "[pipeline] SKIP_SCRAPE set — skipping find_and_scrape_jobs.py"
fi

if [[ -z "${SKIP_FILTER:-}" ]]; then
  set +e
  run_stage "filter" "$ROOT/scripts/scrape_and_filter_candidates.py"
  filter_rc=$?
  set -e
  if [[ "$filter_rc" -eq 0 ]]; then
    append_pipeline_shell_metric filter 0
    sync_supabase "after filter"
  else
    sync_supabase "after filter failure (partial)"
    exit "$filter_rc"
  fi
else
  echo "[pipeline] SKIP_FILTER set — skipping scrape_and_filter_candidates.py"
fi

if [[ -z "${SKIP_CLASSIFY:-}" ]]; then
  set +e
  run_stage "classify" "$ROOT/scripts/classify_and_save.py"
  classify_rc=$?
  set -e
  if [[ "$classify_rc" -eq 0 ]]; then
    append_pipeline_shell_metric classify 0
    sync_supabase "after classify"
  else
    sync_supabase "after classify failure (partial)"
    exit "$classify_rc"
  fi
else
  echo "[pipeline] SKIP_CLASSIFY set — skipping classify_and_save.py"
fi

echo "[pipeline] Done."
