# Gemini-jobsearch (MAAS job sourcing)

Single **monorepo**: Python sourcing pipeline + **`dashboard/`** Next.js UI. Discovery targets US roles (remote, hybrid, or onsite), optional Notion sync and Discord/Slack webhooks.

## Layout

| Path | Purpose |
|------|---------|
| `find_and_scrape_jobs.py` | Yahoo `site:` discovery + ATS scrape → `scraped_jobs.json` |
| `scripts/scrape_and_filter_candidates.py` | Re-scrape / validate + red-flag prefilter → `active_candidate_jobs.json`, `failed_candidate_jobs.json` |
| `scripts/classify_and_save.py` | Gemini (optional) + rules → `approved_jobs.json` |
| `dashboard_server.py` | API on **port 8080**, scheduler, Notion + webhook helpers |
| `dashboard/` | Next.js UI (default **port 3000**) |
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

## Quick start

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

   Set `NEXT_PUBLIC_API_URL=http://localhost:8080` in `dashboard/.env.local` if the API is not on localhost.

## Pipeline stages

1. `find_and_scrape_jobs.py` — writes `scraped_jobs.json` (with optional merge of previous file; see `config.search.merge_previous_scrape`).
2. `scripts/scrape_and_filter_candidates.py` — refreshes postings and applies regex red-flag gates.
3. `scripts/classify_and_save.py` — applies `candidate_jobs.json` overrides when present, else Gemini / keyword classifier.

Logs append to `logs/pipeline.log` (server runs) and `logs/scrape.log` (discovery script).

## Pipeline runner (local)

From the **repository root**, run the same three stages as the dashboard scraper (stops on first failure):

```bash
chmod +x scripts/run_pipeline.sh   # once
./scripts/run_pipeline.sh
```

Or with **Make**:

```bash
make pipeline          # uses the shell script
make pipeline-py       # same steps, invoked directly by Make
```

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
- **Dashboard:** `npm ci`, **`npm run build`** (required). **`npm run lint`** runs in CI with *continue on error* until legacy `any`/quote issues in `page.tsx` are cleaned up.

Workflow file: `.github/workflows/ci.yml`.

**Local parity** with the **required** GitHub checks (no strict lint):

```bash
make ci-check
```

Full local gate (**includes strict** `npm run lint`, which may fail until `page.tsx` ESLint issues are fixed):

```bash
make ci
```

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
