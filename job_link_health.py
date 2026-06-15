"""
HTTP-based heuristics to infer whether a job posting URL is still live.

Used by the dashboard batch stale checker and the per-job /api/job/check-live endpoint.
"""

from __future__ import annotations

import urllib.parse
from typing import Any

import requests

_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_CLOSED_PHRASES = (
    "this job is no longer available",
    "posting has closed",
    "job is closed",
    "no longer accepting applications",
    "position has been filled",
    "job posting was not found",
    "role is no longer open",
    "this position has been filled",
    "requisition is no longer active",
    "job has expired",
)


def check_job_posting_live(url: str, timeout: float = 8.0) -> dict[str, Any]:
    """
    Probe ``url`` and return a structured guess at whether the listing is stale.

    Returns keys: stale (bool), uncertain (bool), reason (str),
    http_status (int | None), final_url (str | None).

    ``uncertain`` is True when we could not fetch or interpret the page
    (network error, gated 401/403, server errors). In those cases ``stale``
    is always False so we do not falsely hide a job.
    """
    result: dict[str, Any] = {
        "stale": False,
        "uncertain": True,
        "reason": "No request made",
        "http_status": None,
        "final_url": None,
    }

    u = (url or "").strip()
    if not u.startswith("http://") and not u.startswith("https://"):
        result["reason"] = "Invalid or missing URL (expected http/https)"
        return result

    try:
        r = requests.get(u, headers=_DEFAULT_HEADERS, timeout=timeout, allow_redirects=True)
    except requests.RequestException as e:
        result["uncertain"] = True
        result["stale"] = False
        result["reason"] = f"Could not fetch URL ({type(e).__name__}: {e})"
        return result

    result["http_status"] = r.status_code
    result["final_url"] = r.url

    if r.status_code in (404, 410):
        result["uncertain"] = False
        result["stale"] = True
        result["reason"] = f"HTTP {r.status_code} (not found / gone)"
        return result

    if r.status_code in (401, 403):
        result["uncertain"] = True
        result["stale"] = False
        result["reason"] = (
            f"HTTP {r.status_code} (listing may be gated; not treating as closed)"
        )
        return result

    if r.status_code >= 500:
        result["uncertain"] = True
        result["stale"] = False
        result["reason"] = f"HTTP {r.status_code} (upstream server error)"
        return result

    result["uncertain"] = False

    final_url = r.url.lower()
    parsed_final = urllib.parse.urlparse(final_url)
    path = parsed_final.path

    if "greenhouse.io" in parsed_final.netloc:
        if "error=true" in final_url or "/jobs/" not in path:
            result["stale"] = True
            result["reason"] = "Greenhouse URL or error flag indicates missing listing"
            return result
    elif "lever.co" in parsed_final.netloc:
        path_parts = [p for p in path.split("/") if p]
        if len(path_parts) < 2:
            result["stale"] = True
            result["reason"] = "Lever URL path too short for a single posting"
            return result
        text_lower = r.text.lower()
        if "jobs at" in text_lower or "current openings" in text_lower:
            result["stale"] = True
            result["reason"] = "Lever page looks like a board listing, not the job"
            return result
    elif "ashbyhq.com" in parsed_final.netloc:
        path_parts = [p for p in path.split("/") if p]
        if len(path_parts) <= 1:
            result["stale"] = True
            result["reason"] = "Ashby URL path too short for a single posting"
            return result

    text_lower = r.text.lower()
    for kw in _CLOSED_PHRASES:
        if kw in text_lower:
            result["stale"] = True
            result["reason"] = f"Closed signal in page body ({kw[:48]!r})"
            return result

    result["stale"] = False
    result["reason"] = f"HTTP {r.status_code}; no known closed signals"
    return result


def is_url_stale(url: str, timeout: float = 8.0) -> bool:
    """Backward-compatible boolean wrapper."""
    return bool(check_job_posting_live(url, timeout=timeout).get("stale"))
