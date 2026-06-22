# Gemini-jobsearch — Project Reference

Multi-tenant job sourcing/matching platform for DevOps/SRE-type roles. Pipeline discovers jobs (Yahoo + ATS boards), filters/validates postings, classifies them with Gemini, syncs approved jobs to Notion/Supabase, and serves a Next.js dashboard.

## Stack
- **Backend**: Python 3.11+, stdlib `http.server` (no FastAPI/Flask), Playwright (WebKit) for scraping, BeautifulSoup, Apify (hosted scraping actors, see below), Supabase (Postgres+Auth+RLS), Gemini API for classification, OpenAI for resume tailoring, Notion API, Discord webhooks.
- **Frontend**: `dashboard/` — Next.js 16.2.6 (App Router), React 19.2.4, Tailwind 4, TypeScript, Supabase JS client.
- **Infra**: Docker Compose (API on 8080, Web on 3000), GitHub Actions CI + auto-deploy to prod (see "Production deployment" below).

## Repo layout
- `find_and_scrape_jobs.py` — Stage 1: Yahoo + ATS job discovery → `scraped_jobs.json`
- `scripts/scrape_and_filter_candidates.py` — Stage 2: re-scrape + regex red-flag filtering → `active_candidate_jobs.json` / `failed_candidate_jobs.json`
- `scripts/classify_and_save.py` — Stage 3: Gemini/keyword classification → `approved_jobs.json`, upserts to Supabase `public.jobs`
- `scripts/run_pipeline.sh` — orchestrates all 3 stages (`SKIP_SCRAPE=1`, `MAAS_USER_ID=...` env overrides)
- `dashboard_server.py` (~3080 lines, down from ~4040 — see "Module split" below) — HTTP API (port 8080) via `DashboardHandler(BaseHTTPRequestHandler)`, scheduler loop, scraper subprocess orchestration. Still the core backend/most logic, but pure helper groups have been extracted (below).
- `auth_helpers.py` — `hash_password`/`verify_password`/`verify_user_credentials`/`register_user`. Reads `dashboard_server.ADMIN_PASSWORD`/`USER_PASSWORD` via a lazy `import dashboard_server` inside each function (not at module load) — preserves `tests/test_dashboard_auth.py`'s pattern of monkeypatching those after import.
- `dashboard_config_store.py` — `load_config`/`save_config`/`load_policy_config`/`save_policy_config`/`rebuild_classifier_prompt`/`load_synced_jobs`/`mark_job_synced`.
- `stale_checker.py` — `check_url_stale`/`persist_job_stale_flag`/`stale_check_worker`/`get_stale_check_state` + the `stale_check_states` dict (single source of truth, re-imported by `dashboard_server.py`).
- `notion_sync.py` — `build_notion_properties`/`build_page_children`/`check_job_exists_in_notion`/`sync_job_to_notion`/`_mirror_notion_row_to_sqlite`/`clean_text_for_notion`. Deliberately kept separate from the root `save_to_notion.py` CLI script — different function signatures (e.g. `build_notion_properties(job)` vs `build_notion_properties(job, db_properties=None)`), merging would have changed behavior.
- `h1b_sponsors.py` — `clean_company_name`/`get_h1b_sponsors_cleaned`/`is_sponsor_match` + sponsor cache globals.
- `watched_companies_scheduler.py` — `resolve_watched_company_input`/`_watched_company_scrape_thread`/`watched_companies_scheduler_loop` + related helpers and the `_watched_scrape_inflight` set/lock.
- `company_scraper/` — on-demand single-company scraper (Greenhouse/Lever/Workday/iCIMS/generic), invoked as subprocess from `dashboard_server.py` via `company_scraper/main.py`
  - `company_scraper/scrapers/apify_client.py` — Apify wrapper used by `workday.py` and `generic.py` (see "Scraping methods by source" below)
- `services/resume_service.py` — JD signal extraction + GPT-4o resume tailoring
- `dashboard/` — Next.js UI (`src/app/page.tsx` is the main job board; `company-scraper/page.tsx` is the scraper UI)
- `tests/` — pytest suite (auth, multi-tenant RLS, query expansion, mirror sync, path resolution)
- `scripts/schema.sql`, `scripts/*.sql` — Supabase table DDL/migrations
- `Job_classifier_prompt.txt` (70KB) — Gemini system prompt defining role/label rules
- `config.json` — target titles, scheduler, search params, target ATS companies
- `policy_config.json` — salary/visa/clearance thresholds

## Data flow
1. Dashboard triggers `POST /api/scrape` → spawns `find_and_scrape_jobs.py` → `scrape_and_filter_candidates.py` → `classify_and_save.py` (sequential subprocesses).
2. Classified jobs land in `approved_jobs.json` and get upserted to Supabase `public.jobs` (RLS-scoped by `user_id`).
3. Dashboard `GET /api/jobs` merges local JSON + Supabase rows, adds H1B sponsor matches and resume match scores.
4. `POST /api/sync` / scheduled sync pushes APPLY-decision jobs to Notion; mirrored locally in `data/notion_job_reports.db` (SQLite).
5. Watched-company scheduler periodically subprocess-spawns `company_scraper/main.py` to upsert new jobs directly to Supabase.

Multi-tenancy: per-user scoping uses `MAAS_USER_ID`/`MAAS_USER_EMAIL` env vars and scoped filenames (e.g. `scraped_jobs_<email>.json`), plus Supabase RLS for the `jobs` and `user_configs` tables.

## Scraping methods by source
| Source | Method | Where |
|---|---|---|
| Greenhouse | Official JSON API (`boards-api.greenhouse.io/v1/boards/{slug}/jobs`) | `company_scraper/scrapers/greenhouse.py` |
| Lever | Official JSON API (`api.lever.co/v0/postings/{slug}?mode=json`) | `company_scraper/scrapers/lever.py` |
| Workday | **Apify-first** (`fantastic-jobs/workday-jobs-scraper` actor) → falls back to local Playwright Chromium if Apify unset/fails/empty | `company_scraper/scrapers/workday.py` |
| Generic / unknown ATS | **Apify-first** (`fantastic-jobs/jobs-scraper` actor, covers 12 ATS platforms) → falls back to local Playwright WebKit + BeautifulSoup | `company_scraper/scrapers/generic.py` |
| iCIMS | Local HTML scrape only (requests + BeautifulSoup, paginated `?iis=`) — **deliberately not on Apify**: `fantastic-jobs/jobs-scraper` does not support iCIMS (confirmed live — it logs "Skipping unsupported URL"); no dedicated iCIMS actor was found on Apify Store either | `company_scraper/scrapers/icims.py` |
| Yahoo job search (Stage 1 discovery) | Local HTML scrape of `search.yahoo.com/search?p=...` — no API, no Apify | `find_and_scrape_jobs.py`, `company_scraper/discovery.py` |

Apify integration: `company_scraper/scrapers/apify_client.py` wraps the `apify-client` SDK. Gated entirely by `APIFY_API_TOKEN` env var — if unset, Workday/generic scrapers behave exactly as before (local Playwright). Both Apify actors are from the same vendor (`fantastic-jobs`) and share an output shape (`title`/`description`/`locations`/`url`/`date_posted`), normalized via `_normalize_items()` in `apify_client.py` into this project's row shape (`job_url`/`job_title`/`company_name`/`job_description`/`location_work_type`/`requirement_id`). The `fantastic-jobs/jobs-scraper` actor's actual supported platforms are: Workday, Greenhouse, Ashby, Lever.co, BambooHR, JazzHR, Personio, Recruitee, Rippling, Rival, Teamtailor, JOIN.com — iCIMS is not among them, so don't re-attempt that migration without a different actor.

**Daily run cap**: `apify_client._check_and_increment_daily_usage()` caps Apify actor calls at `APIFY_MAX_RUNS_PER_DAY` (default 200/day, tracked in `logs/apify_usage.json`) to guard against runaway spend from the scheduler loop. Raising past the cap raises `RuntimeError`, which is caught by the same try/except that handles any other Apify failure — so hitting the cap just means scrapers silently fall back to local Playwright for the rest of the day, not a hard crash.

Test coverage: `tests/test_apify_scraping.py` covers `_normalize_items()` mapping, the daily cap, `run_actor` without a token, and that `generic.py`/`workday.py` fall back to local scraping when Apify raises.

## Module split (dashboard_server.py)
`dashboard_server.py` was a single ~4040-line file: ~50 module-level helper functions plus the `DashboardHandler` HTTP routing class. The pure/standalone helper groups (config persistence, stale-checking, Notion sync, H1B matching, watched-company scheduling, auth) were extracted into the sibling modules listed above in "Repo layout" — same function names/signatures/behavior, just relocated. **`DashboardHandler`'s do_GET/do_POST routing logic itself was deliberately left untouched** — there's no test coverage for the HTTP route layer (the pytest suite tests helpers, not endpoints), so moving ~40 route branches blind was judged too risky for one pass. Where an extracted function needed state still owned by `dashboard_server.py` (`WORKSPACE_DIR`, `resolve_path`, `_invalidate_jobs_cache`, etc.), the new modules do a lazy `import dashboard_server as ds` inside the function body to avoid circular imports while always reading current values. Verified via `import dashboard_server` smoke test, full pytest suite (34 passed, same as before the split), and a live server boot hitting `/api/health` + `/api/health/playwright`.

If you want to go further (route-layer extraction), add HTTP-level tests for the routes you're about to move *first* — there's currently nothing to catch a routing regression.

## Production deployment
Live at **jobs.arkfarms.store** — a single GCP VM (`8.230.100.65`, user `aravindkasireddy5`, repo cloned at `~/ProjectHailMary`) running Docker Compose (API container on 8080, web container on 3000) behind Nginx + DNS already configured on the VM (not in this repo). GitHub remote for this repo is `Aravindkasireddy/ProjectHailMary`, not `Gemini-jobsearch` — same content, different remote name.

**Pipeline** (`.github/workflows/ci.yml`, `deploy` job): on every push to `main`, after the `python` and `dashboard` test/build jobs both pass, a `deploy` job targeting the `production` GitHub environment SSHes into the VM and runs `git reset --hard origin/main && docker compose up --build -d`, then curls `/api/health` to confirm.
- **Approval gate**: the `production` environment has a `required_reviewers` rule (reviewer: `Aravindkasireddy`) with **admin-bypass turned off** — meaning every deploy, including the repo owner's own pushes, pauses at the `deploy` job until manually approved in the Actions UI ("Review pending deployments" → check `production` → **Approve and deploy**).
- **Deploy key**: GitHub Actions uses a dedicated key (`github-actions-deploy`, generated on the VM, added to its own `~/.ssh/authorized_keys`) stored in the `PROD_SSH_KEY` secret — not the maintainer's personal SSH key.
- **Secrets required** (repo-level, `Settings → Secrets and variables → Actions`): `PROD_SSH_HOST`, `PROD_SSH_USER`, `PROD_SSH_KEY`, `PROD_APP_DIR` (deploy SSH target); `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY` (needed by the `dashboard` job's `next build` — the `/company-scraper` page prerenders a Supabase client at build time and throws `supabaseUrl is required` without these; this was a real CI failure encountered and fixed, not a hypothetical).
- **`git reset --hard origin/main` on deploy** wipes any uncommitted changes on the VM (not `.env` — gitignored, untouched). The VM's repo has some pipeline-output JSON files tracked in git that get locally modified by the running pipeline; these are pipeline output, fine to discard on deploy, not user data.
- Verified end-to-end (2026-06-22): pushed a change, approved the gate, confirmed via direct SSH that the VM's `git log` HEAD matched, containers rebuilt healthy, `/api/health` responded, and a real Apify actor call succeeded from inside the running `api` container (not just locally).

## Key Supabase tables (`scripts/schema.sql`)
- `public.jobs` — one row per `(user_id, job_url)`; includes classification, salary, decision, sync state
- `public.user_configs` — per-user sourcing/policy/integration config
- `public.scrape_runs` — pipeline run history/status per stage

## Running locally
```bash
# Python pipeline
python find_and_scrape_jobs.py
python scripts/scrape_and_filter_candidates.py
python scripts/classify_and_save.py
./scripts/run_pipeline.sh        # orchestrates all three

# API server
JOBSEARCH_DASHBOARD_PORT=8080 python dashboard_server.py

# Dashboard
cd dashboard && npm run dev      # localhost:3000

# Docker (preferred for full stack)
make docker-setup && make docker-up

# Tests / CI
make test        # pytest tests/
make ci-check     # test + compile + next build
```

## Required env vars (`.env`)
`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_ANON_KEY`, `GEMINI_API_KEY` (+ rotation keys), `NOTION_TOKEN`, `NOTION_DATABASE_ID`, `JOBSEARCH_WEBHOOK_URL`, `OPENAI_API_KEY` (resume tailoring), `MAAS_USER_ID`/`MAAS_USER_EMAIL` (per-user pipeline scoping), `APIFY_API_TOKEN` (optional — enables Apify-backed Workday/generic scraping; falls back to local Playwright if unset), `APIFY_MAX_RUNS_PER_DAY` (optional, default 200 — caps daily Apify actor calls).

## Conventions / gotchas
- `jobsearch_paths.py` is the single source of truth for workspace root — don't hardcode paths elsewhere.
- `employer_job_url.py` (Python) and `dashboard/src/lib/employerJobUrl.ts` (TS) implement the *same* official-careers-URL classification logic — keep them in sync if changed.
- `dashboard/CLAUDE.md` already warns about Next.js 16 breaking API changes — check it before touching frontend routing/params.
- Company scraper runs as a subprocess (not in-process) specifically to isolate scraping crashes from the API process.
- Local JSON files are pipeline staging/audit trail before Supabase sync — don't assume Supabase is the only source of truth for jobs data.
- Apify actors (`fantastic-jobs/jobs-scraper`, `fantastic-jobs/workday-jobs-scraper`) were picked over alternatives (blackfalcondata, unfenced-group) for 100% run success rate and matching output schema between the two — reuse `apify_client._normalize_items()` rather than writing a new normalizer if adding another `fantastic-jobs` actor.
- `apify-client` is in `requirements.txt`; no code path requires it unless `APIFY_API_TOKEN` is set (import is deferred/local inside the functions that need it).
- Near-dedup (`near_dedup.group_and_flag_duplicates`) and staleness checking (`job_link_health.check_job_posting_live`) are already wired into `dashboard_server.py` (dedup runs on every `/api/jobs` load; staleness has a manual `/api/check-stale` trigger + background worker) — confirmed by audit, not gaps to fix.
