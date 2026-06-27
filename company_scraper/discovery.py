"""Resolve company name to a careers URL (Yahoo + heuristics + HEAD)."""

from __future__ import annotations

import re
from typing import List, Optional
from urllib.parse import quote_plus, urlparse

from bs4 import BeautifulSoup

from company_scraper.http_utils import get_session, head_ok, request_with_retry


def _yahoo_links(query: str) -> List[str]:
    url = f"https://search.yahoo.com/search?p={quote_plus(query)}"
    links: List[str] = []
    try:
        r = request_with_retry("GET", url, session=get_session(), timeout=15, max_attempts=3)
        if r.status_code != 200:
            return links
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            m = re.search(r"RU=([^/]+)", href)
            if m:
                from urllib.parse import unquote

                href = unquote(m.group(1))
            # Real bug (2026-06-24): the RU= branch used to append its decoded
            # URL unconditionally, with no domain filter - unlike this check,
            # which the non-RU= branch already had. Yahoo's own search-results
            # page embeds internal links (e.g. shopping.yahoo.com widgets)
            # behind the RU= redirect param, and those were being returned as
            # if they were genuine external "careers URL" results - confirmed
            # live, this caused find_careers_url() to return a literal Yahoo
            # search page for most companies that needed the Yahoo fallback,
            # which detect_ats() then misclassified as "greenhouse" purely
            # because the substring "greenhouse.io" appeared in the URL's own
            # query string (the original search query embedded in the link).
            parsed = urlparse(href)
            dom = parsed.netloc.lower()
            if parsed.scheme.startswith("http") and "yahoo.com" not in dom and "yimg.com" not in dom:
                links.append(href)
    except Exception:
        pass
    return links


def _slug_from_company(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "", name.lower())
    return s[:40] or "company"


def _candidate_urls(company_name: str) -> List[str]:
    slug = _slug_from_company(company_name)
    compact = company_name.strip().lower().replace(" ", "")
    parts = [p for p in re.split(r"[^a-zA-Z0-9]+", company_name.strip().lower()) if p]
    first = parts[0] if parts else ""
    roots = [
        f"https://{slug}.greenhouse.io",
        f"https://boards.greenhouse.io/{slug}",
        f"https://jobs.lever.co/{slug}",
        f"https://{slug}.myworkdayjobs.com",
        f"https://careers.{slug}.com",
        f"https://jobs.{slug}.com",
        f"https://careers.{compact}.com",
        f"https://jobs.{compact}.com",
        f"https://careers.{first}.com" if first and first not in (slug, compact) else "",
        f"https://www.{compact}.com/careers",
        f"https://{compact}.com/careers",
    ]
    return [u for u in roots if u]


def find_careers_url(company_name: str, errors: Optional[List[str]] = None) -> Optional[str]:
    err = errors if errors is not None else []
    name = (company_name or "").strip()
    if not name:
        err.append("empty company name")
        return None

    # Registry-first: skip live discovery entirely if we already know this
    # company's ATS from a previous discovery run (e.g. the 9985-company
    # OPT-friendly probe). See company_registry.py for why this matters -
    # without it, the same discovery cost gets paid again on every call.
    try:
        from company_registry import resolve_company_ats

        cached = resolve_company_ats(name)
        if cached and cached.get("careers_url"):
            return cached["careers_url"]
    except Exception:
        pass

    found_url = None
    for u in _candidate_urls(name):
        if head_ok(u):
            found_url = u.rstrip("/")
            break

    if not found_url:
        q = (
            f'"{name}" jobs careers '
            f"(site:greenhouse.io OR site:lever.co OR site:myworkdayjobs.com OR site:icims.com)"
        )
        for link in _yahoo_links(q):
            low = link.lower()
            if any(
                x in low
                for x in (
                    "greenhouse.io",
                    "lever.co",
                    "myworkdayjobs.com",
                    "workdayjobs.com",
                    "icims.com",
                    "careers.",
                    "/careers",
                    "/jobs",
                )
            ):
                if head_ok(link):
                    found_url = link.rstrip("/")
                    break

    if not found_url:
        err.append(f"could not discover careers URL for {name!r}")
        return None

    try:
        from company_registry import upsert_company
        from company_scraper.detector import detect_ats

        upsert_company(
            name,
            careers_url=found_url,
            ats_type=detect_ats(found_url),
            verified=True,
            source="live_discovery",
        )
    except Exception:
        pass

    return found_url
