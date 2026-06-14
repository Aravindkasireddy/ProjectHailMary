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

                links.append(unquote(m.group(1)))
            else:
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
    base = company_name.strip().lower().replace(" ", "")
    roots = [
        f"https://{slug}.greenhouse.io",
        f"https://boards.greenhouse.io/{slug}",
        f"https://jobs.lever.co/{slug}",
        f"https://{slug}.myworkdayjobs.com",
        f"https://careers.{base}.com",
        f"https://www.{base}.com/careers",
        f"https://{base}.com/careers",
    ]
    return roots


def find_careers_url(company_name: str, errors: Optional[List[str]] = None) -> Optional[str]:
    err = errors if errors is not None else []
    name = (company_name or "").strip()
    if not name:
        err.append("empty company name")
        return None

    for u in _candidate_urls(name):
        if head_ok(u):
            return u.rstrip("/")

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
                return link.rstrip("/")

    err.append(f"could not discover careers URL for {name!r}")
    return None
