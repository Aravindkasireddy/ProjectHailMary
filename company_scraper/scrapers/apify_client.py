"""Thin wrapper around the Apify platform for HTML-level scrapers (generic career sites).

Only used when ``APIFY_API_TOKEN`` is set; callers must fall back to local
Playwright/BeautifulSoup scraping when it's absent or a run fails.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("company_scraper.apify")

# Simple spend guardrail: cap Apify actor runs per UTC day. Each run can still
# return many jobs, so this bounds *call count*, not job volume — intentionally
# coarse, just enough to stop a runaway scheduler loop from burning budget.
_DEFAULT_MAX_RUNS_PER_DAY = 200
_USAGE_FILE = Path(__file__).resolve().parent.parent.parent / "logs" / "apify_usage.json"

# fantastic-jobs/jobs-scraper: standardized job output across 12 ATS platforms
# (Ashby, BambooHR, Greenhouse, Lever, Workday, Personio, Recruitee, ...).
GENERIC_JOBS_ACTOR = "fantastic-jobs/jobs-scraper"

# fantastic-jobs/workday-jobs-scraper: same vendor/schema as GENERIC_JOBS_ACTOR,
# dedicated to myworkdayjobs.com / myworkdaysite.com career sites. 100% success
# rate vs. 59-73% for other Workday actors on Apify Store as of 2026-06.
WORKDAY_JOBS_ACTOR = "fantastic-jobs/workday-jobs-scraper"


def is_configured() -> bool:
    return bool((os.environ.get("APIFY_API_TOKEN") or "").strip())


def _max_runs_per_day() -> int:
    raw = (os.environ.get("APIFY_MAX_RUNS_PER_DAY") or "").strip()
    if not raw:
        return _DEFAULT_MAX_RUNS_PER_DAY
    try:
        return int(raw)
    except ValueError:
        return _DEFAULT_MAX_RUNS_PER_DAY


def _today_key() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def _check_and_increment_daily_usage() -> None:
    """Raise if today's Apify run count is already at/over the cap; else record one more run.

    Best-effort: any I/O failure on the usage file is swallowed so it never
    blocks a scrape — this is a soft guardrail, not a hard billing control.
    """
    cap = _max_runs_per_day()
    today = _today_key()
    try:
        _USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = {}
        if _USAGE_FILE.exists():
            data = json.loads(_USAGE_FILE.read_text() or "{}")
        count = int(data.get(today, 0))
        if count >= cap:
            raise RuntimeError(
                f"Apify daily run cap reached ({count}/{cap} runs today, APIFY_MAX_RUNS_PER_DAY)"
            )
        data = {today: count + 1}  # only keep today's counter; old days are irrelevant
        _USAGE_FILE.write_text(json.dumps(data))
    except RuntimeError:
        raise
    except Exception as e:
        log.warning("apify usage tracking failed (continuing without cap): %s", e)


def run_actor(actor_id: str, run_input: dict[str, Any], *, timeout_secs: int = 180) -> list[dict[str, Any]]:
    """Run an Apify actor to completion and return its dataset items.

    Raises on any failure (including the daily run cap) — callers are
    expected to catch and fall back to local scraping.
    """
    from apify_client import ApifyClient

    token = (os.environ.get("APIFY_API_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("APIFY_API_TOKEN not set")

    _check_and_increment_daily_usage()

    client = ApifyClient(token)
    run = client.actor(actor_id).call(run_input=run_input, timeout_secs=timeout_secs)
    if not run or not run.get("defaultDatasetId"):
        raise RuntimeError(f"Apify actor {actor_id} returned no dataset")
    items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
    log.info("apify actor=%s items=%d", actor_id, len(items))
    return items


def _normalize_items(items: list[dict[str, Any]], company_hint: str) -> list[dict[str, Any]]:
    """Map fantastic-jobs actor output (title/description/locations/url/date_posted)
    onto this project's job-row shape."""
    rows: list[dict[str, Any]] = []
    for it in items:
        url = (it.get("url") or "").strip()
        if not url:
            continue
        locations = it.get("locations") or []
        loc = ", ".join(str(l) for l in locations if l) if isinstance(locations, list) else str(locations or "")
        rows.append(
            {
                "job_url": url,
                "job_title": (it.get("title") or "Job posting").strip(),
                "company_name": company_hint or "",
                "job_description": it.get("description") or "",
                "location_work_type": loc or "Remote",
                "requirement_id": "",
            }
        )
    return rows


def fetch_jobs_via_apify(
    careers_url: str, company_hint: str = "", max_jobs: int = 40
) -> list[dict[str, Any]]:
    """Run the generic multi-ATS jobs actor against a single careers URL.

    Returns rows already normalized to this project's job-row shape
    (job_url, job_title, company_name, job_description, location_work_type, requirement_id).
    """
    items = run_actor(
        GENERIC_JOBS_ACTOR,
        {"startUrls": [careers_url], "maxJobsPerUrl": max_jobs},
    )
    return _normalize_items(items, company_hint)


def fetch_workday_jobs_via_apify(
    careers_url: str, company_hint: str = "", max_jobs: int = 500
) -> list[dict[str, Any]]:
    """Run the dedicated Workday jobs actor against a myworkdayjobs.com /
    myworkdaysite.com careers URL. Same output shape as ``fetch_jobs_via_apify``.
    """
    items = run_actor(
        WORKDAY_JOBS_ACTOR,
        {"startUrls": [careers_url], "maxJobsPerUrl": max_jobs},
    )
    return _normalize_items(items, company_hint)
