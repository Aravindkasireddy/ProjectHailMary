"""Detect input kind and ATS from URLs."""

from __future__ import annotations

import re
from typing import Literal
from urllib.parse import urlparse

from company_scraper.http_utils import request_with_retry

InputKind = Literal["company_name", "careers_url", "job_url"]
AtsKind = Literal["greenhouse", "lever", "workday", "icims", "generic"]


_JOB_PATH_HINTS = re.compile(
    r"(/job[s]?/[^/]+|/requisition/|/req/|/position/|/careers/job/|/jobdetail/|/jobs/\d+|/job/\d+)",
    re.I,
)


_SKIP_VANITY_HOST_LABELS = frozenset(
    {
        "www",
        "careers",
        "jobs",
        "job",
        "apply",
        "applying",
        "recruiting",
        "talent",
        "hiring",
        "hire",
        "work",
        "join",
        "join-us",
        "vacancies",
        "vacancy",
        "campus",
        "campuses",
        "boards",
        "team",
        "people",
        "hr",
        "employment",
        "opportunities",
        "workplace",
        "students",
        "university",
        "earlycareer",
        "early-career",
    }
)


def brand_label_from_careers_url(url: str) -> str:
    """
    Best-effort employer display name from a careers-site URL hostname.
    Skips leading vanity labels (careers., jobs., www., …) so careers.google.com → Google.
    """
    try:
        host = (urlparse(url or "").netloc or "").lower()
        if not host or "@" in host:
            return ""
        parts = [p for p in host.split(".") if p]
        while parts and parts[0] in _SKIP_VANITY_HOST_LABELS and len(parts) > 2:
            parts.pop(0)
        if not parts:
            return ""
        brand = parts[0].replace("-", " ").strip()
        if not brand:
            return ""
        return brand.title()
    except Exception:
        return ""


def listing_url_candidates_from_job_url(job_url: str) -> list[str]:
    """
    From a single job posting URL, derive likely site-wide listing / search URLs
    (same employer, many roles). Example:
    https://careers.hpe.com/us/en/job/1202469/Cloud-Developer
    -> https://careers.hpe.com/us/en/jobs, .../search-results, etc.
    """
    u = (job_url or "").strip()
    if not u.startswith(("http://", "https://")):
        return []
    p = urlparse(u)
    if not p.netloc:
        return []
    segments = [s for s in (p.path or "").split("/") if s]
    lowered = [s.lower() for s in segments]
    root = f"{p.scheme}://{p.netloc}"
    candidates: list[str] = []

    if "job" in lowered:
        idx = lowered.index("job")
        prefix = "/" + "/".join(segments[:idx]) if idx > 0 else ""
        for sub in _LISTING_PATH_TAILS:
            path = f"{prefix}/{sub}".replace("//", "/")
            if not path.startswith("/"):
                path = "/" + path
            candidates.append(root + path)
    for tail in ("/jobs", "/search-results", "/careers/jobs", "/offices", "/job-search"):
        candidates.append(root + tail)

    out: list[str] = []
    seen: set[str] = set()
    for c in candidates:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


_LISTING_PATH_TAILS = (
    "c/search-results",
    "c/job-search",
    "search-results",
    "job-search",
    "jobs",
    "search",
    "careers",
)


def listing_url_candidates_from_careers_url(careers_url: str) -> list[str]:
    """
    Expand a careers homepage or locale hub (e.g. https://careers.hpe.com/us/en)
    into likely job-listing URLs. The input URL itself is not repeated here;
    callers should try the original first, then these alternates.
    """
    u = (careers_url or "").strip().rstrip("/")
    if not u.startswith(("http://", "https://")):
        return []
    p = urlparse(u)
    if not p.netloc:
        return []
    segments = [s for s in (p.path or "").split("/") if s]
    root = f"{p.scheme}://{p.netloc}"
    prefix = "/" + "/".join(segments) if segments else ""
    candidates: list[str] = []
    for sub in _LISTING_PATH_TAILS:
        path = f"{prefix}/{sub}".replace("//", "/")
        if not path.startswith("/"):
            path = "/" + path
        candidates.append(root + path)
    for tail in ("/jobs", "/search-results", "/c/search-results", "/offices", "/job-search", "/careers/jobs"):
        candidates.append(root + tail)

    out: list[str] = []
    seen: set[str] = set()
    for c in candidates:
        c = c.rstrip("/")
        if c == u or c in seen:
            continue
        seen.add(c)
        out.append(c)
    return out


def detect_input_type(input_str: str) -> InputKind:
    s = (input_str or "").strip()
    if not s:
        return "company_name"
    low = s.lower()
    if low.startswith("http://") or low.startswith("https://"):
        parsed = urlparse(s)
        path = (parsed.path or "").lower()
        if _JOB_PATH_HINTS.search(path):
            return "job_url"
        if len(path) > 1 and path not in ("/", "/careers", "/jobs"):
            if re.search(r"/(job|jobs|requisition|req|position)/", path, re.I):
                return "job_url"
        return "careers_url"
    return "company_name"


def detect_ats(url: str) -> AtsKind:
    u = (url or "").lower()
    if "greenhouse.io" in u or "boards.greenhouse.io" in u:
        return "greenhouse"
    if "lever.co" in u or "jobs.lever.co" in u:
        return "lever"
    if "myworkdayjobs.com" in u or "workdayjobs.com" in u or "wd5.myworkdayjobs.com" in u:
        return "workday"
    if "icims.com" in u:
        return "icims"
    try:
        r = request_with_retry("GET", url, timeout=15, max_attempts=2)
        text = (r.text or "").lower()
        if "myworkdayjobs.com" in text or "workdaycdn" in text or ("wdio" in text and "workday" in text):
            return "workday"
        if "icims" in text or "icims.com" in text:
            return "icims"
    except Exception:
        pass
    return "generic"
