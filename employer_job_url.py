"""
True when a job URL points at an employer or ATS-hosted posting, not aggregators / social.

Keep in sync with ``dashboard/src/lib/employerJobUrl.ts`` (same allow/block rules).
"""

from __future__ import annotations

from urllib.parse import urlparse

# Hosts we never treat as "official company career" apply pages.
_BLOCKED_HOST_SUFFIXES = (
    "linkedin.com",
    "linkedin.cn",
    "indeed.com",
    "glassdoor.com",
    "glassdoor.co.uk",
    "monster.com",
    "ziprecruiter.com",
    "dice.com",
    "careerbuilder.com",
    "snagajob.com",
    "simplyhired.com",
    "talent.com",
    "jobrapido.com",
    "jooble.org",
    "jooble.com",
    "reddit.com",
    "twitter.com",
    "x.com",
    "t.co",
    "facebook.com",
    "instagram.com",
    "tiktok.com",
    "medium.com",
    "substack.com",
    "weworkremotely.com",
    "remote.co",
    "remotive.com",
    "remoteok.io",
    "dynamitejobs.com",
    "wellfound.com",
    "angel.co",
    "hn.algolia.com",
    "news.ycombinator.com",
)

# Known ATS / apply stacks (substring match on full URL is enough).
_ATS_URL_HINTS = (
    "greenhouse.io",
    "lever.co",
    "myworkdayjobs.com",
    "workdayjobs.com",
    "ashbyhq.com",
    "apply.workable.com",
    "smartrecruiters.com",
    "icims.com",
    "bamboohr.com",
    "rippling.com",
    "pinpointhq.com",
    "breezy.hr",
    "recruitee.com",
    "teamtailor.com",
    "ultipro.com",
    "taleo.net",
    "brassring.com",
    "eightfold.ai",
    "successfactors.com",
    "oraclecloud.com",
    "fa.us2.oraclecloud.com",
    "jobvite.com",
    "hrmdirect.com",
    "paycomonline.net",
)


def _host(url: str) -> str:
    try:
        h = (urlparse(url).netloc or "").lower()
        if h.startswith("www."):
            h = h[4:]
        return h
    except Exception:
        return ""


def is_official_company_careers_job_url(url: str) -> bool:
    if not (url or "").strip():
        return False
    low = url.lower()
    h = _host(url)
    for suf in _BLOCKED_HOST_SUFFIXES:
        if h == suf or h.endswith("." + suf):
            return False
    for hint in _ATS_URL_HINTS:
        if hint in low:
            return True
    # Employer career hubs: careers.example.com, jobs.example.com, apply.example.com
    if h.startswith("careers.") or h.startswith("jobs.") or h.startswith("apply."):
        return True
    try:
        path = (urlparse(url).path or "").lower()
    except Exception:
        path = ""
    # Many companies use /careers/, /jobs/, etc. on the corporate domain (not a subdomain).
    if "/careers" in path or "/job/" in path or "/jobs/" in path or "/openings" in path or "/positions" in path:
        return True
    return False
