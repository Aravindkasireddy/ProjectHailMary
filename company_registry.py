"""Company Registry: a shared, company-level cache of ATS discovery results.

Problem this solves: discovering a company's ATS type/endpoint (slug-guessing
+ Yahoo fallback, see company_scraper/discovery.py) is a real cost - the
9985-company OPT-friendly probe earlier this session took ~12 hours and a
lot of network calls to do this once. Without a registry, that work has to
be redone every time any code path (watched-companies scheduler, on-demand
company scraper, a future bulk discovery pass) needs to know a company's
ATS. The registry persists the answer once it's known, keyed by normalized
company name, so it's a cache lookup instead of live discovery on every call.

This is intentionally a separate table from watched_companies: this
registry is company-level (the same company has the same ATS regardless of
which user is watching it), while watched_companies is a per-user scrape
subscription (poll interval, is_active, etc. are per-user choices).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from company_normalizer import normalize_company

DEFAULT_STALE_AFTER_DAYS = 30


def _name_key(name: str) -> str:
    return normalize_company(name or "").strip().lower()


def lookup_company(name: str) -> Optional[Dict[str, Any]]:
    """Return the registry row for ``name`` if one exists, else None.

    Does not check staleness - callers that care should check
    is_stale(row) themselves, since "stale but present" is still useful
    (e.g. as a hint while a fresh check runs).
    """
    from supabase_client import get_supabase_client

    key = _name_key(name)
    if not key:
        return None
    sb = get_supabase_client()
    res = sb.table("companies").select("*").eq("name_normalized", key).limit(1).execute()
    rows = res.data or []
    return rows[0] if rows else None


def is_stale(row: Dict[str, Any], max_age_days: int = DEFAULT_STALE_AFTER_DAYS) -> bool:
    """A registry row is stale if it was never verified, or verified too long ago.

    ATS boards do get retired/renamed (confirmed live elsewhere this project:
    16 dead config.json slugs found in one audit), so even a "verified" row
    needs periodic re-confirmation, not permanent trust.
    """
    if not row.get("verified"):
        return True
    last = row.get("last_verified_at")
    if not last:
        return True
    try:
        ts = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
    except Exception:
        return True
    return (datetime.now(timezone.utc) - ts) > timedelta(days=max_age_days)


def upsert_company(
    name: str,
    careers_url: Optional[str] = None,
    ats_type: Optional[str] = None,
    ats_endpoint: Optional[str] = None,
    verified: bool = False,
    health_score: float = 0.0,
    source: str = "unknown",
) -> Dict[str, Any]:
    """Insert or update a company's registry row, keyed by normalized name."""
    from supabase_client import get_supabase_client

    key = _name_key(name)
    if not key:
        raise ValueError("company name normalizes to empty string")

    now_iso = datetime.now(timezone.utc).isoformat()
    row = {
        "name": name,
        "name_normalized": key,
        "careers_url": careers_url,
        "ats_type": ats_type,
        "ats_endpoint": ats_endpoint,
        "verified": verified,
        "health_score": health_score,
        "source": source,
        "last_checked_at": now_iso,
    }
    if verified:
        row["last_verified_at"] = now_iso

    sb = get_supabase_client()
    sb.table("companies").upsert(row, on_conflict="name_normalized").execute()
    return row


def resolve_company_ats(name: str, max_age_days: int = DEFAULT_STALE_AFTER_DAYS) -> Optional[Dict[str, Any]]:
    """The main entry point other code should call: registry-first lookup.

    Returns a fresh, verified registry row if one exists; None if the
    registry has nothing usable (caller should fall back to live discovery
    via company_scraper/discovery.py, then call upsert_company() to persist
    the result for next time).
    """
    row = lookup_company(name)
    if row and not is_stale(row, max_age_days):
        return row
    return None
