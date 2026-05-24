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
