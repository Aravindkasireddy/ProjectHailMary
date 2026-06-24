"""Deterministic job-fingerprinting for cross-source deduplication.

Problem: the same posting often shows up from multiple sources (e.g. a
Workday board, a LinkedIn repost, a company-page repost) with different
job_url values, which the existing (user_id, job_url) uniqueness constraint
treats as separate jobs. near_dedup.py's Jaccard-similarity grouping catches
some of these but is fuzzy, O(n^2), and recomputed on every /api/jobs load.

canonical_fingerprint() is a fast, deterministic alternative: normalize
company + title + location into a stable string and hash it. Two postings
for the same role at the same company/location collapse to one fingerprint
regardless of which ATS or repost surfaced them, so they can be merged at
write time instead of just flagged at read time.
"""
from __future__ import annotations

import hashlib
import re

_LEGAL_SUFFIXES = re.compile(
    r"\b(inc|llc|corp|corporation|incorporated|ltd|limited|co|company|"
    r"holdings|group|llp|plc)\b\.?",
    re.IGNORECASE,
)
_SENIORITY_PREFIXES = re.compile(
    r"^(senior|sr|staff|principal|lead|junior|jr|associate|entry level)\s+",
    re.IGNORECASE,
)
_REMOTE_HINTS = ("remote", "work from home", "wfh", "anywhere")


def normalize_company_name(name: str) -> str:
    """Strip legal suffixes/punctuation so 'Acme Inc.' and 'ACME, LLC' match."""
    if not name:
        return ""
    s = name.lower()
    s = re.sub(r"[,.\-()]", " ", s)
    s = _LEGAL_SUFFIXES.sub("", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def normalize_title(title: str) -> str:
    """Strip seniority prefixes and punctuation noise from a job title.

    Deliberately does NOT strip seniority entirely from the role itself
    (e.g. "Senior" vs "Staff" are genuinely different roles at some
    companies) - only a single leading seniority word is dropped, since
    that's the most common source of cosmetic title drift between reposts
    of the exact same opening (e.g. "DevOps Engineer" vs "Sr. DevOps
    Engineer" for the identical req).
    """
    if not title:
        return ""
    s = title.lower()
    s = re.sub(r"[\(\)\[\]\-–—,.]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = _SENIORITY_PREFIXES.sub("", s).strip()
    s = re.sub(r"\s+", " ", s).strip()
    return s


def normalize_location(location: str) -> str:
    """Collapse location text to either a city/region token or 'remote'.

    Reposts frequently vary location text cosmetically (e.g. "Austin, TX
    (Remote)" vs "Remote" vs "Remote - US") for what is the same fully
    remote role. Treat any location mentioning a remote-work hint as the
    single bucket "remote" rather than trying to preserve the city, since
    the city is usually irrelevant noise for a remote posting anyway.
    """
    if not location:
        return ""
    s = location.lower()
    if any(hint in s for hint in _REMOTE_HINTS):
        return "remote"
    s = re.sub(r"[\(\)\[\]]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def canonical_fingerprint(job: dict) -> str:
    """sha256 hash of normalized(company)|normalized(title)|normalized(location).

    Two postings with the same fingerprint are treated as the same canonical
    job regardless of job_url/ats_source - they get merged into one row with
    multiple tracked sources instead of producing duplicate rows.
    """
    company = normalize_company_name(job.get("company_name", ""))
    title = normalize_title(job.get("job_title", ""))
    location = normalize_location(job.get("location_work_type", ""))
    basis = f"{company}|{title}|{location}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def make_source_entry(job: dict, ats_source: str | None = None) -> dict:
    """Build one entry for the jobs.sources JSONB array."""
    return {
        "ats_source": ats_source or job.get("ats_source") or "unknown",
        "source_url": job.get("job_url") or "",
        "scraped_at": job.get("scraped_at") or "",
    }
