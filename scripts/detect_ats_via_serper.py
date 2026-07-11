"""
Find real ATS boards for OPT-sponsor companies whose career_portal is
'generic' (ATS not yet identified) by searching Serper for each company
on myworkdayjobs.com / greenhouse.io / lever.co / ashbyhq.com.

Each company costs 4 Serper queries (one per ATS). With ~478 companies
that's ~1912 queries. The free tier is 2500, so run with --limit if low.

Usage:
    python3 scripts/detect_ats_via_serper.py [--dry-run] [--limit 100] [--workers 5]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

EXCEL_PATH = ROOT / "Opt_freindly" / "Gopall-OPT-Friendly-2 copy.xlsx"
CONFIG_PATH = ROOT / "config.json"
TARGET_STATUSES = {"Strong Active Sponsor", "Active but Selective"}

SERPER_KEY = os.environ.get("SERPER_API_KEY", "")

_WD_RE  = re.compile(r'https?://([a-zA-Z0-9._-]+\.myworkdayjobs\.com/[^\s\'"<>?#,]+)', re.I)
_GH_RE  = re.compile(r'boards\.greenhouse\.io/([^/\s\'"<>?#,]+)', re.I)
_GH2_RE = re.compile(r'https?://([a-z0-9-]+)\.greenhouse\.io(?:/|$)', re.I)
_LV_RE  = re.compile(r'jobs\.lever\.co/([^/\s\'"<>?#,]+)', re.I)
_ASH_RE = re.compile(r'jobs\.ashbyhq\.com/([^/\s\'"<>?#,]+)', re.I)
_SR_RE  = re.compile(r'https?://careers\.smartrecruiters\.com/([^/\s\'"<>?#,]+)', re.I)

ATS_SEARCHES = [
    ("workday",         "myworkdayjobs.com"),
    ("greenhouse",      "greenhouse.io"),
    ("lever",           "lever.co"),
    ("ashby",           "ashbyhq.com"),
    ("smartrecruiters", "smartrecruiters.com"),
]


def serper_search(query: str) -> list[dict]:
    if not SERPER_KEY:
        return []
    try:
        r = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": SERPER_KEY, "Content-Type": "application/json"},
            json={"q": query, "num": 3},
            timeout=10,
        )
        return r.json().get("organic", [])
    except Exception:
        return []


def _extract(ats: str, url: str) -> str | None:
    if not url:
        return None
    if ats == "workday":
        m = _WD_RE.search(url)
        if m:
            raw = "https://" + m.group(1).rstrip("/?,;")
            # strip /job/ sub-paths to get board root
            return re.sub(r"/job/.*$", "", raw, flags=re.I)
    elif ats == "greenhouse":
        m = _GH_RE.search(url)
        if m:
            return m.group(1).lower().strip("/")
        m = _GH2_RE.search(url)
        if m and m.group(1) not in ("boards", "app", "www"):
            return m.group(1).lower()
    elif ats == "lever":
        m = _LV_RE.search(url)
        if m:
            return m.group(1).lower().strip("/")
    elif ats == "ashby":
        m = _ASH_RE.search(url)
        if m:
            return m.group(1).strip("/")
    elif ats == "smartrecruiters":
        m = _SR_RE.search(url)
        if m:
            return m.group(1).strip("/")
    return None


def _slug_matches_company(ats: str, slug: str, company_name: str) -> bool:
    """Check the board slug/subdomain looks like it belongs to this company."""
    # Normalize company name to key tokens (skip legal suffixes)
    _stop = {"inc", "llc", "ltd", "corp", "corporation", "co", "company",
             "group", "global", "services", "solutions", "us", "usa", "dba",
             "the", "and", "of", "for", "lp", "plc"}
    tokens = [t for t in re.sub(r"[^a-z0-9 ]", " ", company_name.lower()).split()
              if t not in _stop and len(t) > 2]
    if not tokens:
        return False

    if ats == "workday":
        # Extract subdomain from URL: https://<tenant>.myworkdayjobs.com/...
        m = re.match(r"https?://([^.]+)\.", slug)
        identifier = m.group(1).lower() if m else slug.lower()
    else:
        identifier = slug.lower()

    # At least one meaningful company token must appear in the identifier
    return any(tok in identifier for tok in tokens)


def probe_company(company_name: str) -> dict:
    """Search Serper for this company on each ATS. Returns {ats: slug}."""
    found = {}
    for ats, site in ATS_SEARCHES:
        results = serper_search(f'"{company_name}" site:{site}')
        for item in results:
            link = item.get("link", "")
            slug = _extract(ats, link)
            if slug and _slug_matches_company(ats, slug, company_name):
                found[ats] = slug
                break
        time.sleep(0.1)  # gentle rate limiting
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="Max companies (0=all)")
    ap.add_argument("--workers", type=int, default=5)
    args = ap.parse_args()

    if not SERPER_KEY:
        print("ERROR: SERPER_API_KEY not set in .env")
        sys.exit(1)

    df = pd.read_excel(EXCEL_PATH)
    df_target = df[
        df["Sponsor Status"].isin(TARGET_STATUSES) &
        (df["ats_platform"] == "generic") &
        (df["career_portal_verified"] == True)
    ].copy()

    # Skip known consulting/staffing firms (they're blocked anyway)
    _skip = {"infosys", "tcs", "tata consultancy", "wipro", "cognizant", "hcl",
              "tech mahindra", "mphasis", "accenture", "capgemini", "dxc",
              "ntt data", "kyndryl", "teksystems", "insight global", "robert half",
              "randstad", "leidos", "saic", "booz allen", "caci", "gdit",
              "beaconfire", "innova solutions", "procareer"}
    df_target = df_target[
        ~df_target["Employer Name"].str.lower().apply(
            lambda n: any(s in n for s in _skip)
        )
    ]

    companies = df_target["Employer Name"].tolist()
    if args.limit:
        companies = companies[:args.limit]

    cfg = json.loads(CONFIG_PATH.read_text())
    existing = {ats: set(cfg["target_companies"].get(ats, []))
                for ats in ["greenhouse", "lever", "ashby", "workday", "smartrecruiters"]}

    print(f"Searching {len(companies)} companies × 5 ATS platforms "
          f"= ~{len(companies)*5} Serper queries")
    print()

    from collections import defaultdict
    by_ats: dict[str, list] = defaultdict(list)
    done = 0

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(probe_company, c): c for c in companies}
        for fut in as_completed(futures):
            company = futures[fut]
            done += 1
            result = fut.result()
            for ats, slug in result.items():
                if ats in existing and slug not in existing[ats]:
                    by_ats[ats].append((company, slug))
                    existing[ats].add(slug)
                    print(f"  [{done}/{len(companies)}] {ats.upper():15} {company[:40]:40} → {slug}")
            if done % 20 == 0 and not result:
                print(f"  [{done}/{len(companies)}] ...")

    print(f"\nTotal new entries found: {sum(len(v) for v in by_ats.values())}")
    for ats, items in by_ats.items():
        print(f"  {ats}: +{len(items)}")

    if args.dry_run:
        print("\n--dry-run: config.json not written.")
        return

    for ats, items in by_ats.items():
        slugs = [slug for _, slug in items]
        if slugs:
            cfg["target_companies"][ats] = sorted(
                set(cfg["target_companies"].get(ats, [])) | set(slugs)
            )

    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))
    print("\nconfig.json updated:")
    for ats, items in by_ats.items():
        if items:
            after = len(cfg["target_companies"][ats])
            print(f"  {ats}: {after - len(items)} → {after}")


if __name__ == "__main__":
    main()
