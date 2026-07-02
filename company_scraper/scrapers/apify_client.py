"""Thin wrapper around the Apify platform for HTML-level scrapers (generic career sites).

Only used when ``APIFY_API_TOKEN`` is set; callers must fall back to local
Playwright/BeautifulSoup scraping when it's absent or a run fails.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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

# Hostname patterns for the platforms GENERIC_JOBS_ACTOR actually supports
# (Greenhouse/Lever/Workday already have their own direct-API or dedicated-actor
# paths and never reach this check; this only matters for the "generic" bucket).
# Confirmed live 2026-06-22: calling the actor against an unsupported host (e.g.
# a Salesforce-style custom careers site) logs "Skipping unsupported URL" and
# returns 0 items every time, burning a full run of the daily Apify quota for
# nothing. Checking the host first lets generic.py skip straight to local
# Playwright for those instead of paying for a call that can never succeed.
_SUPPORTED_GENERIC_HOST_PATTERNS = (
    re.compile(r"\.bamboohr\.com$", re.I),
    re.compile(r"\.applytojob\.com$", re.I),  # JazzHR
    re.compile(r"\.jazz\.co$", re.I),
    re.compile(r"\.personio\.(com|de)$", re.I),
    re.compile(r"\.recruitee\.com$", re.I),
    re.compile(r"ats\.rippling\.com$", re.I),
    re.compile(r"\.rivalapp\.com$", re.I),
    re.compile(r"\.teamtailor\.com$", re.I),
    re.compile(r"(^|\.)join\.com$", re.I),
    re.compile(r"\.ashbyhq\.com$", re.I),
    re.compile(r"\.myworkdayjobs\.com$", re.I),
    re.compile(r"\.myworkdaysite\.com$", re.I),
    re.compile(r"\.greenhouse\.io$", re.I),
    re.compile(r"\.lever\.co$", re.I),
)


def is_configured() -> bool:
    return bool((os.environ.get("APIFY_API_TOKEN") or "").strip())


def generic_actor_likely_supports(url: str) -> bool:
    """Best-effort check of whether GENERIC_JOBS_ACTOR's supported-platform list
    is likely to recognize this URL's host, to avoid burning Apify quota on a
    call that's certain to return 0 items (e.g. Salesforce's custom careers site).

    This is intentionally conservative in the *permissive* direction: an
    unrecognized-but-actually-supported host just costs one wasted call (same
    as today, no regression); a recognized host always gets the Apify attempt.
    """
    try:
        host = (urlparse(url).netloc or "").lower()
    except Exception:
        return True
    if not host:
        return True
    return any(p.search(host) for p in _SUPPORTED_GENERIC_HOST_PATTERNS)


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


def get_usage_summary() -> dict[str, Any]:
    """Read-only snapshot of today's Apify run count for dashboard display."""
    cap = _max_runs_per_day()
    today = _today_key()
    runs_today = 0
    try:
        if _USAGE_FILE.exists():
            data = json.loads(_USAGE_FILE.read_text() or "{}")
            runs_today = int(data.get(today, 0))
    except Exception as e:
        log.warning("apify usage read failed: %s", e)
    return {
        "configured": is_configured(),
        "date": today,
        "runs_today": runs_today,
        "max_runs_per_day": cap,
    }


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


def _resolve_workday_board_url(careers_url: str) -> str:
    """
    If careers_url is a custom company domain (e.g. careers.usaa.com), fetch the
    page and extract the embedded myworkdayjobs.com board URL from links/iframes/scripts.
    Returns the resolved myworkdayjobs.com URL, or the original URL if not found.
    The Apify Workday actor requires a myworkdayjobs.com URL — custom domains fail silently.
    """
    from urllib.parse import urlparse
    import re as _re

    host = urlparse(careers_url).netloc.lower()
    if "myworkdayjobs.com" in host or "myworkdaysite.com" in host:
        return careers_url  # already a native Workday URL

    try:
        from company_scraper.http_utils import request_with_retry
        r = request_with_retry("GET", careers_url, timeout=15, max_attempts=2)
        text = r.text or ""
        # Look for myworkdayjobs.com board URLs embedded in HTML
        matches = _re.findall(
            r'https?://[a-zA-Z0-9._-]+\.(?:myworkdayjobs|myworkdaysite)\.com/[^\s\'"<>]+',
            text
        )
        if matches:
            # Prefer board-level URLs (no /job/ in path) over individual job links
            board_urls = [m for m in matches if "/job/" not in m.lower()]
            best = (board_urls or matches)[0].rstrip("/?,;")
            logging.getLogger("company_scraper").info(
                "Resolved Workday board URL: %s -> %s", careers_url, best
            )
            return best
    except Exception as e:
        logging.getLogger("company_scraper").debug(
            "Workday board URL resolution failed for %s: %s", careers_url, e
        )
    return careers_url


def fetch_workday_jobs_via_apify(
    careers_url: str, company_hint: str = "", max_jobs: int = 500
) -> list[dict[str, Any]]:
    """Run the dedicated Workday jobs actor against a myworkdayjobs.com /
    myworkdaysite.com careers URL. Same output shape as ``fetch_jobs_via_apify``.
    Automatically resolves custom company domains to their myworkdayjobs.com
    board URL before calling the actor (custom domains fail silently in Apify).
    """
    resolved_url = _resolve_workday_board_url(careers_url)
    items = run_actor(
        WORKDAY_JOBS_ACTOR,
        {"startUrls": [resolved_url], "maxJobsPerUrl": max_jobs},
    )
    return _normalize_items(items, company_hint)
