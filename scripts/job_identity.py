"""Stable job identity + light enrichment for dedup across pipeline JSON files."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict
from urllib.parse import urlparse


def normalize_job_url(url: str) -> str:
    if not url:
        return ""
    try:
        p = urlparse(url)
        path = p.path.rstrip("/")
        return f"{p.scheme}://{p.netloc.lower()}{path}".lower()
    except Exception:
        return (url or "").lower().strip()


def stable_job_id(url: str) -> str:
    n = normalize_job_url(url)
    if not n:
        return ""
    return hashlib.sha256(n.encode("utf-8")).hexdigest()[:32]


def compute_description_hash(description: str) -> str:
    if not description:
        return ""
    normalized = "".join(description.lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def enrich_job_record(job: Dict[str, Any]) -> Dict[str, Any]:
    """Mutate job dict with job_id and description_hash when missing."""
    url = job.get("job_url") or ""
    if not job.get("job_id"):
        jid = stable_job_id(url)
        if jid:
            job["job_id"] = jid
    desc = job.get("job_description") or ""
    if desc and not job.get("description_hash"):
        job["description_hash"] = compute_description_hash(desc)
    return job


def enrich_job_list(jobs: list) -> list:
    for j in jobs:
        if isinstance(j, dict):
            enrich_job_record(j)
    return jobs
