"""Generic career sites: robots.txt (optional), Playwright WebKit listing, then HTTP detail pages."""

from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from company_scraper.constants import GENERIC_LISTING_LINK_CAP, MAX_GENERIC_JOBS
from company_scraper.http_utils import get_session, request_with_retry

_JOB_HREF = re.compile(
    r"(/job|/jobs/|/careers/|requisition|req\.|position|posting|apply/|/opportunity/)",
    re.I,
)


def _robots_allowed(url: str) -> bool:
    try:
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        rp = RobotFileParser()
        rp.set_url(base + "/robots.txt")
        rp.read()
        return rp.can_fetch("*", url)
    except Exception:
        return True


def _collect_listing_links(careers_url: str, max_links: int) -> List[str]:
    time.sleep(2)
    out: List[str] = []
    with sync_playwright() as p:
        browser = p.webkit.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
                "(KHTML, like Gecko) Version/17.0 Safari/605.1.15"
            ),
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()
        try:
            page.goto(careers_url, wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(2000)
            raw = page.evaluate(
                """() => Array.from(document.querySelectorAll('a[href]')).map(a => a.href).filter(Boolean)"""
            )
        finally:
            context.close()
            browser.close()
    if not isinstance(raw, list):
        return out
    base_host = urlparse(careers_url).netloc.lower()
    for h in raw:
        if not isinstance(h, str) or len(out) >= max_links:
            break
        low = h.lower()
        if not low.startswith("http"):
            continue
        if urlparse(h).netloc.lower() != base_host and base_host not in low:
            continue
        if _JOB_HREF.search(h):
            # Keep query string — many ATS links need ?… to resolve; strip hash only.
            out.append(h.split("#")[0])
    return list(dict.fromkeys(out))


def _fetch_detail(url: str, company_hint: str) -> Dict[str, Any]:
    sess = get_session()
    r = request_with_retry("GET", url, session=sess, timeout=25, max_attempts=3)
    soup = BeautifulSoup(r.text or "", "html.parser")
    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        title = og["content"].strip() or title
    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        title = h1.get_text(strip=True) or title
    desc = ""
    for sel in ("article", "main", '[role="main"]', ".job-description", "#job-description"):
        node = soup.select_one(sel)
        if node:
            desc = node.get_text("\n", strip=True)[:120000]
            break
    if not desc:
        desc = soup.get_text("\n", strip=True)[:120000]
    co = company_hint or urlparse(url).netloc.split(".")[0].title()
    return {
        "job_url": url,
        "job_title": title or "Job posting",
        "company_name": co,
        "job_description": desc,
        "location_work_type": "Remote",
        "requirement_id": "",
    }


def fetch_single_job_page(job_url: str, company_hint: str = "") -> List[Dict[str, Any]]:
    """Fetch one job detail URL (respects robots.txt)."""
    if not _robots_allowed(job_url):
        return []
    time.sleep(2)
    try:
        return [_fetch_detail(job_url, company_hint)]
    except Exception:
        return []


def fetch_jobs(careers_url: str, company_hint: str = "", max_jobs: Optional[int] = None) -> List[Dict[str, Any]]:
    if max_jobs is None:
        max_jobs = MAX_GENERIC_JOBS
    if not _robots_allowed(careers_url):
        return []
    cap = min(GENERIC_LISTING_LINK_CAP, max(200, max_jobs * 4))
    links = _collect_listing_links(careers_url, max_links=cap)
    rows: List[Dict[str, Any]] = []
    for u in links:
        if len(rows) >= max_jobs:
            break
        if not _robots_allowed(u):
            continue
        time.sleep(2)
        try:
            rows.append(_fetch_detail(u, company_hint))
        except Exception:
            continue
    return rows
