"""Workday career sites (Playwright Chromium, rate-limited)."""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List
from urllib.parse import urlparse

from company_scraper.url_normalize import canonical_job_url
from playwright.sync_api import sync_playwright


def _extract_job_links(page) -> List[str]:
    return page.evaluate(
        """() => {
          const out = new Set();
          for (const a of document.querySelectorAll('a[href]')) {
            const h = a.href || '';
            if (/\\/job\\//i.test(h) || /\\/w\\/\\w+\\/\\w+\\/job\\//i.test(h) || /\\/d\\/\\w+\\/\\w+\\/\\w+\\/\\d+/i.test(h)) out.add(h.split('#')[0]);
          }
          return Array.from(out);
        }"""
    )


def fetch_jobs(careers_url: str, company_hint: str = "", max_pages: int = 24) -> List[Dict[str, Any]]:
    from company_scraper.scrapers import apify_client

    if apify_client.is_configured():
        try:
            rows = apify_client.fetch_workday_jobs_via_apify(careers_url, company_hint)
            if rows:
                return rows[:500]
        except Exception as e:
            logging.getLogger("company_scraper").warning(
                "apify workday scrape failed for %s, falling back to local Playwright: %s", careers_url, e
            )

    time.sleep(2)
    seen: set[str] = set()
    rows: List[Dict[str, Any]] = []
    host_company = company_hint or (urlparse(careers_url).netloc.split(".")[0].title())

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1400, "height": 900},
        )
        page = context.new_page()
        try:
            page.goto(careers_url, wait_until="domcontentloaded", timeout=90000)
            for _ in range(max_pages):
                time.sleep(2)
                for h in _extract_job_links(page):
                    c = canonical_job_url(h)
                    if not c or c in seen:
                        continue
                    seen.add(c)
                    title = ""
                    try:
                        title = page.evaluate(
                            """(u) => {
                              const a = Array.from(document.querySelectorAll('a[href]')).find(x => (x.href||'').split('#')[0] === u);
                              return a ? (a.innerText || '').trim().slice(0, 400) : '';
                            }""",
                            h,
                        )
                    except Exception:
                        pass
                    if not title:
                        title = (urlparse(h).path or "").strip("/").split("/")[-1].replace("-", " ")[:200] or "Workday job"
                    rows.append(
                        {
                            "job_url": h,
                            "job_title": title,
                            "company_name": host_company,
                            "job_description": "",
                            "location_work_type": "Remote",
                            "requirement_id": "",
                        }
                    )
                clicked = False
                for sel in (
                    "button:has-text('Next')",
                    "a:has-text('Next')",
                    "[aria-label*='ext page']",
                    "[data-uxi-pagination-navigation='next']",
                ):
                    try:
                        loc = page.locator(sel).first
                        if loc.count() and loc.is_visible():
                            loc.click()
                            page.wait_for_timeout(3500)
                            clicked = True
                            break
                    except Exception:
                        continue
                if not clicked:
                    break
        finally:
            context.close()
            browser.close()

    return rows[:500]
