"""Lever public postings API."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from company_scraper.http_utils import get_session, request_with_retry


def board_url_from_job_or_listing(url: str) -> str:
    """``jobs.lever.co/<company>/<posting>`` → ``jobs.lever.co/<company>`` (full board)."""
    p = urlparse((url or "").strip())
    if "lever.co" not in (p.netloc or "").lower():
        return (url or "").strip().rstrip("/")
    parts = [x for x in (p.path or "").split("/") if x]
    if len(parts) <= 1:
        return f"{p.scheme}://{p.netloc}/{parts[0]}".rstrip("/") if parts else (url or "").strip().rstrip("/")
    return f"{p.scheme}://{p.netloc}/{parts[0]}".rstrip("/")


def _slug(url: str) -> Optional[str]:
    p = urlparse(url)
    if "lever.co" not in (p.netloc or "").lower():
        return None
    parts = [x for x in (p.path or "").split("/") if x]
    return parts[0] if parts else None


def fetch_jobs(careers_or_job_url: str, company_hint: str = "") -> List[Dict[str, Any]]:
    careers_or_job_url = board_url_from_job_or_listing(careers_or_job_url)
    slug = _slug(careers_or_job_url)
    if not slug:
        return []
    api = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    r = request_with_retry("GET", api, session=get_session(), timeout=25, max_attempts=3)
    if r.status_code != 200:
        return []
    postings = r.json()
    if not isinstance(postings, list):
        return []
    out: List[Dict[str, Any]] = []
    for posting in postings:
        title = (posting.get("text") or "").strip()
        loc = ""
        cat = posting.get("categories") or {}
        if isinstance(cat, dict):
            loc = (cat.get("location") or "") or ""
        team = (cat.get("team") or "") if isinstance(cat, dict) else ""
        u = (posting.get("hostedUrl") or posting.get("applyUrl") or "").strip()
        if not u:
            continue
        desc_parts = []
        for key in ("description", "descriptionPlain"):
            if posting.get(key):
                desc_parts.append(str(posting[key]))
        desc = "\n".join(desc_parts)[:120000]
        co = company_hint or slug.replace("-", " ").title()
        out.append(
            {
                "job_url": u,
                "job_title": title,
                "company_name": co,
                "job_description": desc,
                "location_work_type": str(loc) if loc else "Remote",
                "requirement_id": str(posting.get("id") or ""),
                "department": str(team) if team else "",
            }
        )
    return out
