"""Scrape MAAS-role jobs from OPT-friendly sponsor employers, output to CSV.

Standalone, exploratory tool — does NOT write to Supabase `public.jobs`
(the main pipeline's sole job-data store). It reuses the existing scraping
infrastructure rather than reimplementing it:

  - Employer source: `Opt_freindly/Gopall-OPT-Friendly-2 copy.xlsx` (the same
    file already one-time-ingested into Supabase's `h1b_sponsors` table via
    scripts/ingest_opt_friendly.py) — read directly here so this script has
    no Supabase/MAAS_USER_ID dependency by default and can run standalone.
  - ATS dispatch (2026-06-28 update): each employer's `ats_platform` was
    already detected and persisted (Excel + Supabase, via
    scripts/detect_ats_for_sponsors.py) for the 3,204-row Strong Active
    Sponsor / Active but Selective scope. This script now reads that
    column and dispatches straight to the matching connector
    (Greenhouse/Lever/Workday/iCIMS public APIs) instead of re-running
    detect_ats()'s live HTTP probe for every employer on every run.
    detect_ats() is only called as a fallback when `ats_platform` is
    null/empty for a given row (e.g. employers outside that already-
    detected scope, or a future Excel refresh that hasn't been re-run
    through detect_ats_for_sponsors.py yet).
  - Connectors: company_scraper.scrapers.{greenhouse,lever,workday,icims,generic}
    (same Greenhouse Job Board API / Lever postings API / Apify-backed
    generic connector the main pipeline uses — see CLAUDE.md "Scraping
    methods by source"). A specialized connector failure (bad client slug,
    404, unexpected JSON, etc.) logs a warning and falls back to the
    generic connector for that one employer — never crashes the run.
  - Role filtering: find_and_scrape_jobs.is_target_job() against
    config.json's target_titles (the same MAAS role-family list the main
    pipeline targets) — not a separate hardcoded keyword list. Connectors
    only fetch jobs; they never decide role relevance themselves, so this
    one shared matcher is the single place that judgment is made.
  - Location filtering: `is_target_location()` — no equivalent existed
    elsewhere in the codebase to reuse.

Usage:
    python3 scripts/scrape_opt_sponsors_to_csv.py \
        [--sponsor-statuses "Strong Active Sponsor,Active but Selective"] \
        [--top-states CA,TX,NY,NJ,WA,MA,VA] \
        [--limit 50] [--sleep 1.5] [--output output/maas_roles_jobs.csv] \
        [--source excel|supabase]
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
    "ats_platform",
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

# Connectors with a dedicated fetch_jobs(careers_url, company_hint) for a
# specific ATS - dispatched to directly when ats_platform names one of
# these. Anything else (including "generic" or an unrecognized value)
# falls through to the generic connector below. Stored as modules (not
# bound functions) and looked up via getattr() at call time, so tests can
# monkeypatch e.g. workday.fetch_jobs after import and have it take effect.
_SPECIALIZED_CONNECTOR_MODULES = {
    "greenhouse": greenhouse,
    "lever": lever,
    "workday": workday,
    "icims": icims,
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


def load_ats_platform_from_supabase(company_names: list[str]) -> dict[str, str]:
    """Bulk-fetch {company_name: ats_platform} from Supabase's h1b_sponsors
    table (populated by scripts/detect_ats_for_sponsors.py). Only imported/
    called when --source supabase is passed - the default Excel-only path
    never touches Supabase, preserving this script's standalone behavior.
    """
    from supabase_client import get_supabase_client

    supabase = get_supabase_client()
    out: dict[str, str] = {}
    limit = 1000
    offset = 0
    while True:
        res = (
            supabase.table("h1b_sponsors")
            .select("company_name,ats_platform")
            .range(offset, offset + limit - 1)
            .execute()
        )
        if not res.data:
            break
        for r in res.data:
            if r.get("ats_platform"):
                out[r["company_name"]] = r["ats_platform"]
        if len(res.data) < limit:
            break
        offset += limit
    return out


def load_filtered_employers(
    sponsor_statuses: list[str],
    top_states: list[str] | None,
    limit: int | None,
    source: str = "excel",
) -> pd.DataFrame:
    df = pd.read_excel(EXCEL_PATH)
    df = df.dropna(subset=["Employer Name", "career_portal"])
    df = df[df["Sponsor Status"].isin(sponsor_statuses)]
    if top_states:
        df = df[df["Top State"].isin(top_states)]
    if "ats_platform" not in df.columns:
        df["ats_platform"] = pd.NA

    if source == "supabase":
        names = df["Employer Name"].astype(str).str.strip().tolist()
        ats_map = load_ats_platform_from_supabase(names)
        log.info("Loaded ats_platform for %d companies from Supabase h1b_sponsors.", len(ats_map))
        df = df.copy()
        df["ats_platform"] = df["Employer Name"].astype(str).str.strip().map(ats_map).combine_first(df["ats_platform"])

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


def scrape_employer(careers_url: str, company_hint: str, known_ats: str | None) -> tuple[list[dict], str]:
    """Dispatch by ats_platform (falling back to a live detect_ats() probe
    only when known_ats is null/empty). Returns (jobs, ats_used) where
    ats_used is the connector that actually produced the result - usually
    equal to known_ats, but "generic" if a specialized connector failed and
    we fell back. Never raises - caller logs and continues on failure, per
    the brief's "robust error handling over silent failures."
    """
    ats = (known_ats or "").strip().lower() or None
    if not ats:
        ats = detect_ats(careers_url)
        log.info("  ats_platform missing for %s - fell back to detect_ats() -> %s", company_hint, ats)

    module = _SPECIALIZED_CONNECTOR_MODULES.get(ats)
    if module is not None:
        try:
            return module.fetch_jobs(careers_url, company_hint), ats
        except Exception as e:
            log.warning(
                "Specialized %s connector failed for %s (%s): %s - falling back to generic connector.",
                ats, company_hint, careers_url, e,
            )
            # fall through to the generic connector below

    try:
        return generic.fetch_jobs(careers_url, company_hint), (ats if module is None else "generic")
    except Exception as e:
        log.warning("Generic connector failed for %s (%s): %s", company_hint, careers_url, e)
        return [], ats


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sponsor-statuses", default=",".join(DEFAULT_SPONSOR_STATUSES))
    ap.add_argument("--top-states", default="", help="Comma-separated 2-letter state codes, e.g. CA,TX,NY")
    ap.add_argument("--limit", type=int, default=None, help="Max employers to process (omit for all)")
    ap.add_argument("--sleep", type=float, default=1.5, help="Seconds to sleep between employers")
    ap.add_argument("--output", default=str(ROOT / "output" / "maas_roles_jobs.csv"))
    ap.add_argument(
        "--source", choices=["excel", "supabase"], default="excel",
        help="Where to read ats_platform from. 'excel' (default) reads the column already in the "
             "spreadsheet - no Supabase dependency. 'supabase' bulk-fetches the live h1b_sponsors "
             "table instead (useful if Supabase has been re-detected more recently than this Excel snapshot).",
    )
    args = ap.parse_args()

    sponsor_statuses = [s.strip() for s in args.sponsor_statuses.split(",") if s.strip()]
    top_states = [s.strip().upper() for s in args.top_states.split(",") if s.strip()] or None

    target_titles = load_target_titles()
    log.info("Target role families (from config.json): %s", target_titles)

    employers = load_filtered_employers(sponsor_statuses, top_states, args.limit, source=args.source)
    log.info(
        "Loaded %d employers (sponsor_statuses=%s, top_states=%s, source=%s) with a career_portal URL.",
        len(employers), sponsor_statuses, top_states, args.source,
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
            known_ats = row.get("ats_platform")
            known_ats = None if pd.isna(known_ats) else str(known_ats).strip()
            log.info("[%d/%d] %s -> %s (ats_platform=%s)", i, len(employers), employer_name, career_portal, known_ats or "unset")

            jobs, ats_used = scrape_employer(career_portal, employer_name, known_ats)
            log.info("  ats_used=%s scraped=%d", ats_used, len(jobs))

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
                    "ats_platform": known_ats or "",
                    "job_title": title,
                    "job_location": location,
                    "job_url": job.get("job_url"),
                    "source_ats": ats_used,
                    "scraped_at": datetime.now(timezone.utc).isoformat(),
                })
                kept += 1
            f.flush()  # crash-resilient: every employer's rows are durable immediately

            if kept:
                total_employers_with_jobs += 1
                total_jobs_written += kept
                log.info("  kept %d target-role job(s) for %s", kept, employer_name)
            elif not jobs:
                log.info("  no jobs scraped for %s (logged, not silently skipped)", employer_name)

            if i < len(employers):
                time.sleep(args.sleep)

    log.info(
        "Done. %d target-role jobs from %d employers (of %d scraped) written to %s",
        total_jobs_written, total_employers_with_jobs, len(employers), out_path,
    )


if __name__ == "__main__":
    main()
