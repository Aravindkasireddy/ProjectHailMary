"""
Job posting liveness checker.

Strategy per ATS (most reliable → least reliable):
  1. ATS-native API call  — direct JSON endpoint, no HTML parsing needed
  2. Redirect detection   — job closed = redirected to board/listing page
  3. HTTP status          — 404/410 = definitively gone
  4. Page-body signals    — closed phrases in HTML text

Callers always get:
  {
    stale: bool,
    uncertain: bool,   # True when we genuinely cannot tell (network error, gated)
    reason: str,
    http_status: int | None,
    final_url: str | None,
    method: str,       # which check produced the verdict
  }

``uncertain=True`` always forces ``stale=False`` — never falsely hide a job.
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Any

import requests

_SESSION = requests.Session()
_SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xhtml+xml;q=0.9,*/*;q=0.8",
})

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
    "this position is no longer available",
    "this position has been closed",
    "this opening is no longer available",
    "job listing is no longer active",
    "this job has been filled",
    "we're sorry, this job is no longer",
    "sorry, this job posting has expired",
)

# Patterns that indicate a redirect to a board listing rather than a specific job
_BOARD_URL_PATTERNS = (
    re.compile(r"/jobs/?$", re.I),
    re.compile(r"/careers/?$", re.I),
    re.compile(r"/openings/?$", re.I),
    re.compile(r"error=true", re.I),
    re.compile(r"/job-search/?", re.I),
)


def _result(
    stale: bool,
    uncertain: bool,
    reason: str,
    method: str,
    http_status: int | None = None,
    final_url: str | None = None,
) -> dict[str, Any]:
    return {
        "stale": False if uncertain else stale,
        "uncertain": uncertain,
        "reason": reason,
        "method": method,
        "http_status": http_status,
        "final_url": final_url,
    }


def _get(url: str, timeout: float = 8.0, stream: bool = False) -> requests.Response:
    return _SESSION.get(url, timeout=timeout, allow_redirects=True, stream=stream)


# ---------------------------------------------------------------------------
# ATS-native API checks
# ---------------------------------------------------------------------------

def _check_greenhouse(job_id: str) -> dict[str, Any]:
    """
    Greenhouse exposes a public JSON endpoint per job.
    Returns 200 with job data if live, 404 if closed.
    """
    api_url = f"https://boards-api.greenhouse.io/v1/boards/jobs/{job_id}"
    try:
        r = _get(api_url, timeout=6)
        if r.status_code == 200:
            return _result(False, False, "Greenhouse API: job is live", "greenhouse_api", r.status_code, r.url)
        if r.status_code == 404:
            return _result(True, False, "Greenhouse API: job not found (404)", "greenhouse_api", r.status_code, r.url)
        # Any other status — fall through to HTML check
    except Exception as e:
        pass
    return {}


def _check_lever(company: str, job_id: str) -> dict[str, Any]:
    """
    Lever public JSON posting endpoint — 404 when closed.
    """
    api_url = f"https://api.lever.co/v0/postings/{company}/{job_id}"
    try:
        r = _get(api_url, timeout=6)
        if r.status_code == 200:
            return _result(False, False, "Lever API: job is live", "lever_api", r.status_code, r.url)
        if r.status_code == 404:
            return _result(True, False, "Lever API: job not found (404)", "lever_api", r.status_code, r.url)
    except Exception:
        pass
    return {}


def _check_ashby(job_id: str) -> dict[str, Any]:
    """
    Ashby GraphQL-style public endpoint.
    """
    api_url = f"https://api.ashbyhq.com/posting-api/job-board/job/{job_id}"
    try:
        r = _get(api_url, timeout=6)
        if r.status_code == 200:
            return _result(False, False, "Ashby API: job is live", "ashby_api", r.status_code, r.url)
        if r.status_code in (404, 410):
            return _result(True, False, f"Ashby API: job not found ({r.status_code})", "ashby_api", r.status_code, r.url)
    except Exception:
        pass
    return {}


def _check_workday(url: str) -> dict[str, Any]:
    """
    Workday job URLs contain a job requisition ID in the path.
    A live job returns 200; a closed one redirects to the board or returns 404.
    """
    try:
        r = _SESSION.get(url, timeout=8, allow_redirects=False)
        # Workday closed jobs redirect (301/302) to the board listing
        if r.status_code in (301, 302):
            location = r.headers.get("Location", "")
            if "/job/" not in location.lower():
                return _result(True, False, f"Workday: redirect to board ({location[:60]})", "workday_redirect", r.status_code, location)
        if r.status_code == 404:
            return _result(True, False, "Workday: 404 not found", "workday_http", r.status_code, url)
        if r.status_code == 200:
            # Follow the redirect ourselves to check final URL
            r2 = _get(url, timeout=8)
            final = r2.url.lower()
            if any(p.search(final) for p in _BOARD_URL_PATTERNS):
                return _result(True, False, "Workday: redirected to board listing", "workday_redirect", r2.status_code, r2.url)
            return _result(False, False, "Workday: job page returned 200", "workday_http", r2.status_code, r2.url)
    except Exception as e:
        pass
    return {}


def _check_icims(url: str) -> dict[str, Any]:
    """
    iCIMS job pages 404 or redirect to /jobs when closed.
    """
    try:
        r = _get(url, timeout=8)
        if r.status_code == 404:
            return _result(True, False, "iCIMS: 404 not found", "icims_http", r.status_code, r.url)
        final = r.url.lower()
        if "/jobs" in final and "iis=" not in final:
            return _result(True, False, "iCIMS: redirected to jobs listing", "icims_redirect", r.status_code, r.url)
        return _result(False, False, f"iCIMS: job page returned {r.status_code}", "icims_http", r.status_code, r.url)
    except Exception:
        pass
    return {}


def _check_smartrecruiters(url: str) -> dict[str, Any]:
    """
    SmartRecruiters public API for job details.
    URL format: jobs.smartrecruiters.com/<company>/<job_id>
    API:        www.smartrecruiters.com/public-api/v1/jobs/<job_id>
    """
    parsed = urllib.parse.urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) >= 2:
        job_id = parts[-1]
        try:
            api_url = f"https://www.smartrecruiters.com/public-api/v1/jobs/{job_id}"
            r = _get(api_url, timeout=6)
            if r.status_code == 200:
                data = r.json()
                status = data.get("status", "").lower()
                if status in ("closed", "cancelled", "on_hold"):
                    return _result(True, False, f"SmartRecruiters API: status={status}", "smartrecruiters_api", r.status_code, r.url)
                return _result(False, False, f"SmartRecruiters API: status={status or 'active'}", "smartrecruiters_api", r.status_code, r.url)
            if r.status_code == 404:
                return _result(True, False, "SmartRecruiters API: job not found", "smartrecruiters_api", r.status_code, r.url)
        except Exception:
            pass
    return {}


# ---------------------------------------------------------------------------
# Generic fallback
# ---------------------------------------------------------------------------

def _check_generic(url: str, timeout: float = 8.0) -> dict[str, Any]:
    """
    Generic fallback: HTTP status + redirect + closed-phrase scan.
    """
    try:
        r = _get(url, timeout=timeout)
    except requests.RequestException as e:
        return _result(False, True, f"Network error: {type(e).__name__}: {e}", "generic_http")

    http_status = r.status_code
    final_url = r.url

    if http_status in (404, 410):
        return _result(True, False, f"HTTP {http_status} (not found / gone)", "generic_http", http_status, final_url)

    if http_status in (401, 403):
        return _result(False, True, f"HTTP {http_status} (gated — cannot verify)", "generic_http", http_status, final_url)

    if http_status >= 500:
        return _result(False, True, f"HTTP {http_status} (server error)", "generic_http", http_status, final_url)

    # Redirect to board listing?
    if final_url.lower() != url.lower():
        if any(p.search(final_url) for p in _BOARD_URL_PATTERNS):
            return _result(True, False, f"Redirected to board listing ({final_url[:60]})", "redirect_detection", http_status, final_url)

    # Page-body closed-phrase scan
    text_lower = r.text.lower()
    for phrase in _CLOSED_PHRASES:
        if phrase in text_lower:
            return _result(True, False, f"Closed phrase in page body: {phrase!r:.48}", "body_scan", http_status, final_url)

    return _result(False, False, f"HTTP {http_status}; no closed signals found", "generic_http", http_status, final_url)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def check_job_posting_live(url: str, timeout: float = 8.0) -> dict[str, Any]:
    """
    Check whether a job posting URL is still live.

    Routes to an ATS-native API check when the URL's host/path matches
    a known ATS, falling back to generic HTTP + body scan otherwise.

    Returns:
        stale (bool)      — True if posting is definitively closed
        uncertain (bool)  — True when we genuinely cannot tell
        reason (str)      — human-readable explanation
        method (str)      — which check produced the verdict
        http_status (int | None)
        final_url (str | None)
    """
    u = (url or "").strip()
    if not u.startswith("http"):
        return _result(False, True, "Invalid URL", "none")

    parsed = urllib.parse.urlparse(u)
    host = parsed.netloc.lower()
    path = parsed.path

    # --- Greenhouse ---
    # URL: boards.greenhouse.io/<company>/jobs/<job_id>
    if "greenhouse.io" in host:
        m = re.search(r"/jobs/(\d+)", path)
        if m:
            res = _check_greenhouse(m.group(1))
            if res:
                return res

    # --- Lever ---
    # URL: jobs.lever.co/<company>/<uuid>
    if "lever.co" in host:
        parts = [p for p in path.split("/") if p]
        if len(parts) >= 2:
            res = _check_lever(parts[0], parts[1])
            if res:
                return res

    # --- Ashby ---
    # URL: jobs.ashbyhq.com/<company>/<uuid>
    if "ashbyhq.com" in host:
        parts = [p for p in path.split("/") if p]
        if len(parts) >= 2:
            res = _check_ashby(parts[1])
            if res:
                return res

    # --- Workday ---
    if "myworkdayjobs.com" in host or "myworkdaysite.com" in host:
        res = _check_workday(u)
        if res:
            return res

    # --- iCIMS ---
    if "icims.com" in host:
        res = _check_icims(u)
        if res:
            return res

    # --- SmartRecruiters ---
    if "smartrecruiters.com" in host:
        res = _check_smartrecruiters(u)
        if res:
            return res

    # --- Generic fallback ---
    return _check_generic(u, timeout=timeout)


def is_url_stale(url: str, timeout: float = 8.0) -> bool:
    """Backward-compatible boolean wrapper."""
    return bool(check_job_posting_live(url, timeout=timeout).get("stale"))
