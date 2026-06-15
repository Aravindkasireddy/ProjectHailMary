"""
True when a job URL is a company-hosted (or employer-tenant) apply page — not aggregators,
not LinkedIn, and not multi-tenant ATS boards (Greenhouse, Lever, Ashby, …).

Workday ``*.myworkdayjobs.com`` / ``*.workdayjobs.com`` and Oracle recruiting cloud hosts are
allowed because postings are employer-tenant URLs.

Keep in sync with ``dashboard/src/lib/employerJobUrl.ts``.
"""

from __future__ import annotations

from urllib.parse import urlparse

# Aggregators, social, job boards (never treat as company-hosted apply).
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

# Shared ATS domains (apply URL is not on the employer's own corporate / careers domain).
_MULTI_TENANT_ATS_SUFFIXES = (
    "greenhouse.io",
    "lever.co",
    "ashbyhq.com",
    "workable.com",
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
    "jobvite.com",
    "hrmdirect.com",
    "paycomonline.net",
    "successfactors.com",
)


def _host(url: str) -> str:
    try:
        h = (urlparse(url).netloc or "").lower()
        if h.startswith("www."):
            h = h[4:]
        return h
    except Exception:
        return ""


def _blocked_aggregator(h: str) -> bool:
    for suf in _BLOCKED_HOST_SUFFIXES:
        if h == suf or h.endswith("." + suf):
            return True
    return False


def _multi_tenant_ats_host(h: str) -> bool:
    for suf in _MULTI_TENANT_ATS_SUFFIXES:
        if h == suf or h.endswith("." + suf):
            return True
    return False


def is_official_company_careers_job_url(url: str) -> bool:
    """
    Company-hosted apply URL: employer career site, corporate /careers paths, or
    employer-tenant Workday / Oracle recruiting — excluding LinkedIn and shared ATS boards.
    """
    if not (url or "").strip():
        return False
    low = (url or "").lower()
    h = _host(url)
    if not h:
        return False
    if _blocked_aggregator(h):
        return False
    if _multi_tenant_ats_host(h):
        return False

    # Employer Workday tenant boards (e.g. acme.wd5.myworkdayjobs.com)
    if h.endswith(".myworkdayjobs.com") or h.endswith(".workdayjobs.com"):
        return True

    # Oracle recruiting cloud (employer-specific recruiting hosts)
    if "oraclecloud.com" in low or h.endswith(".oraclecloud.com"):
        return True

    # careers.example.com, jobs.example.com, apply.example.com
    if h.startswith("careers.") or h.startswith("jobs.") or h.startswith("apply."):
        return True

    try:
        path = (urlparse(url).path or "").lower()
    except Exception:
        path = ""
    if (
        "/careers" in path
        or "/job/" in path
        or "/jobs/" in path
        or "/openings" in path
        or "/positions" in path
    ):
        return True
    return False
