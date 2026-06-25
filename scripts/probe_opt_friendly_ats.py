"""Probe every OPT-friendly company (h1b_sponsors.opt_friendly_score not null) to find
which ones have a fast/cheap-to-poll ATS board (Greenhouse/Lever/Workday/iCIMS) versus a
generic corporate careers page. Goal: build the watch-list for near-real-time scraping of
OPT-friendly job postings.

Resumable: progress is checkpointed to a JSON file after every company, keyed by
company_name, so re-running this script skips already-processed companies instead of
starting over. Runs companies concurrently (independent external hosts per company, not
sharing a single rate-limited search engine, so this is safe to parallelize unlike the
Yahoo/DuckDuckGo discovery paths elsewhere in this repo).

For each company that resolves to a candidate ATS URL, also verifies the company's own
name actually appears on the resolved page before accepting the match - confirmed live
2026-06-24 that slug-guessing produces real false positives (e.g. "General Motors" guessed
to "general" resolving to some unrelated company's real Greenhouse board at that slug).

Usage:
    python3 scripts/probe_opt_friendly_ats.py [--limit N] [--workers N]

Output: opt_friendly_ats_probe.json in the repo root, with one entry per company:
    {"company_name": ..., "url": ..., "ats": ..., "verified": bool}
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(dotenv_path=str(ROOT / ".env"))

from supabase_client import get_supabase_client  # noqa: E402
from company_scraper.discovery import find_careers_url  # noqa: E402
from company_scraper.detector import detect_ats  # noqa: E402
from h1b_sponsors import clean_company_name  # noqa: E402

OUTPUT_PATH = ROOT / "opt_friendly_ats_probe.json"
_LOCK = threading.Lock()


def _load_progress() -> dict:
    if OUTPUT_PATH.exists():
        try:
            return json.loads(OUTPUT_PATH.read_text())
        except Exception:
            return {}
    return {}


def _save_progress(progress: dict) -> None:
    tmp = OUTPUT_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(progress, indent=2))
    tmp.replace(OUTPUT_PATH)


import re as _re
from urllib.parse import urlparse as _urlparse

_TITLE_TAG_RE = _re.compile(r"<title[^>]*>(.*?)</title>", _re.IGNORECASE | _re.DOTALL)


def _verify_company_on_page(company_name: str, url: str, ats: str | None = None) -> bool:
    """Verify a resolved ATS URL genuinely belongs to ``company_name``.

    Real bug (2026-06-25), found in two layers:
    1. Checking the FULL page body text for keyword overlap (even with
       boilerplate words stripped) is still too permissive - full-page text
       scanning matches on noise. Fixed by checking only the <title> tag:
       Greenhouse/Lever boards consistently render it as "Jobs at {Company}"
       / "{Company} Jobs" / just "{Company}" - confirmed live,
       boards.greenhouse.io/air's title is literally "Jobs at Air" (not "Air
       Filters Inc") and /apex's is "Jobs at Apex Eye" (not "Apex Systems
       LLC").
    2. clean_company_name() (h1b_sponsors.py) is designed for loose fuzzy
       *matching* and strips words like "Systems"/"Technologies"/"Solutions"
       as if they were legal suffixes - which destroys the actual
       distinguishing part of a name like "Apex Systems" (cleans down to
       just "apex", a single generic word that trivially matches any board
       whose company happens to also start with "Apex"). Switched to
       company_normalizer's lighter suffix stripper, which only removes true
       legal-entity suffixes (Inc/LLC/Corp/Ltd/...) and keeps real
       distinguishing words intact.
    """
    from company_normalizer import _strip_legal_suffix

    cleaned = _strip_legal_suffix(company_name).strip().lower()
    keywords = [w for w in cleaned.split() if len(w) >= 3] or [company_name.lower()]
    if not keywords:
        return False

    try:
        r = requests.get(url, timeout=12, headers={"User-Agent": "Mozilla/5.0"})
        m = _TITLE_TAG_RE.search(r.text or "")
        title_text = (m.group(1) if m else "").lower()
        if not title_text:
            return False
        matches = sum(1 for kw in keywords if kw in title_text)
        required = min(2, len(keywords))
        return matches >= required
    except Exception:
        return False


def _probe_one(company_name: str) -> dict:
    cleaned = clean_company_name(company_name).strip() or company_name
    first_word = cleaned.split()[0] if cleaned.split() else company_name
    errs: list[str] = []
    url = find_careers_url(first_word, errs)
    if not url:
        url = find_careers_url(cleaned, errs)
    if not url:
        return {"company_name": company_name, "url": None, "ats": None, "verified": False}

    ats = detect_ats(url)
    verified = False
    if ats in ("greenhouse", "lever", "workday", "icims"):
        verified = _verify_company_on_page(company_name, url, ats)

    return {"company_name": company_name, "url": url, "ats": ats, "verified": verified}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    sb = get_supabase_client()
    # PostgREST caps rows per request at 1000 (db-max-rows) regardless of the
    # .limit() value passed here - confirmed live, an unpaginated .limit(100000)
    # call silently returned only the top 1000 rows. Paginate with .range() to
    # actually fetch the full ~9985-row OPT-friendly list.
    companies: list[str] = []
    page_size = 1000
    offset = 0
    while True:
        res = (
            sb.table("h1b_sponsors")
            .select("company_name,opt_friendly_score")
            .not_.is_("opt_friendly_score", "null")
            .order("opt_friendly_score", desc=True)
            .range(offset, offset + page_size - 1)
            .execute()
        )
        page = res.data or []
        companies.extend(r["company_name"] for r in page)
        if len(page) < page_size:
            break
        offset += page_size
        if args.limit and len(companies) >= args.limit:
            break
    if args.limit:
        companies = companies[: args.limit]
    print(f"Total OPT-friendly companies to probe: {len(companies)}")

    progress = _load_progress()
    todo = [c for c in companies if c not in progress]
    print(f"Already done: {len(progress)}, remaining: {len(todo)}")

    done_count = len(progress)
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(_probe_one, name): name for name in todo}
        for fut in as_completed(futures):
            name = futures[fut]
            try:
                result = fut.result()
            except Exception as e:
                result = {"company_name": name, "url": None, "ats": None, "verified": False, "error": str(e)}

            with _LOCK:
                progress[name] = result
                done_count += 1
                if done_count % 10 == 0:
                    _save_progress(progress)
                tag = "HIT" if result.get("verified") else ("ats?" if result.get("ats") else "-")
                print(f"[{done_count}/{len(companies)}] {name!r:50} -> {result.get('url')} {result.get('ats')} {tag}", flush=True)

    _save_progress(progress)

    verified_hits = [v for v in progress.values() if v.get("verified")]
    print(f"\n=== DONE. {len(verified_hits)} verified fast-pollable companies out of {len(progress)} probed ===")
    for v in sorted(verified_hits, key=lambda x: x["company_name"]):
        print(v["company_name"], "->", v["url"], v["ats"])


if __name__ == "__main__":
    main()
