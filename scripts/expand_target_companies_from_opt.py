"""
Expand config.json target_companies from OPT-sponsor Excel sheet.

Reads every row in the sponsor sheet that has an ATS platform detected
(ats_platform in greenhouse/lever/ashby/workday) and a Sponsor Status
of "Strong Active Sponsor" or "Active but Selective", extracts the board
slug / URL, and adds any not already in config.json.

Usage:
    python3 scripts/expand_target_companies_from_opt.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
EXCEL_PATH = ROOT / "Opt_freindly" / "Gopall-OPT-Friendly-2 copy.xlsx"
CONFIG_PATH = ROOT / "config.json"

TARGET_STATUSES = {"Strong Active Sponsor", "Active but Selective"}


def _gh_slug(url: str) -> str | None:
    """Extract Greenhouse board slug from boards.greenhouse.io/<slug>
    or <slug>.greenhouse.io (custom subdomain) URLs."""
    if not url or "greenhouse.io" not in url:
        return None
    # Standard: boards.greenhouse.io/<slug>
    m = re.search(r"boards\.greenhouse\.io/([^/?#]+)", url)
    if m:
        return m.group(1).lower()
    # Custom subdomain: <slug>.greenhouse.io
    m = re.match(r"https?://([^.]+)\.greenhouse\.io", url)
    if m:
        return m.group(1).lower()
    return None


def _lv_slug(url: str) -> str | None:
    if not url or "lever.co" not in url:
        return None
    m = re.search(r"jobs\.lever\.co/([^/?#]+)", url)
    return m.group(1).lower() if m else None


def _ash_slug(url: str) -> str | None:
    if not url or "ashbyhq.com" not in url:
        return None
    m = re.search(r"jobs\.ashbyhq\.com/([^/?#]+)", url)
    return m.group(1) if m else None


def _wd_url(url: str) -> str | None:
    if not url or "myworkdayjobs.com" not in url:
        return None
    # Strip to board root: https://<tenant>.myworkdayjobs.com/<board>
    m = re.match(r"(https://[^/]+\.myworkdayjobs\.com/[^/?#]+)", url)
    return m.group(1) if m else None


EXTRACTORS = {
    "greenhouse": _gh_slug,
    "lever":      _lv_slug,
    "ashby":      _ash_slug,
    "workday":    _wd_url,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Print what would be added without writing")
    args = ap.parse_args()

    df = pd.read_excel(EXCEL_PATH)
    cfg = json.loads(CONFIG_PATH.read_text())

    existing = {
        ats: set(cfg["target_companies"].get(ats, []))
        for ats in EXTRACTORS
    }

    # Filter to target sponsors with a detected ATS
    df_target = df[
        df["Sponsor Status"].isin(TARGET_STATUSES) &
        df["ats_platform"].isin(EXTRACTORS.keys())
    ].copy()

    print(f"Eligible rows: {len(df_target)} "
          f"({df_target['ats_platform'].value_counts().to_dict()})")

    additions: dict[str, list[str]] = {ats: [] for ats in EXTRACTORS}

    for _, row in df_target.iterrows():
        ats = row["ats_platform"]
        portal = str(row.get("career_portal") or "")
        extractor = EXTRACTORS[ats]
        value = extractor(portal)
        if value and value not in existing[ats]:
            additions[ats].append(value)
            existing[ats].add(value)  # prevent duplicates within this run

    total = sum(len(v) for v in additions.values())
    print(f"\nNew entries to add: {total}")
    for ats, vals in additions.items():
        if vals:
            print(f"  {ats} (+{len(vals)}): {vals[:5]}{'...' if len(vals) > 5 else ''}")

    if total == 0:
        print("Nothing new to add.")
        return

    if args.dry_run:
        print("\n--dry-run: config.json not written.")
        return

    for ats, vals in additions.items():
        cfg["target_companies"][ats] = sorted(
            set(cfg["target_companies"].get(ats, [])) | set(vals)
        )

    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))
    print(f"\nconfig.json updated.")
    for ats in EXTRACTORS:
        after = len(cfg["target_companies"].get(ats, []))
        before = after - len(additions[ats])
        if additions[ats]:
            print(f"  {ats}: {before} → {after}")


if __name__ == "__main__":
    main()
