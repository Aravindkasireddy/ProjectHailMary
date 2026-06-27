"""Scrape MAAS-role jobs from OPT-friendly sponsor employers, output to CSV.

Standalone, exploratory tool — does NOT write to Supabase `public.jobs`
(the main pipeline's sole job-data store). It reuses the existing scraping
infrastructure rather than reimplementing it:

  - Employer source: `Opt_freindly/Gopall-OPT-Friendly-2 copy.xlsx` (the same
    file already one-time-ingested into Supabase's `h1b_sponsors` table via
    scripts/ingest_opt_friendly.py) — read directly here so this script has
    no Supabase/MAAS_USER_ID dependency and can run standalone.
  - ATS detection: company_scraper.detector.detect_ats()
  - Connectors: company_scraper.scrapers.{greenhouse,lever,workday,icims,generic}
    (same Greenhouse Job Board API / Lever postings API / Apify-backed
    generic connector the main pipeline uses — see CLAUDE.md "Scraping
    methods by source").
  - Role filtering: find_and_scrape_jobs.is_target_job() against
    config.json's target_titles (the same MAAS role-family list the main
    pipeline targets) — not a separate hardcoded keyword list.
  - Location filtering: new here (`is_target_location()`) — no equivalent
    existed elsewhere in the codebase to reuse.

Usage:
    python3 scripts/scrape_opt_sponsors_to_csv.py \
        [--sponsor-statuses "Strong Active Sponsor,Active but Selective"] \
        [--top-states CA,TX,NY,NJ,WA,MA,VA] \
        [--limit 50] [--sleep 1.5] [--output output/maas_roles_jobs.csv]
"""
from __future__ import annotations

import argparse
import csv
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import find_and_scrape_jobs as fasj  # noqa: E402 - reuse is_target_job, not reimplement
from company_scraper.detector import detect_ats  # noqa: E402
from company_scraper.scrapers import generic, greenhouse, icims, lever, workday  # noqa: E402

EXCEL_PATH = ROOT / "Opt_freindly" / "Gopall-OPT-Friendly-2 copy.xlsx"
CONFIG_PATH = ROOT / "config.json"
OUTPUT_FIELDS = [
    "employer_name",
    "sponsor_status",
    "opt_score",
    "trend",
    "top_state",
    "job_title",
    "job_location",
    "job_url",
    "source_ats",
    "scraped_at",
]

DEFAULT_SPONSOR_STATUSES = ["Strong Active Sponsor", "Active but Selective"]
_US_TERMS = ("united states", "usa", "u.s.", " us ", "us)", "(us")
_PREFERRED_STATE_NAMES = {
    "california", "texas", "new york", "new jersey", "washington",
    "massachusetts", "virginia",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("scrape_opt_sponsors")


def load_target_titles() -> list[str]:
    """Single source of truth: config.json's target_titles, same list the
    main pipeline already targets — not a separate hardcoded keyword set.
    """
    import json

    cfg = json.loads(CONFIG_PATH.read_text())
    titles = cfg.get("target_titles") or []
    if not titles:
        raise RuntimeError(f"config.json at {CONFIG_PATH} has no target_titles")
    return titles


def load_filtered_employers(
    sponsor_statuses: list[str],
    top_states: list[str] | None,
    limit: int | None,
) -> pd.DataFrame:
    df = pd.read_excel(EXCEL_PATH)
    df = df.dropna(subset=["Employer Name", "career_portal"])
    df = df[df["Sponsor Status"].isin(sponsor_statuses)]
    if top_states:
        df = df[df["Top State"].isin(top_states)]
    if limit:
        df = df.head(limit)
    return df


def is_target_location(location: str) -> bool:
    loc = (location or "").lower()
    if "remote" in loc:
        return True
    if any(term in loc for term in _US_TERMS) or loc.strip() == "us":
        return True
    return any(state in loc for state in _PREFERRED_STATE_NAMES)


def scrape_employer(careers_url: str, company_hint: str) -> tuple[list[dict], str]:
    """Dispatch to the same connector main.py uses for this ATS. Returns
    (jobs, ats_kind). Never raises - caller logs and continues on failure,
    per the brief's "robust error handling over silent failures."
    """
    ats = detect_ats(careers_url)
    try:
        if ats == "greenhouse":
            return greenhouse.fetch_jobs(careers_url, company_hint), ats
        if ats == "lever":
            return lever.fetch_jobs(careers_url, company_hint), ats
        if ats == "workday":
            return workday.fetch_jobs(careers_url, company_hint), ats
        if ats == "icims":
            return icims.fetch_jobs(careers_url, company_hint), ats
        return generic.fetch_jobs(careers_url, company_hint), ats
    except Exception as e:
        log.warning("scrape failed for %s (%s): %s", company_hint, careers_url, e)
        return [], ats


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sponsor-statuses", default=",".join(DEFAULT_SPONSOR_STATUSES))
    ap.add_argument("--top-states", default="", help="Comma-separated 2-letter state codes, e.g. CA,TX,NY")
    ap.add_argument("--limit", type=int, default=None, help="Max employers to process (omit for all)")
    ap.add_argument("--sleep", type=float, default=1.5, help="Seconds to sleep between employers")
    ap.add_argument("--output", default=str(ROOT / "output" / "maas_roles_jobs.csv"))
    args = ap.parse_args()

    sponsor_statuses = [s.strip() for s in args.sponsor_statuses.split(",") if s.strip()]
    top_states = [s.strip().upper() for s in args.top_states.split(",") if s.strip()] or None

    target_titles = load_target_titles()
    log.info("Target role families (from config.json): %s", target_titles)

    employers = load_filtered_employers(sponsor_statuses, top_states, args.limit)
    log.info(
        "Loaded %d employers (sponsor_statuses=%s, top_states=%s) with a career_portal URL.",
        len(employers), sponsor_statuses, top_states,
    )

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    total_jobs_written = 0
    total_employers_with_jobs = 0

    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()

        for i, (_, row) in enumerate(employers.iterrows(), start=1):
            employer_name = str(row["Employer Name"]).strip()
            career_portal = str(row["career_portal"]).strip()
            log.info("[%d/%d] %s -> %s", i, len(employers), employer_name, career_portal)

            jobs, ats = scrape_employer(career_portal, employer_name)
            log.info("  ats=%s scraped=%d", ats, len(jobs))

            kept = 0
            for job in jobs:
                title = job.get("job_title") or ""
                location = job.get("location_work_type") or ""
                if not fasj.is_target_job(title, target_titles):
                    continue
                if not is_target_location(location):
                    continue
                writer.writerow({
                    "employer_name": employer_name,
                    "sponsor_status": row.get("Sponsor Status"),
                    "opt_score": row.get("OPT-Friendly Hiring Score (0-100)"),
                    "trend": row.get("Trend Label"),
                    "top_state": row.get("Top State"),
                    "job_title": title,
                    "job_location": location,
                    "job_url": job.get("job_url"),
                    "source_ats": ats,
                    "scraped_at": datetime.now(timezone.utc).isoformat(),
                })
                kept += 1
            f.flush()  # crash-resilient: every employer's rows are durable immediately

            if kept:
                total_employers_with_jobs += 1
                total_jobs_written += kept
                log.info("  kept %d target-role job(s) for %s", kept, employer_name)

            if i < len(employers):
                time.sleep(args.sleep)

    log.info(
        "Done. %d target-role jobs from %d employers (of %d scraped) written to %s",
        total_jobs_written, total_employers_with_jobs, len(employers), out_path,
    )


if __name__ == "__main__":
    main()
