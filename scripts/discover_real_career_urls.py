"""Discover real career URLs for OPT sponsor companies whose guessed
career_portal link was confirmed dead.

scripts/verify_career_portal_links.py found an 84% dead rate across the
filtered (Strong Active Sponsor / Active but Selective) scope - most
"guessed" links are slugified-company-name domains that were never
registered. This script attempts live discovery of each dead-link
company's REAL careers URL via company_scraper.discovery.find_careers_url()
(registry-first, then slug-guessing + Yahoo fallback - not reimplemented
here), which now includes two guards added after live testing surfaced
real false positives:
  - rejects parked/squatted domains returning a fake 200
    (_is_genuine_careers_page())
  - rejects a real-but-wrong-company careers page (the company-name
    verification in the same function)

Only rows where a URL is actually found get updated - a dead row that
stays NOT FOUND is left exactly as verify_career_portal_links.py already
marked it (career_portal_verified=False), never overwritten with a guess.

Usage:
    python3 scripts/discover_real_career_urls.py --limit 0 --sleep 0.5
"""
from __future__ import annotations

import argparse
import logging
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from company_scraper.detector import detect_ats  # noqa: E402
from company_scraper.discovery import find_careers_url  # noqa: E402
from supabase_client import get_supabase_client  # noqa: E402

EXCEL_PATH = ROOT / "Opt_freindly" / "Gopall-OPT-Friendly-2 copy.xlsx"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("discover_real_career_urls")


def backup_excel() -> Path:
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    backup_path = EXCEL_PATH.with_name(f"{EXCEL_PATH.stem}.bak-discover-{ts}{EXCEL_PATH.suffix}")
    shutil.copy2(EXCEL_PATH, backup_path)
    return backup_path


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=50, help="Max companies to process (0 = all)")
    ap.add_argument("--sleep", type=float, default=0.5, help="Seconds to sleep between companies")
    ap.add_argument("--skip-excel", action="store_true")
    ap.add_argument("--skip-supabase", action="store_true")
    ap.add_argument(
        "--sponsor-statuses",
        default="Strong Active Sponsor,Active but Selective",
        help="Comma-separated Sponsor Status values to include (empty string = no filter)",
    )
    args = ap.parse_args()

    df = pd.read_excel(EXCEL_PATH)
    if "career_portal_discovered_at" not in df.columns:
        df["career_portal_discovered_at"] = pd.NA

    sponsor_statuses = [s.strip() for s in args.sponsor_statuses.split(",") if s.strip()]
    candidates = df[df["career_portal_verified"] == False]  # noqa: E712
    if sponsor_statuses:
        candidates = candidates[candidates["Sponsor Status"].isin(sponsor_statuses)]
    if args.limit:
        candidates = candidates.head(args.limit)
    log.info("Attempting live discovery for %d companies with a confirmed-dead career_portal link.", len(candidates))

    supabase = None if args.skip_supabase else get_supabase_client()

    found_count = 0
    not_found_count = 0
    for i, (idx, row) in enumerate(candidates.iterrows(), start=1):
        employer_name = str(row["Employer Name"]).strip()
        errors: list[str] = []
        try:
            real_url = find_careers_url(employer_name, errors)
        except Exception as e:
            log.warning("find_careers_url crashed for %s: %s", employer_name, e)
            real_url = None

        now = datetime.now(timezone.utc).isoformat()
        if real_url:
            ats = None
            try:
                ats = detect_ats(real_url)
            except Exception:
                pass
            df.at[idx, "career_portal"] = real_url
            df.at[idx, "career_portal_verified"] = True
            df.at[idx, "career_portal_verified_at"] = now
            df.at[idx, "career_portal_discovered_at"] = now
            if ats:
                df.at[idx, "ats_platform"] = ats
            found_count += 1
            log.info("[%d/%d] %s -> FOUND: %s (%s)", i, len(candidates), employer_name, real_url, ats)

            if supabase is not None:
                try:
                    supabase.table("h1b_sponsors").upsert(
                        {
                            "company_name": employer_name,
                            "career_portal": real_url,
                            "career_portal_verified": True,
                            "career_portal_verified_at": now,
                            "ats_platform": ats,
                        },
                        on_conflict="company_name",
                    ).execute()
                except Exception as e:
                    log.warning("Supabase upsert failed for %s: %s", employer_name, e)
        else:
            not_found_count += 1
            log.info("[%d/%d] %s -> NOT FOUND (%s)", i, len(candidates), employer_name, errors[:1])

        if i < len(candidates):
            time.sleep(args.sleep)

    if not args.skip_excel:
        backup_path = backup_excel()
        log.info("Backed up Excel file to %s before writing.", backup_path)
        df.to_excel(EXCEL_PATH, index=False)
        log.info("Wrote discovered career_portal URLs back to %s.", EXCEL_PATH)

    log.info("Done. %d found, %d not found (of %d attempted).", found_count, not_found_count, found_count + not_found_count)


if __name__ == "__main__":
    main()
