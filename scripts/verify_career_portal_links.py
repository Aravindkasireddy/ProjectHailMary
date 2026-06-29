"""Verify each OPT-friendly sponsor's career_portal link is actually live.

97% of career_portal/linkedin_account links in
`Opt_freindly/Gopall-OPT-Friendly-2 copy.xlsx` have `link_data_source ==
"guessed"` (not scraped from a real page) - confirmed in the original sheet
analysis. A guessed link can be dead, parked, or simply wrong, which directly
hurts scrape_opt_sponsors_to_csv.py's yield (a dead career_portal URL means
zero jobs for that employer, indistinguishable from "this employer has no
open roles right now").

For every employer in the filtered scope with a career_portal URL, runs
company_scraper.http_utils.head_ok() (the same HEAD-then-GET-fallback liveness
check already used elsewhere in this codebase - not reimplemented) and writes
the result to:

  - The Excel file itself (new career_portal_verified /
    career_portal_verified_at columns), with a timestamped backup taken first.
  - Supabase's h1b_sponsors table (same two new columns - see
    supabase_h1b_link_verification.sql), via a minimal
    {company_name, career_portal_verified, career_portal_verified_at}
    upsert so existing rich-metadata columns are left untouched.

Usage:
    python3 scripts/verify_career_portal_links.py --limit 50 --sleep 1.0
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

from company_scraper.http_utils import head_ok  # noqa: E402
from supabase_client import get_supabase_client  # noqa: E402

EXCEL_PATH = ROOT / "Opt_freindly" / "Gopall-OPT-Friendly-2 copy.xlsx"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("verify_career_portal_links")


def backup_excel() -> Path:
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    backup_path = EXCEL_PATH.with_name(f"{EXCEL_PATH.stem}.bak-{ts}{EXCEL_PATH.suffix}")
    shutil.copy2(EXCEL_PATH, backup_path)
    return backup_path


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=50, help="Max companies to process (this run defaults to a small test batch)")
    ap.add_argument("--sleep", type=float, default=1.0, help="Seconds to sleep between head_ok() calls")
    ap.add_argument("--skip-excel", action="store_true", help="Don't write back to the Excel file")
    ap.add_argument("--skip-supabase", action="store_true", help="Don't upsert into Supabase")
    ap.add_argument(
        "--sponsor-statuses",
        default="Strong Active Sponsor,Active but Selective",
        help="Comma-separated Sponsor Status values to include (empty string = no filter)",
    )
    ap.add_argument(
        "--skip-already-verified",
        action="store_true",
        default=True,
        help="Skip rows that already have a career_portal_verified value from a prior run (default: on)",
    )
    ap.add_argument("--no-skip-already-verified", dest="skip_already_verified", action="store_false")
    args = ap.parse_args()

    df = pd.read_excel(EXCEL_PATH)
    if "career_portal_verified" not in df.columns:
        df["career_portal_verified"] = pd.NA
    if "career_portal_verified_at" not in df.columns:
        df["career_portal_verified_at"] = pd.NA

    candidates = df[df["career_portal"].notna()]
    sponsor_statuses = [s.strip() for s in args.sponsor_statuses.split(",") if s.strip()]
    if sponsor_statuses:
        candidates = candidates[candidates["Sponsor Status"].isin(sponsor_statuses)]
    if args.skip_already_verified:
        already = candidates["career_portal_verified"].notna().sum()
        candidates = candidates[candidates["career_portal_verified"].isna()]
        if already:
            log.info("Skipping %d rows already verified in a prior run.", already)
    if args.limit:
        candidates = candidates.head(args.limit)
    log.info("Verifying career_portal links for %d companies (sponsor_statuses=%s).", len(candidates), sponsor_statuses or "ANY")

    supabase = None if args.skip_supabase else get_supabase_client()

    live_count = 0
    dead_count = 0
    for i, (idx, row) in enumerate(candidates.iterrows(), start=1):
        employer_name = str(row["Employer Name"]).strip()
        url = str(row["career_portal"]).strip()
        try:
            is_live = head_ok(url)
        except Exception as e:
            log.warning("head_ok failed for %s (%s): %s", employer_name, url, e)
            is_live = False
        now = datetime.now(timezone.utc).isoformat()
        df.at[idx, "career_portal_verified"] = is_live
        df.at[idx, "career_portal_verified_at"] = now
        if is_live:
            live_count += 1
        else:
            dead_count += 1
        log.info("[%d/%d] %s -> %s (%s)", i, len(candidates), employer_name, "LIVE" if is_live else "DEAD/UNREACHABLE", url)

        if supabase is not None:
            try:
                supabase.table("h1b_sponsors").upsert(
                    {"company_name": employer_name, "career_portal_verified": is_live, "career_portal_verified_at": now},
                    on_conflict="company_name",
                ).execute()
            except Exception as e:
                log.warning("Supabase upsert failed for %s: %s", employer_name, e)

        if i < len(candidates):
            time.sleep(args.sleep)

    if not args.skip_excel:
        backup_path = backup_excel()
        log.info("Backed up Excel file to %s before writing.", backup_path)
        df.to_excel(EXCEL_PATH, index=False)
        log.info("Wrote career_portal_verified back to %s.", EXCEL_PATH)

    log.info("Done. %d live, %d dead/unreachable (of %d checked).", live_count, dead_count, live_count + dead_count)


if __name__ == "__main__":
    main()
