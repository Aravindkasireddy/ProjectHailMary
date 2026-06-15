"""iCIMS search HTML (requests + BeautifulSoup)."""

from __future__ import annotations

import time
from typing import Any, Dict, List
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from company_scraper.http_utils import get_session, request_with_retry
from company_scraper.url_normalize import canonical_job_url


def fetch_jobs(careers_url: str, company_hint: str = "", max_pages: int = 25) -> List[Dict[str, Any]]:
    sess = get_session()
    rows: List[Dict[str, Any]] = []
    seen: set[str] = set()
    base = careers_url.split("?")[0].rstrip("/")

    for page_i in range(max_pages):
        if page_i == 0:
            url = careers_url
        else:
            joiner = "&" if "?" in careers_url else "?"
            url = f"{base}{joiner}iis={page_i + 1}"

        time.sleep(2)
        r = request_with_retry("GET", url, session=sess, timeout=25, max_attempts=3)
        if r.status_code != 200:
            break
        soup = BeautifulSoup(r.text, "html.parser")
        found = 0
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            low = href.lower()
            if "icims.com" not in low and not low.startswith("/"):
                continue
            if not any(x in low for x in ("job", "position", "requisition", "req", "jobdetail")):
                continue
            full_raw = urljoin(careers_url, href).split("#")[0]
            canon = canonical_job_url(full_raw)
            if not canon or canon in seen:
                continue
            seen.add(canon)
            title = (a.get_text() or "").strip() or "Job"
            rows.append(
                {
                    "job_url": full_raw,
                    "job_title": title[:500],
                    "company_name": company_hint or urlparse(careers_url).netloc.split(".")[0].title(),
                    "job_description": "",
                    "location_work_type": "Remote",
                    "requirement_id": "",
                }
            )
            found += 1
        if found == 0:
            break
    return rows[:500]
