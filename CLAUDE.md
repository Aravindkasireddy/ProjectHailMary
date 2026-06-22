# Gemini-jobsearch — Project Reference

Multi-tenant job sourcing/matching platform for DevOps/SRE-type roles. Pipeline discovers jobs (Yahoo + ATS boards), filters/validates postings, classifies them with Gemini, upserts approved jobs to Supabase (the sole job-data store), and serves a Next.js dashboard.

## Stack
- **Backend**: Python 3.11+, stdlib `http.server` (no FastAPI/Flask), Playwright (WebKit) for scraping, BeautifulSoup, Apify (hosted scraping actors, see below), Supabase (Postgres+Auth+RLS), Gemini API for classification, OpenAI for resume tailoring, Discord/Slack webhooks.
- **Frontend**: `dashboard/` — Next.js 16.2.6 (App Router), React 19.2.4, Tailwind 4, TypeScript, Supabase JS client.
- **Infra**: Docker Compose (API on 8080, Web on 3000), GitHub Actions CI + auto-deploy to prod (see "Production deployment" below).

## Repo layout
- `find_and_scrape_jobs.py` — Stage 1: Yahoo + ATS job discovery → `scraped_jobs.json`
- `scripts/scrape_and_filter_candidates.py` — Stage 2: re-scrape + regex red-flag filtering → `active_candidate_jobs.json` / `failed_candidate_jobs.json`
- `scripts/classify_and_save.py` — Stage 3: Gemini/keyword classification → `approved_jobs.json`, upserts to Supabase `public.jobs`
- `scripts/run_pipeline.sh` — orchestrates all 3 stages (`SKIP_SCRAPE=1`, `MAAS_USER_ID=...` env overrides)
- `dashboard_server.py` (~3080 lines, down from ~4040 — see "Module split" below) — HTTP API (port 8080) via `DashboardHandler(BaseHTTPRequestHandler)`, scheduler loop, scraper subprocess orchestration. Still the core backend/most logic, but pure helper groups have been extracted (below).
- `dashboard_config_store.py` — `load_config`/`save_config`/`load_policy_config`/`save_policy_config`/`rebuild_classifier_prompt`.
- `stale_checker.py` — `check_url_stale`/`persist_job_stale_flag`/`stale_check_worker`/`get_stale_check_state` + the `stale_check_states` dict (single source of truth, re-imported by `dashboard_server.py`).
- `h1b_sponsors.py` — `clean_company_name`/`get_h1b_sponsors_cleaned`/`is_sponsor_match` + sponsor cache globals.
- `watched_companies_scheduler.py` — `resolve_watched_company_input`/`_watched_company_scrape_thread`/`watched_companies_scheduler_loop` + related helpers and the `_watched_scrape_inflight` set/lock.
- `company_scraper/` — on-demand single-company scraper (Greenhouse/Lever/Workday/iCIMS/generic), invoked as subprocess from `dashboard_server.py` via `company_scraper/main.py`
  - `company_scraper/scrapers/apify_client.py` — Apify wrapper used by `workday.py` and `generic.py` (see "Scraping methods by source" below)
- `services/resume_service.py` — JD signal extraction + GPT-4o resume tailoring
- `dashboard/` — Next.js UI (`src/app/page.tsx`, ~3750 lines, is the main job board; `company-scraper/page.tsx` is the scraper UI)
  - `dashboard/components/JobCard.tsx` — extracted per-job card (badges, salary/visa panel, classifier output, all action buttons) from `page.tsx`; state/API calls stay in `page.tsx`, passed down as callback props
- `tests/` — pytest suite (auth, multi-tenant RLS, query expansion, path resolution)
- `scripts/schema.sql`, `scripts/*.sql` — Supabase table DDL/migrations
- `Job_classifier_prompt.txt` — Gemini system prompt defining role/label rules (rewritten 2026-06-22, see "Classifier prompt" below)
- `config.json` — target titles, scheduler, search params, target ATS companies
- `policy_config.json` — salary/visa/clearance thresholds

## Data flow
1. Dashboard triggers `POST /api/scrape` → spawns `find_and_scrape_jobs.py` → `scrape_and_filter_candidates.py` → `classify_and_save.py` (sequential subprocesses).
2. Classified jobs land in `approved_jobs.json` and get upserted to Supabase `public.jobs` (RLS-scoped by `user_id`).
3. Dashboard `GET /api/jobs` merges local JSON + Supabase rows, adds H1B sponsor matches and resume match scores.
4. After each pipeline run, newly approved jobs found in this run trigger an optional Discord/Slack webhook digest (or per-job alert) — no Notion sync; Supabase `public.jobs` is the sole job-data store.
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

**Pre-check before calling the generic actor** (added 2026-06-22, real incident): confirmed live that calling `GENERIC_JOBS_ACTOR` against a host it doesn't support (e.g. Salesforce's custom careers site) logs "Skipping unsupported URL" and returns 0 items every time — 25 production Apify runs were burned this way in one day before the fix. `apify_client.generic_actor_likely_supports(url)` checks the URL's host against the actor's known-supported domain patterns (Ashby/BambooHR/JazzHR/Personio/Recruitee/Rippling/Teamtailor/JOIN.com/Workday/Greenhouse/Lever) before `generic.py` even attempts the call — unrecognized hosts skip straight to local Playwright, no wasted quota. Intentionally permissive on uncertainty: an unrecognized-but-actually-supported host costs one wasted call (same as before, not a regression), never blocks a genuinely supported one.

**Daily run cap**: `apify_client._check_and_increment_daily_usage()` caps Apify actor calls at `APIFY_MAX_RUNS_PER_DAY` (default 200/day, tracked in `logs/apify_usage.json`) to guard against runaway spend from the scheduler loop. Raising past the cap raises `RuntimeError`, which is caught by the same try/except that handles any other Apify failure — so hitting the cap just means scrapers silently fall back to local Playwright for the rest of the day, not a hard crash.

Test coverage: `tests/test_apify_scraping.py` covers `_normalize_items()` mapping, the daily cap, `run_actor` without a token, and that `generic.py`/`workday.py` fall back to local scraping when Apify raises.

## Module split (dashboard_server.py)
`dashboard_server.py` was a single ~4040-line file: ~50 module-level helper functions plus the `DashboardHandler` HTTP routing class. The pure/standalone helper groups (config persistence, stale-checking, Notion sync, H1B matching, watched-company scheduling, auth) were extracted into sibling modules — same function names/signatures/behavior, just relocated. **`DashboardHandler`'s do_GET/do_POST routing logic itself was deliberately left untouched** in that pass — moving ~40 route branches blind in the same change as the extraction was judged too risky. Where an extracted function needed state still owned by `dashboard_server.py` (`WORKSPACE_DIR`, `resolve_path`, `_invalidate_jobs_cache`, etc.), the new modules do a lazy `import dashboard_server as ds` inside the function body to avoid circular imports while always reading current values. Verified via `import dashboard_server` smoke test, full pytest suite, and a live server boot hitting `/api/health` + `/api/health/playwright`.

**Update**: the Notion sync module (`notion_sync.py`) and its SQLite mirror (`notion_sqlite_mirror.py`) described above were later deleted entirely when Notion support was removed (Supabase `public.jobs` is now the sole job-data store). The `users` table that briefly lived in a re-homed `user_auth_db.py` (`data/app_users.db`) was itself deleted shortly after — see "Auth" below, that whole local-login path was dead code.

**Worktree-merge gotcha**: the Notion-removal pass ran in an isolated worktree spawned from an earlier commit than `main` had advanced to (3 commits behind: the Apify-usage endpoint, the classifier rewrite, and critically the `JobCard.tsx` extraction). Merging main back into that worktree branch produced a real conflict in `page.tsx` (old inline per-job JSX vs. the new `<JobCard ... />` call) — resolved by keeping the componentized call but dropping the two Notion-sync props (`syncingJobUrl`/`onSyncJob`) it still referenced, then separately cleaning the equivalent dead "Sync Notion" button out of `JobCard.tsx` itself, which the worktree agent had never seen and so never touched. Lesson: when delegating a long-running worktree task, check `git merge-base` against current `main` before trusting a clean-looking diff — a stale branch point means components that didn't exist yet at spawn time won't get the same cleanup pass.

**Correction**: `tests/test_dashboard_auth.py` *does* exercise the route layer — it boots a real `ThreadingHTTPServer(DashboardHandler)` on a free port and hits real endpoints over HTTP (`/api/jobs`, `/api/scrape`, `/api/scrape/company`, `/api/scrape/status`, `/api/config`, `/api/policy`, `/api/analytics`, `/api/apify-usage`, health endpoints), asserting status codes and auth boundaries (401/403). It is not exhaustive — most of the ~40 routes still have no test — but the "zero route coverage" claim from the initial module-split pass was wrong; reuse this file's `test_server` fixture (module-scoped, spins up a live server) and `tests/conftest.py`'s `mock_auth` fixture rather than building new test infra when adding more route tests.

## Auth
Login/signup is **Supabase Auth only** — `dashboard/src/app/page.tsx` calls `supabase.auth.signInWithPassword`/`signUp`/`onAuthStateChange` directly; there is no backend-issued session token. `DashboardHandler.get_auth_payload()` verifies the Bearer JWT via `supabase_client.verify_supabase_jwt()` on every `/api/*` request; `get_auth_role()` maps the Supabase `"authenticated"` role claim to `"admin"` only for the literal email `admin@hailmary.ai`, `"user"` otherwise (any other raw role value, e.g. a test-minted `"admin"`/`"user"`, passes through unchanged).

This used to have a *second*, parallel auth path: `/api/login`/`/api/register` backed by a local SQLite `users` table (`auth_helpers.py`, `user_auth_db.py`, `data/app_users.db`). Removed 2026-06-22 — confirmed via grep that the frontend never called those routes (it only ever used Supabase Auth), so the SQLite path was pure dead weight plus a real weak spot (hardcoded `admin123`/`user123` fallback passwords). Tests that used to call `/api/login`/`/api/register` to mint session tokens now use `tests/conftest.py`'s `mock_auth` fixture, which monkeypatches `supabase_client.verify_supabase_jwt` to accept arbitrary minted `(email, role)` tokens without touching real Supabase or a local DB — same testing capability, no backend dependency. Full suite is 33 tests post-removal (down from 35 — the two `/api/login`-specific success/failure tests no longer apply). Verified live on the VM: `/api/login` now 403 (falls through to the generic admin-required gate for unrecognized POST paths, since there's no more special-case for it — not a clean 404, but functionally gone either way), `/api/jobs` correctly 401 without a real Supabase JWT.

## Caching
There's an existing in-memory cache for `load_all_jobs()`: `_cached_jobs_data`/`_cached_jobs_mtimes` (dashboard_server.py, per-user-email keyed), invalidated via `_invalidate_jobs_cache(email)` whenever jobs are written. It's keyed on local JSON file mtimes, so it only helps the local-JSON merge path — there is no caching for Supabase queries, no HTTP-level caching (ETag/Cache-Control) on any `/api/*` response, and `get_h1b_sponsors_cleaned()` reloads/recomputes its sponsor list each call (own internal cache, separate from the jobs cache). Don't assume "no caching layer" when investigating perf — check `_cached_jobs_data` first.

## Duplicate jobs (fixed 2026-06-22)
Root cause was **not** in `near_dedup.py` — that module only *flags* near-duplicates (`is_duplicate`/`duplicate_of`/`duplicates` fields) by description-similarity, it never removes them, and **the frontend never read those fields**, so flagged duplicates still rendered. Fixed in `dashboard/src/app/page.tsx`: all job-category lists now derive from `dedupedJobs = jobs.filter(j => !j.is_duplicate)` instead of the raw `jobs` array.

The bigger source of duplicates was a separate bug in `find_and_scrape_jobs.py`'s LinkedIn-scrape path: `resolve_career_link()` → `resolve_career_link_with_llm()` asks Gemini/OpenAI to "find the most accurate direct URL" for a (company, title) pair with **zero grounding/verification** — LLMs reliably hallucinate plausible-looking but fake URLs (placeholder IDs like `?jobId=123456`, generic `/careers/index.jsp` listing pages). Every hallucinated/re-resolved URL became a *new* `job_url`, and since Supabase's uniqueness is `(user_id, job_url)`, each fake URL minted a brand-new duplicate row — confirmed at scale: KeyBank's "CI/CD Engineer" alone had 79 rows, one real company-wide audit found 619 of 3189 total `public.jobs` rows (≈19%) were duplicates across 310 `(company, title)` groups.

**Fix**: `scrape_linkedin()` now calls a new `_resolved_career_url_is_live()` helper before trusting a resolved URL — wraps `job_link_health.check_job_posting_live()` and only accepts the resolved URL if it's a genuine 2xx response (not stale, not uncertain/gated/error). Any ambiguity falls back to the real, stable LinkedIn URL instead of an unverified guess. Verified against real fabricated KeyBank URLs (correctly rejected) and known-live Workday/Greenhouse URLs (correctly accepted).

**One-time data cleanup** (2026-06-22): ran a one-off script (not committed — was a manual Supabase Python session) that grouped all `public.jobs` rows by `(user_id, normalized company_name, normalized job_title)` and deleted all but the most-recently-`scraped_at` row per group — 619 rows deleted, table went 3189 → 2570. Caveat: "most recent" doesn't guarantee "most correct" — some surviving rows are themselves generic careers-landing-page URLs rather than specific postings, since the cleanup didn't re-run liveness verification on survivors. If duplicates reappear for a given company, check whether the surviving `job_url` is actually a specific job page vs. a generic index page (the latter should probably be filtered at scrape time too — not yet done).

## Observability
- **`/api/apify-usage`** (auth required): returns `{configured, date, runs_today, max_runs_per_day}` from `apify_client.get_usage_summary()` — read-only view of the daily Apify spend guardrail, for surfacing in the dashboard UI without SSHing into the VM.
- **CI failure alerts**: `.github/workflows/ci.yml` has a `notify-on-failure` job (needs: `[python, dashboard, deploy]`, `if: failure()`) that posts to Discord via the existing bot (`DISCORD_BOT_TOKEN`/`DISCORD_CHANNEL_ID` — same bot used by `jobsearch_webhook.py`, not a separate incoming webhook). Each Discord-posting step itself is conditioned on those two secrets being non-empty, so the job no-ops cleanly instead of erroring if they're not yet added as repo secrets (as of 2026-06-22 they are **not yet added** — alerting is wired but inactive until you add them).

## Classifier prompt
`Job_classifier_prompt.txt` was fully rewritten 2026-06-22 with a new role taxonomy (added System Engineer, Data Platform Engineer, MLOps, AIOps; retired Database/Network/Security Engineer families entirely — those now hit `OutOfScope` + red flag "Retired MAAS role family"). Salary is explicitly **no longer a red flag** (old prompt blocked on salary below a threshold; new prompt's Compensation rule says salary should never trigger DO_NOT_APPLY). Experience-cap logic is now fixed MAAS-standard text (3–6 yrs non-SRE, 3–7 yrs SRE) rather than derived from `policy_config.json`'s `max_experience_years`/`min_salary_*`.

**`dashboard_config_store.rebuild_classifier_prompt()` was updated to match**: it used to splice a config-driven block between `"## RED FLAG RULES"` and `"## DATABASE ENGINEER RULE"` (which no longer exists in the new prompt — would have silently broken). It now splices only the `"### Work authorization restriction"` sub-block (between that header and `"### Experience requirement violation"`), still driven by `policy_config.json`'s `enforce_visa_sponsorship`/`enforce_no_clearance`/`custom_red_flag_keywords` — the rest of the much-larger new RED FLAG RULES section (generic-support, software-dev-dominant, niche-domain, role-alignment, compensation sub-rules) is static and untouched by rebuild. Verified via direct call and through the live `/api/policy` endpoint, including the visa/clearance-disabled paths.

## CI/CD gotcha: `secrets` context is not allowed in step `if:` conditionals
Hit this for real (2026-06-22): a `notify-on-failure` step had `if: ${{ secrets.DISCORD_BOT_TOKEN != '' && ... }}` — GitHub Actions rejects this as an **invalid workflow file** ("Unrecognized named-value: 'secrets'"), and when a workflow file is invalid, GitHub registers the run under the literal file path as its name with **zero jobs** and an immediate failure — not a job failure, the whole pipeline never starts. This broke `main` for one push (tests/build/deploy all silently didn't run) before being caught and fixed. The `secrets` context is only available in `env:`/`with:`/`run:` blocks, not `if:`. Fix pattern: move the secret into `env:`, then branch on it inside the `run:` shell script (`if [ -z "$SECRET" ]; then exit 0; fi`) instead of a YAML-level `if:`. If you ever add a new conditional step gated on a secret's presence, use this pattern, not `if: secrets.X != ''`.

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
`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_ANON_KEY`, `GEMINI_API_KEY` (+ rotation keys), `JOBSEARCH_WEBHOOK_URL`, `OPENAI_API_KEY` (resume tailoring), `MAAS_USER_ID`/`MAAS_USER_EMAIL` (per-user pipeline scoping), `APIFY_API_TOKEN` (optional — enables Apify-backed Workday/generic scraping; falls back to local Playwright if unset), `APIFY_MAX_RUNS_PER_DAY` (optional, default 200 — caps daily Apify actor calls).

## Conventions / gotchas
- `jobsearch_paths.py` is the single source of truth for workspace root — don't hardcode paths elsewhere.
- `employer_job_url.py` (Python) and `dashboard/src/lib/employerJobUrl.ts` (TS) implement the *same* official-careers-URL classification logic — keep them in sync if changed.
- `dashboard/CLAUDE.md` already warns about Next.js 16 breaking API changes — check it before touching frontend routing/params.
- Company scraper runs as a subprocess (not in-process) specifically to isolate scraping crashes from the API process.
- Local JSON files are pipeline staging/audit trail before Supabase sync — don't assume Supabase is the only source of truth for jobs data.
- Apify actors (`fantastic-jobs/jobs-scraper`, `fantastic-jobs/workday-jobs-scraper`) were picked over alternatives (blackfalcondata, unfenced-group) for 100% run success rate and matching output schema between the two — reuse `apify_client._normalize_items()` rather than writing a new normalizer if adding another `fantastic-jobs` actor.
- `apify-client` is in `requirements.txt`; no code path requires it unless `APIFY_API_TOKEN` is set (import is deferred/local inside the functions that need it).
- Near-dedup (`near_dedup.group_and_flag_duplicates`) and staleness checking (`job_link_health.check_job_posting_live`) are already wired into `dashboard_server.py` (dedup runs on every `/api/jobs` load; staleness has a manual `/api/check-stale` trigger + background worker) — confirmed by audit, not gaps to fix.
- The real driver of pipeline behavior for a logged-in user is the Supabase `user_configs` row (`target_titles`, policy thresholds, etc.), **not** `config.json` — `config.json` is only the unauthenticated/default fallback. If a user reports "the feed feels off," check their `user_configs` row first, not just the repo's local JSON.
- `config.json`'s `target_companies` lists (Greenhouse/Lever/Ashby/SmartRecruiters slugs) drift dead over time as companies rename/retire their ATS boards — confirmed 16 dead 404 slugs on a 2026-06-22 live audit (pruned). Worth a periodic live-check sweep (hit each board's API directly) rather than assuming the list stays valid indefinitely. Don't run the check at high concurrency (20 workers) against companies with huge boards (some payloads are 40MB+) — caused false "dead" timeouts on re-check that were actually alive at lower concurrency/individually.
- **`find_and_scrape_jobs.py`'s `fetch_with_playwright()` is wrapped in `PLAYWRIGHT_LOCK`** (added 2026-06-22, real incident): the LinkedIn-scrape `ThreadPoolExecutor(max_workers=4)` calls it concurrently, but Playwright's *sync* API is not safe to drive from multiple threads at once — one thread's browser crash corrupts the shared driver state for every other concurrently-running thread, surfacing as `'PlaywrightContextManager' object has no attribute '_playwright'` cascading across all of them (observed live: a single crashed Chromium process degraded ~7 concurrent LinkedIn scrapes into slow/unreliable LLM-fallback parsing in the same run). Fixed by serializing all `sync_playwright()` usage behind one lock (`with PLAYWRIGHT_LOCK, sync_playwright() as p:` — single `with` statement, no re-indentation of the existing 100+ line body needed). This trades concurrency on the *browser session* for correctness; the threads still parallelize everything else (HTTP, parsing). If you add another concurrent Playwright call site, route it through the same lock rather than a new one.
