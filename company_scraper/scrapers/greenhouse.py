"""Greenhouse public board API."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from company_scraper.http_utils import get_session, request_with_retry


def _slug_from_url(url: str) -> Optional[str]:
    p = urlparse(url)
    host = (p.netloc or "").lower()
    parts = [x for x in (p.path or "").split("/") if x]
    if host.endswith(".greenhouse.io") and not host.startswith("boards"):
        return host.split(".")[0]
    if "boards.greenhouse.io" in host and parts:
        return parts[0]
    if "greenhouse.io" in host and parts:
        return parts[0]
    return None


def fetch_jobs(careers_or_job_url: str, company_hint: str = "") -> List[Dict[str, Any]]:
    slug = _slug_from_url(careers_or_job_url)
    if not slug:
        return []
    api = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
    r = request_with_retry("GET", api, session=get_session(), timeout=25, max_attempts=3)
    if r.status_code != 200:
        return []
    data = r.json()
    jobs = data.get("jobs") or []
    out: List[Dict[str, Any]] = []
    co = company_hint or data.get("name") or slug
    for j in jobs:
        title = j.get("title") or ""
        loc = j.get("location", {}).get("name") if isinstance(j.get("location"), dict) else j.get("location") or ""
        u = j.get("absolute_url") or ""
        if not u:
            continue
        desc = ""
        if j.get("content"):
            desc = str(j.get("content"))[:120000]
        dept = ""
        for d in j.get("departments") or []:
            if isinstance(d, dict) and d.get("name"):
                dept = d["name"]
                break
        out.append(
            {
                "job_url": u,
                "job_title": title,
                "company_name": co,
                "job_description": desc,
                "location_work_type": str(loc) if loc else "Remote",
                "requirement_id": str(j.get("internal_job_id") or j.get("id") or ""),
            }
        )
    parsed_u = urlparse(careers_or_job_url)
    if re.search(r"/jobs/\d+", (parsed_u.path or ""), re.I):
        jid = re.search(r"/jobs/(\d+)", parsed_u.path, re.I)
        if jid:
            want = jid.group(1)
            out = [x for x in out if want in x["job_url"]]
    return out
