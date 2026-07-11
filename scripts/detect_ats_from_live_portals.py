"""
Scan OPT-sponsor companies whose career_portal is live-verified but
ats_platform='generic', fetch the page, and detect the real ATS.

For detected Workday/Greenhouse/Lever/Ashby/SmartRecruiters portals,
extract the board slug/URL and add to config.json.

Usage:
    python3 scripts/detect_ats_from_live_portals.py [--dry-run] [--workers 10] [--limit 0]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from company_scraper.http_utils import request_with_retry  # noqa: E402

EXCEL_PATH = ROOT / "Opt_freindly" / "Gopall-OPT-Friendly-2 copy.xlsx"
CONFIG_PATH = ROOT / "config.json"

TARGET_STATUSES = {"Strong Active Sponsor", "Active but Selective"}

# ATS URL pattern extractors
_GH_RE   = re.compile(r'https?://(?:boards\.greenhouse\.io/([^/\s\'"<>?#]+)|([a-z0-9-]+)\.greenhouse\.io)', re.I)
_LV_RE   = re.compile(r'https?://jobs\.lever\.co/([^/\s\'"<>?#]+)', re.I)
_ASH_RE  = re.compile(r'https?://jobs\.ashbyhq\.com/([^/\s\'"<>?#]+)', re.I)
_WD_RE   = re.compile(r'https?://[a-zA-Z0-9._-]+\.(?:myworkdayjobs|myworkdaysite)\.com/[^\s\'"<>]*', re.I)
_SR_RE   = re.compile(r'https?://careers\.smartrecruiters\.com/([^/\s\'"<>?#]+)', re.I)


def _extract_slugs(html: str, portal_url: str) -> dict:
    """Return dict of ats -> slug/url found in page HTML."""
    results = {}

    m = _WD_RE.search(html)
    if m:
        url = m.group(0).rstrip("/?,;")
        # Normalize to board root (drop /job/ sub-paths)
        parts = url.split("/job/")
        results["workday"] = parts[0].rstrip("/")

    m = _GH_RE.search(html)
    if m:
        slug = (m.group(1) or m.group(2) or "").lower().strip()
        if slug:
            results["greenhouse"] = slug

    m = _LV_RE.search(html)
    if m:
        results["lever"] = m.group(1).lower().strip()

    m = _ASH_RE.search(html)
    if m:
        results["ashby"] = m.group(1).strip()

    m = _SR_RE.search(html)
    if m:
        results["smartrecruiters"] = m.group(1).strip()

    return results


def probe_company(row) -> dict | None:
    """Fetch career portal and detect ATS. Returns result dict or None."""
    url = str(row.get("career_portal") or "").strip()
    name = str(row.get("Employer Name") or "").strip()
    if not url or not url.startswith("http"):
        return None

    try:
        resp = request_with_retry(url, timeout=10)
        if not resp or resp.status_code >= 400:
            return None
        html = resp.text
        slugs = _extract_slugs(html, url)
        if slugs:
            return {"company": name, "portal": url, "found": slugs}
    except Exception:
        pass
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--limit", type=int, default=0, help="Max companies to probe (0=all)")
    args = ap.parse_args()

    df = pd.read_excel(EXCEL_PATH)
    df_target = df[
        df["Sponsor Status"].isin(TARGET_STATUSES) &
        (df["ats_platform"] == "generic") &
        (df["career_portal_verified"] == True)
    ].copy()

    rows = df_target.to_dict("records")
    if args.limit:
        rows = rows[:args.limit]

    print(f"Probing {len(rows)} live generic portals with {args.workers} workers...")

    findings: list[dict] = []
    done = 0

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(probe_company, r): r for r in rows}
        for fut in as_completed(futures):
            done += 1
            result = fut.result()
            if result:
                findings.append(result)
                print(f"  [{done}/{len(rows)}] FOUND {result['company']}: {result['found']}")
            elif done % 50 == 0:
                print(f"  [{done}/{len(rows)}] ...")

    print(f"\nFound ATS on {len(findings)} / {len(rows)} companies\n")

    # Tally by ATS
    from collections import Counter, defaultdict
    by_ats: dict[str, list] = defaultdict(list)
    for f in findings:
        for ats, slug in f["found"].items():
            by_ats[ats].append((f["company"], slug))

    for ats, items in by_ats.items():
        print(f"{ats.upper()} ({len(items)} new):")
        for company, slug in items[:10]:
            print(f"  {company[:40]:40} {slug}")
        if len(items) > 10:
            print(f"  ... and {len(items)-10} more")
        print()

    if args.dry_run:
        print("--dry-run: config.json not updated.")
        return

    # Merge into config.json
    cfg = json.loads(CONFIG_PATH.read_text())

    added: dict[str, list] = {ats: [] for ats in ["greenhouse", "lever", "ashby", "workday", "smartrecruiters"]}
    existing = {ats: set(cfg["target_companies"].get(ats, [])) for ats in added}

    for ats, items in by_ats.items():
        if ats not in added:
            continue
        for company, slug in items:
            if slug and slug not in existing[ats]:
                added[ats].append(slug)
                existing[ats].add(slug)

    total_added = sum(len(v) for v in added.values())
    if total_added == 0:
        print("Nothing new to add to config.json.")
        return

    for ats, slugs in added.items():
        if slugs:
            cfg["target_companies"][ats] = sorted(
                set(cfg["target_companies"].get(ats, [])) | set(slugs)
            )

    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))
    print(f"config.json updated — {total_added} new entries:")
    for ats, slugs in added.items():
        if slugs:
            before = len(cfg["target_companies"][ats]) - len(slugs)
            print(f"  {ats}: {before} → {before + len(slugs)}")


if __name__ == "__main__":
    main()
