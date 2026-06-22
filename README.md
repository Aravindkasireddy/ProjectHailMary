# Gemini-jobsearch (MAAS job sourcing)

Single **monorepo**: Python sourcing pipeline + **`dashboard/`** Next.js UI. Discovery targets US roles (remote, hybrid, or onsite), optional Notion sync and Discord/Slack webhooks.

**On Windows**, running via **[Docker](#docker-api--dashboard)** is the most reliable path (Playwright + bash pipeline + one command for API + UI).

### Local data vs Supabase

- **Supabase** holds the live job board (`public.jobs`) and user settings; you can use the dashboard **without** keeping job JSON on disk.
- The **Python pipeline** (`find_and_scrape_jobs.py`, classify scripts, `dashboard_server.py` upload paths) still **writes JSON and logs under the repo root** by design (and `data/notion_job_reports.db` after Notion syncs). That is normal for this repo today.
- To **wipe generated artifacts** on your Mac (job blobs, `data/`, `logs/`, `scratch/`, Next `.next` cache): run **`./scripts/clear_local_jobsearch_data.sh`** (or **`sh ./scripts/clear_local_jobsearch_data.sh`**) or **`./scripts/clear_local_jobsearch_data.sh --yes`** for no prompt. It does **not** delete `.env` or your own folders like `Opt_freindly/`.
- To avoid writing into the repo for a session, you can set **`JOBSEARCH_ROOT`** to a throwaway directory (see `jobsearch_paths.py`); the app will use that path instead of the clone for workspace files.
- The **browser** may still keep dashboard auth in **localStorage**; clear site data for your dev URL if you want that gone too.
- **Company-hosted apply URLs:** In Settings, turn on **Company-hosted apply URLs only** so the list and uploads keep employer career pages and tenant Workday/Oracle links, and drop LinkedIn plus shared ATS boards (Greenhouse, Lever, Ashby, …).

## Layout

| Path | Purpose |
|------|---------|
| `scrape_tracker.py` | Fire-and-forget Supabase writes to **`public.scrape_runs`** (pipeline + company scrapes) |
| `scripts/scrape_runs.sql` | DDL + RLS for **`scrape_runs`** (also merged into `scripts/schema.sql`) |
| `scripts/clear_local_jobsearch_data.sh` | **Wipe** local pipeline outputs (`*.json` job blobs, `data/`, `logs/`, `scratch/`, `dashboard/.next`). See [Local data vs Supabase](#local-data-vs-supabase). |
| `find_and_scrape_jobs.py` | Yahoo `site:` discovery + ATS scrape → `scraped_jobs.json` |
| `scripts/scrape_and_filter_candidates.py` | Re-scrape / validate + red-flag prefilter → `active_candidate_jobs.json`, `failed_candidate_jobs.json` |
| `scripts/classify_and_save.py` | Gemini (optional) + rules → `approved_jobs.json` |
| `company_scraper/` | On-demand **company-targeted** scrape: paste **company name**, **careers URL**, or **one job URL** → discovers listing pages (ATS + fallbacks), collects up to hundreds of roles, filters **IT-related** titles, upserts to Supabase `jobs` via `POST /api/scrape/company` (poll `GET /api/scrape/company/status`) |
| `dashboard_server.py` | API on **port 8080**, scheduler, Notion + webhook helpers; scrape history **`GET /api/scrape/status`**, **`GET /api/scrape/status/<id>`**, **`GET /api/scrape/active`** |
| `dashboard/` | Next.js UI (default **port 3000**); **Company Scraper** UI at `/company-scraper`. The main job board reads **`public.jobs` from Supabase** (local `*.json` files are pipeline staging until you upload/sync). Optional **company-hosted apply URLs only** filter: Settings → **Company-hosted apply URLs only** (stored in **`user_configs.search_official_career_job_urls_only`**); run **`scripts/add_search_official_career_job_urls_only.sql`** once if the column is missing. Logic is shared by `employer_job_url.py` and `dashboard/src/lib/employerJobUrl.ts`. |
| `Job_classifier_prompt.txt` | Large classifier instructions (policy blocks can be rebuilt from `policy_config.json`) |
| `config.json` | Target titles, scheduler, **search** tuning, optional `webhook_url` |
| `policy_config.json` | Salary / experience / visa / clearance knobs for prompt rebuild |
| `notion_sqlite_mirror.py` | Writes **`data/notion_job_reports.db`** whenever a job is successfully synced to Notion (same core fields as the Notion row) |

## Notion + local SQLite mirror

Every successful Notion sync from `dashboard_server.py` (manual **Sync**, scheduler auto-sync, or “already in Notion” duplicate hit) **upserts** a row into:

`data/notion_job_reports.db` → table **`notion_job_reports`**

The DB file is gitignored. The **table** is created when **`dashboard_server.py` starts** (or on first successful sync). **Rows appear only after a successful Notion sync** (manual **Sync**, scheduler auto-sync, or `save_to_notion.py`). If `notion_job_reports.db` is **0 bytes** with no tables (e.g. created with `touch`), delete it and restart the server or sync once.

Inspect locally:

```bash
sqlite3 data/notion_job_reports.db "SELECT job_title, company_name, notion_page_id, synced_at FROM notion_job_reports ORDER BY synced_at DESC LIMIT 10;"
```

## Docker (API + dashboard)

Use this for a **single-command** stack: **Python API on 8080** (with **Playwright WebKit**) and **Next.js on 3000**. On **Windows**, use **Docker Desktop** with the **WSL2 backend**; keep the repo on a **WSL disk path** for faster bind mounts (a `C:\...` clone still works but can be slower).

### Setup

1. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) (includes Compose v2) and ensure it is **running**.
2. **First time only** — create `.env` and build images (safe if `.env` already exists):

   ```bash
   make docker-setup
   ```

   Or: `chmod +x scripts/docker-setup.sh && ./scripts/docker-setup.sh`  
   This copies **`.env.example` → `.env`** when `.env` is missing, then runs **`docker compose build`**.

3. Edit **`.env`**: set **`SUPABASE_URL`**, **`SUPABASE_SERVICE_ROLE_KEY`**, plus Notion/Gemini/webhooks as needed. Restart containers after changing env: **`docker compose up --build`**.
4. Shell scripts must use **LF** line endings in the container. The repo has **`.gitattributes`** for `*.sh`; if you still see `/bin/bash^M` errors on Windows, re-checkout with LF or run `git add --renormalize .` once.

### Run

```bash
docker compose up --build
```

Open **http://localhost:3000**. The UI is built with **`NEXT_PUBLIC_API_URL=http://localhost:8080`** so your **browser** reaches the API on the host.

**Persistence:** Compose mounts **the whole repo** at **`/app`**, so **`data/`**, **`logs/`**, and pipeline **`*.json`** files are written **next to your clone** on disk.

### Pipeline inside the container

With `docker compose up` running:

```bash
make docker-pipeline
```

Or:

```bash
docker compose exec api bash -lc 'chmod +x scripts/run_pipeline.sh 2>/dev/null; ./scripts/run_pipeline.sh'
```

To **also push merged jobs to Supabase** after each stage, set in **`.env`**:

```text
MAAS_USER_ID=<uuid from Supabase auth.users>
MAAS_USER_EMAIL=you@example.com
```

Shell in the API container: **`make docker-shell`**.

### After dashboard code changes

Rebuild the web image: **`docker compose build web`** (or `docker compose up --build`).

**Images:** root **`Dockerfile`** — Playwright's official Python base. **`dashboard/Dockerfile`** — Node 20 production build.

```bash
make docker-setup      # first time: .env + build
make docker-build      # docker compose build
make docker-up         # docker compose up --build
make docker-down       # docker compose down
make docker-shell      # bash inside api (compose must be running)
make docker-pipeline   # full pipeline script inside api
```

### Troubleshooting

**`failed to connect to the docker API` / `docker.sock: no such file or directory`** — the Docker engine is not running. On **macOS**, open **Docker Desktop** (from Applications), wait until it reports **Docker is running**, then run **`make docker-setup`** or **`docker compose build`** again. If you use **Colima** or **OrbStack**, start that service instead.

**`Bind for 0.0.0.0:8080 failed: port is already allocated`** — something on your Mac is already using **8080** (very often a **non-Docker** `python dashboard_server.py` you started earlier, or another container). Either:

- Stop it: `lsof -nP -iTCP:8080 -sTCP:LISTEN` then quit that PID, or  
- Use another **host** port for the API. In **`.env`** add:

  ```text
  JOBSEARCH_API_HOST_PORT=8081
  ```

  Optionally **`JOBSEARCH_WEB_HOST_PORT=3001`** if **3000** is busy too. Then run **`docker compose up --build`** so the **web** image rebuilds with the matching **`NEXT_PUBLIC_API_URL`** (e.g. `http://localhost:8081`).

**`3000: bind: address already in use`** — host port **3000** is taken (often **`npm run dev`** for the dashboard). In **`.env`** set **`JOBSEARCH_WEB_HOST_PORT=3001`** (or any free port), then **`docker compose up --build`**. Open the UI at **`http://localhost:3001`** (or whatever you chose).

**`Host system is missing dependencies` / `Docker image version not matching Playwright version`** — the **Playwright Python package** in `requirements.txt` must match the **`mcr.microsoft.com/playwright/python:v…-jammy`** tag in the root **`Dockerfile`**. After changing either one, rebuild the API image: **`docker compose build --no-cache api`** then **`docker compose up`**.

**`Found orphan containers (…frontend… backend…)`** — left over from an older compose file that used different service names. **`make docker-up`** and **`make docker-down`** now pass **`--remove-orphans`**. You can also run once: **`docker compose down --remove-orphans`**.

## Quick start (native — no Docker)

1. **Python 3.11+** recommended. Create a venv and install deps:

   ```bash
   cd /path/to/Gemini-jobsearch
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   playwright install webkit
   ```

2. **Environment** — copy `.env.example` to `.env` and set at least:

   - `GEMINI_API_KEY` (optional; classifier falls back to keyword rules without it)
   - `NOTION_TOKEN` / `NOTION_DATABASE_ID` if you use Notion sync
   - `JOBSEARCH_WEBHOOK_URL` (optional; overrides `webhook_url` in `config.json` when set)

3. **Run the API + scheduler**

   ```bash
   python dashboard_server.py
   ```

   If you see **`Address already in use`**, something else is bound to **port 8080** (often another copy of this server). Either stop that process, or use another port and point the Next app at it:

   ```bash
   JOBSEARCH_DASHBOARD_PORT=8081 python dashboard_server.py
   ```

   Then set `NEXT_PUBLIC_API_URL=http://localhost:8081` in `dashboard/.env.local`.

4. **Run the dashboard UI**

   ```bash
   cd dashboard && npm install && npm run dev
   ```

   `npm run dev` uses **Webpack** (not Turbopack) so the dev server can write `.next/` in environments where Turbopack hits a read-only path (e.g. some agent or container setups). For Turbopack locally: `npm run dev:turbo`.

   Set `NEXT_PUBLIC_API_URL=http://localhost:8080` in `dashboard/.env.local` if the API is not on localhost.

## Pipeline stages

1. `find_and_scrape_jobs.py` — writes `scraped_jobs.json` (with optional merge of previous file; see `config.search.merge_previous_scrape`).
2. `scripts/scrape_and_filter_candidates.py` — refreshes postings and applies regex red-flag gates.
3. `scripts/classify_and_save.py` — applies `candidate_jobs.json` overrides when present, else Gemini / keyword classifier.

When sourcing runs from the **dashboard** with a logged-in Supabase user, **`upload_user_jobs`** merges scoped JSON (`scraped_jobs`, `active_candidate_jobs`, `failed_candidate_jobs`, `approved_jobs`, `synced_jobs`, plus the Notion SQLite mirror) into **`public.jobs`** after **each** stage (and on filter/classify failure with whatever was produced so far). Local JSON remains the pipeline’s working format; **Postgres is the published source for the UI.**

Logs append to `logs/pipeline.log` (server runs) and `logs/scrape.log` (discovery script). Stage timing from **`dashboard_server.py`** scraper steps and from **`scripts/run_pipeline.sh`** is also appended as JSON lines to **`logs/pipeline_metrics.jsonl`** (best-effort). Optional classifier notes from the UI go to **`logs/classifier_feedback.jsonl`**.

The Python API exposes **`GET /api/health`** (process up) and **`GET /api/health/playwright`** (WebKit launch smoke; returns 503 if browsers are missing). **`GET /api/config/default-target-titles`** returns the same default title list as `jobsearch_constants.DEFAULT_TARGET_TITLES` (no auth). Authenticated users may call **`POST /api/config/reset-target-titles`** (local scoped `config_*.json` plus optional Supabase `user_configs` update when service credentials are set), **`POST /api/classifier-feedback`** (append-only log), and **`POST /api/job/check-live`** with JSON `{"job_url":"…","job_id":"optional-uuid","persist":true}` to probe whether a posting URL still looks **live** or **closed** (HTTP + ATS heuristics in `job_link_health.py`); when `persist` is true, the server updates matching rows in local job JSON (if present) and in Supabase **`public.jobs`** for the authenticated user.

**Supabase RLS:** the backend uses the **service role** key to upsert into `public.jobs` / `user_configs`, so writes bypass end-user RLS. Lock down who can reach **`dashboard_server.py`** (or your API container); treat the service role key like a root password.

**Playwright:** stage 2 uses headless **WebKit**. For the same interpreter you use to run `dashboard_server.py` or the pipeline (venv or system), run `python3 -m playwright install webkit` once after installing deps. If the error mentions `Executable doesn't exist` under a `cursor-sandbox-cache` path, `PLAYWRIGHT_BROWSERS_PATH` may be pointing there—in that shell run the install command again, or unset that variable so browsers live under the default cache (e.g. `~/Library/Caches/ms-playwright` on macOS).

## Pipeline runner (local)

From the **repository root**, run the same three stages as the dashboard scraper (stops on first failure). If you use **Docker**, run **`make docker-pipeline`** while **`docker compose up`** is running (see [Docker](#docker-api--dashboard)).

```bash
chmod +x scripts/run_pipeline.sh   # once
./scripts/run_pipeline.sh
```

Or with **Make**:

```bash
make pipeline          # uses the shell script
make pipeline-py       # same script (respects `PYTHON=...`)
```

Publish merged jobs to **Supabase** after each finished stage (same merge as the dashboard) by exporting:

```bash
export MAAS_USER_ID='<uuid from Supabase auth.users>'
export MAAS_USER_EMAIL='you@example.com'   # must match scoped JSON filenames
./scripts/run_pipeline.sh
```

Requires **`.env`** with `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` (see `supabase_client.py`). If those variables are unset, the pipeline still runs and only updates local JSON.

Skip stages when reusing existing artifacts:

```bash
SKIP_SCRAPE=1 ./scripts/run_pipeline.sh      # only filter + classify
SKIP_FILTER=1 SKIP_CLASSIFY=1 ./scripts/run_pipeline.sh   # scrape only
```

Override Python or repo root:

```bash
PYTHON=python3.12 ./scripts/run_pipeline.sh
JOBSEARCH_ROOT=/path/to/Gemini-jobsearch ./scripts/run_pipeline.sh
```

## CI (GitHub Actions)

On **push** and **pull_request** to `main` (and pushes to `cursor/**` branches), **CI** runs:

- **Python:** `pip install -r requirements.txt`, `pytest`, and `compileall` on core modules.
- **Dashboard:** `npm ci`, **`npm run build`** (required). **`npm run lint`** runs in CI with *continue on error* until legacy `any`/quote issues in `page.tsx` are cleaned up. The build step needs **`NEXT_PUBLIC_SUPABASE_URL`** / **`NEXT_PUBLIC_SUPABASE_ANON_KEY`** as repo secrets — `next build` prerenders `/company-scraper`, which constructs a Supabase client at build time and fails without them.
- **Deploy** (push to `main` only, after both jobs above pass): SSHes into the production VM and redeploys. See **[Production deployment](#production-deployment)** below.

Workflow file: `.github/workflows/ci.yml`.

**Local parity** with the **required** GitHub checks (no strict lint):

```bash
make ci-check
```

Full local gate (**includes strict** `npm run lint`, which may fail until `page.tsx` ESLint issues are fixed):

```bash
make ci
```

## Production deployment

Live at **https://jobs.arkfarms.store**, served by a single GCP VM running Docker Compose (API on 8080, web on 3000) behind an Nginx + DNS setup configured directly on the VM (not tracked in this repo — see `deploy/README_GCE.md` for VM provisioning).

**Auto-deploy on push to `main`:** the `deploy` job in `.github/workflows/ci.yml` runs only after both the `python` and `dashboard` CI jobs pass. It SSHes into the VM and runs:

```bash
git reset --hard origin/main
docker compose up --build -d
curl -sf http://localhost:8080/api/health
```

**Manual approval gate:** the `deploy` job targets a GitHub `production` environment with a required-reviewer rule and admin-bypass disabled — so every deploy (including the maintainer's own pushes) pauses in the Actions UI until manually approved (**Actions → run → "Review pending deployments" → Approve and deploy**). This is a deliberate safety gate between "tests passed" and "code is live," not an oversight.

**One-time setup** (already done for this repo's VM, documented here in case the deploy target ever changes):
1. On the VM: generate a dedicated key (`ssh-keygen -t ed25519 -f ~/.ssh/gh_deploy_key`), append the `.pub` to `~/.ssh/authorized_keys`.
2. In GitHub repo secrets: `PROD_SSH_HOST`, `PROD_SSH_USER`, `PROD_SSH_KEY` (the dedicated private key, not a personal one), `PROD_APP_DIR` (path to the repo clone on the VM).
3. In `Settings → Environments → production`: enable **Required reviewers**, add an approver, and uncheck **"Allow administrators to bypass configured protection rules"** if you want the gate to apply to admins too (otherwise admins skip the approval step).

**Caveat:** `git reset --hard` on deploy discards any uncommitted changes on the VM (not `.env`, which is gitignored). Don't hand-edit files directly on the production VM expecting them to survive the next deploy.

## CLI options

```bash
# Discovery only: collect Yahoo URLs, no ATS page scrape
python find_and_scrape_jobs.py --dry-run
# Same via env
JOBSEARCH_DRY_RUN=1 python find_and_scrape_jobs.py
```

## Configuration

- **`JOBSEARCH_ROOT`** — override repository root when scripts cannot infer it.
- **`config.search`** — `country_phrase`, `include_remote_primary_boards`, `merge_previous_scrape`, optional `yahoo_site_templates` (list of format strings with `{title}` and `{country}`).

## Primary vs legacy UI

Use the **Next.js** app in `dashboard/` as the main control surface. The Python server still serves `index.html` at `http://localhost:8080/` for legacy use only.

## Security

Prefer `JOBSEARCH_WEBHOOK_URL` in `.env` over committing webhooks in `config.json`. The dashboard API masks the on-disk webhook in JSON when the env var is set.
