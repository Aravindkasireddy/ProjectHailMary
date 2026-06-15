"""Normalize job posting URLs so the same role does not create multiple Supabase rows."""

from __future__ import annotations

from urllib.parse import urlparse, urlunparse


def canonical_job_url(url: str) -> str:
    """
    Stable key for deduplication: https host lowercased, default https, path without trailing slash,
    no query string or fragment.
    """
    u = (url or "").strip()
    if not u:
        return ""
    try:
        p = urlparse(u)
        netloc = (p.netloc or "").strip().lower()
        if "@" in netloc:
            netloc = netloc.split("@")[-1]
        if netloc.endswith(":80") or netloc.endswith(":443"):
            netloc = netloc.rsplit(":", 1)[0]
        path = (p.path or "").rstrip("/")
        scheme = "https"
        return urlunparse((scheme, netloc, path, "", "", ""))
    except Exception:
        return u.split("#")[0].split("?")[0].rstrip("/").lower()
