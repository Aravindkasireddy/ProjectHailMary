"""
One-time script: find the real myworkdayjobs.com board URL for each
watched_company with ats_platform='workday' but a custom career domain.

Strategy (per company):
  1. Fetch the custom URL with requests (fast, handles most cases)
  2. Extract embedded myworkdayjobs.com / myworkdaysite.com URLs from HTML
  3. If not found, try Playwright (JS-rendered pages)
  4. If still not found, try Serper search: "<company> site:myworkdayjobs.com"
  5. Update careers_url in watched_companies if resolved

Run: python3 scripts/resolve_workday_custom_domains.py
"""

import os
import re
import sys
import time
import json
import logging
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client
from company_scraper.http_utils import request_with_retry

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

WORKDAY_RE = re.compile(
    r'https?://[a-zA-Z0-9._-]+\.(?:myworkdayjobs|myworkdaysite)\.com/[^\s\'"<>]*',
    re.I
)


def _best_board_url(matches: list[str]) -> str:
    if not matches:
        return None
    # Prefer board-level URLs (no /job/ segment)
    boards = [m for m in matches if "/job/" not in m.lower()]
    best = (boards or matches)[0].rstrip("/?,;")
    return best


def try_requests(url: str) -> str:
    try:
        r = request_with_retry("GET", url, timeout=15, max_attempts=2)
        matches = WORKDAY_RE.findall(r.text or "")
        return _best_board_url(matches)
    except Exception as e:
        log.debug("requests failed for %s: %s", url, e)
        return None


def try_playwright(url: str) -> str:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=20000, wait_until="networkidle")
            html = page.content()
            browser.close()
        matches = WORKDAY_RE.findall(html)
        return _best_board_url(matches)
    except Exception as e:
        log.debug("playwright failed for %s: %s", url, e)
        return None


def try_serper(company_name: str) -> str:
    api_key = os.environ.get("SERPER_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        import requests
        query = f"{company_name} careers site:myworkdayjobs.com"
        r = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": query, "num": 5},
            timeout=10,
        )
        data = r.json()
        for item in data.get("organic", []):
            link = item.get("link", "")
            if "myworkdayjobs.com" in link or "myworkdaysite.com" in link:
                # Strip to board level (remove /job/... suffix)
                m = re.match(r'(https?://[^/]+/[^/]+)', link)
                return m.group(1) if m else link
    except Exception as e:
        log.debug("serper failed for %s: %s", company_name, e)
    return None


def resolve(company_name: str, careers_url: str) -> str:
    log.info("Resolving: %s (%s)", company_name, careers_url)

    result = try_requests(careers_url)
    if result:
        log.info("  ✓ requests: %s", result)
        return result

    result = try_playwright(careers_url)
    if result:
        log.info("  ✓ playwright: %s", result)
        return result

    result = try_serper(company_name)
    if result:
        log.info("  ✓ serper: %s", result)
        return result

    log.info("  ✗ not resolved")
    return None


def main():
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])

    rows = sb.table("watched_companies").select("id,company_name,careers_url") \
        .eq("ats_platform", "workday").execute().data

    custom = [
        r for r in rows
        if "myworkdayjobs.com" not in (r["careers_url"] or "")
        and "myworkdaysite.com" not in (r["careers_url"] or "")
    ]

    log.info("Found %d custom-domain Workday companies to resolve", len(custom))

    resolved = 0
    failed = 0
    results = []

    for i, row in enumerate(custom, 1):
        log.info("[%d/%d] %s", i, len(custom), row["company_name"])
        board_url = resolve(row["company_name"], row["careers_url"])

        if board_url:
            try:
                sb.table("watched_companies").update({"careers_url": board_url}) \
                    .eq("id", row["id"]).execute()
                log.info("  → Updated Supabase: %s", board_url)
                resolved += 1
                results.append({"company": row["company_name"], "old": row["careers_url"], "new": board_url})
            except Exception as e:
                log.error("  Supabase update failed: %s", e)
                failed += 1
        else:
            failed += 1

        # Be gentle — avoid hammering sites
        time.sleep(1)

    log.info("Done. Resolved: %d / %d. Failed: %d", resolved, len(custom), failed)

    # Save results for review
    out = "logs/workday_domain_resolution.json"
    os.makedirs("logs", exist_ok=True)
    with open(out, "w") as f:
        json.dump(results, f, indent=2)
    log.info("Results saved to %s", out)


if __name__ == "__main__":
    main()
