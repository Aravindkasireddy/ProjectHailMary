#!/bin/sh
# Remove local pipeline artifacts (job JSON, logs, Notion SQLite mirror).
# Does NOT delete: .env, tracked config.json / policy_config.json, source code, Opt_freindly/, etc.
#
# POSIX sh — safe to run as:  sh ./scripts/clear_local_jobsearch_data.sh
#
# Usage:
#   ./scripts/clear_local_jobsearch_data.sh          # prompts for confirmation
#   ./scripts/clear_local_jobsearch_data.sh --yes    # non-interactive (CI / automation)

set -eu
ROOT="$(CDPATH= cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ "${1:-}" != "--yes" ]; then
  echo "This will delete under: $ROOT"
  echo "  - directories: data/ logs/ scratch/"
  echo "  - root job blobs: scraped_jobs*.json approved_jobs*.json active_candidate_jobs*.json"
  echo "                    failed_candidate_jobs*.json synced_jobs*.json candidate_jobs*.json"
  echo "  - per-user config copies: config_*.json policy_config_*.json (not config.json / policy_config.json)"
  echo "  - dry_run_urls.json eslint_report.txt (if present)"
  echo "  - dashboard/.next (Next build cache; will be recreated on next dev/build)"
  printf 'Continue? [y/N] '
  read -r ans || true
  case "$ans" in
    [yY]|[yY][eE][sS]) ;;
    *) echo "Aborted."; exit 1 ;;
  esac
fi

rm -rf -- data logs scratch 2>/dev/null || true
rm -rf -- dashboard/.next 2>/dev/null || true

for f in \
  scraped_jobs*.json \
  approved_jobs*.json \
  active_candidate_jobs*.json \
  failed_candidate_jobs*.json \
  synced_jobs*.json \
  candidate_jobs*.json \
  config_*.json \
  policy_config_*.json
do
  [ -f "$f" ] || continue
  case "$f" in
    config.json|policy_config.json) continue ;;
  esac
  rm -f -- "$f"
done

rm -f -- dry_run_urls.json eslint_report.txt 2>/dev/null || true

echo "Done. Reminder: the dashboard may still store auth in browser localStorage; clear site data for localhost if needed."
echo "Optional: rm -rf dashboard/node_modules .venv venv  (only if you want to reclaim disk; reinstall deps after)."
