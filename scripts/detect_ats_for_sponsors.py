"""Detect and persist each OPT-friendly sponsor's ATS platform.

For every employer in `Opt_freindly/Gopall-OPT-Friendly-2 copy.xlsx` with a
`career_portal` URL, runs `company_scraper.detector.detect_ats()` (the same
detector the main pipeline and scrape_opt_sponsors_to_csv.py already use -
not reimplemented here) and writes the result to:

  - The Excel file itself (new `ats_platform` / `ats_platform_detected_at`
    columns), with a timestamped backup taken first.
  - Supabase's `h1b_sponsors` table (new `ats_platform` /
    `ats_platform_detected_at` columns - see supabase_h1b_ats_platform.sql),
    via a minimal upsert ({company_name, ats_platform, ats_platform_detected_at})
    so existing rich-metadata columns on each row are left untouched.

detect_ats() does a live HTTP GET for any host it doesn't recognize from the
URL alone (i.e. anything not greenhouse.io/lever.co/myworkdayjobs.com/
icims.com), so this is rate-limited between requests and supports --limit
for a small test batch before running against the full sponsor list.

Usage:
    python3 scripts/detect_ats_for_sponsors.py --limit 50 --sleep 1.0
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
from supabase_client import get_supabase_client  # noqa: E402

EXCEL_PATH = ROOT / "Opt_freindly" / "Gopall-OPT-Friendly-2 copy.xlsx"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("detect_ats_for_sponsors")


def backup_excel() -> Path:
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    backup_path = EXCEL_PATH.with_name(f"{EXCEL_PATH.stem}.bak-{ts}{EXCEL_PATH.suffix}")
    shutil.copy2(EXCEL_PATH, backup_path)
    return backup_path


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=50, help="Max companies to process (this run defaults to a small test batch)")
    ap.add_argument("--sleep", type=float, default=1.0, help="Seconds to sleep between detect_ats() calls")
    ap.add_argument("--skip-excel", action="store_true", help="Don't write back to the Excel file")
    ap.add_argument("--skip-supabase", action="store_true", help="Don't upsert into Supabase")
    ap.add_argument(
        "--sponsor-statuses",
        default="Strong Active Sponsor,Active but Selective",
        help="Comma-separated Sponsor Status values to include (empty string = no filter)",
    )
    ap.add_argument(
        "--skip-already-detected",
        action="store_true",
        default=True,
        help="Skip rows that already have an ats_platform value from a prior run (default: on)",
    )
    ap.add_argument("--no-skip-already-detected", dest="skip_already_detected", action="store_false")
    args = ap.parse_args()

    df = pd.read_excel(EXCEL_PATH)
    if "ats_platform" not in df.columns:
        df["ats_platform"] = pd.NA
    if "ats_platform_detected_at" not in df.columns:
        df["ats_platform_detected_at"] = pd.NA

    candidates = df[df["career_portal"].notna()]
    sponsor_statuses = [s.strip() for s in args.sponsor_statuses.split(",") if s.strip()]
    if sponsor_statuses:
        candidates = candidates[candidates["Sponsor Status"].isin(sponsor_statuses)]
    if args.skip_already_detected:
        already = candidates["ats_platform"].notna().sum()
        candidates = candidates[candidates["ats_platform"].isna()]
        if already:
            log.info("Skipping %d rows that already have an ats_platform value from a prior run.", already)
    if args.limit:
        candidates = candidates.head(args.limit)
    log.info(
        "Detecting ATS for %d companies (sponsor_statuses=%s, of %d total rows matching that filter with a career_portal URL).",
        len(candidates), sponsor_statuses or "ANY", df["career_portal"].notna().sum(),
    )

    supabase = None if args.skip_supabase else get_supabase_client()

    results = []
    for i, (idx, row) in enumerate(candidates.iterrows(), start=1):
        employer_name = str(row["Employer Name"]).strip()
        url = str(row["career_portal"]).strip()
        try:
            ats = detect_ats(url)
        except Exception as e:
            log.warning("detect_ats failed for %s (%s): %s", employer_name, url, e)
            ats = "generic"
        now = datetime.now(timezone.utc).isoformat()
        df.at[idx, "ats_platform"] = ats
        df.at[idx, "ats_platform_detected_at"] = now
        results.append((employer_name, url, ats))
        log.info("[%d/%d] %s -> %s (%s)", i, len(candidates), employer_name, ats, url)

        if supabase is not None:
            try:
                supabase.table("h1b_sponsors").upsert(
                    {"company_name": employer_name, "ats_platform": ats, "ats_platform_detected_at": now},
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
        log.info("Wrote ats_platform back to %s.", EXCEL_PATH)

    from collections import Counter
    counts = Counter(ats for _, _, ats in results)
    log.info("Done. ATS breakdown for this run: %s", dict(counts))


if __name__ == "__main__":
    main()
