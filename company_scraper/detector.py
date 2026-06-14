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
