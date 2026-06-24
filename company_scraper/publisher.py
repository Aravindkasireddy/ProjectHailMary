"""Publish company-scraped jobs to Supabase public.jobs only (no intermediate JSON on disk)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List


from company_scraper.url_normalize import canonical_job_url


def _row(
    job: Dict[str, Any],
    user_id: str,
    ats_platform: str,
) -> Dict[str, Any]:
    url = canonical_job_url(job.get("job_url") or "")
    payload = dict(job.get("apply_decision_payload") or {})
    payload.setdefault("source", "company_scraper")
    payload["ats_platform"] = ats_platform
    payload["is_company_targeted"] = True

    from job_fingerprint import canonical_fingerprint, make_source_entry

    job_for_fp = {**job, "job_url": url}
    fingerprint = canonical_fingerprint(job_for_fp)

    def _conf(v: Any) -> float:
        if v is None:
            return 100.0
        try:
            x = float(v)
            return x * 100.0 if x <= 1.0 else x
        except (TypeError, ValueError):
            return 100.0

    return {
        "user_id": user_id,
        "job_title": job.get("job_title") or "Unknown Title",
        "company_name": job.get("company_name") or "Unknown",
        "job_url": url,
        "requirement_id": job.get("requirement_id") or "Unknown",
        "job_description": job.get("job_description") or "",
        "location_work_type": job.get("location_work_type") or "Remote",
        # Real incident (2026-06-23): these used to default to APPLY/"DevOps
        # Engineer"/100% whenever main.py's classification step didn't run
        # (which used to be always - see main.py's classify_job_dynamically
        # call). If classification genuinely didn't happen, default to "don't
        # know" (OutOfScope/DO_NOT_APPLY), never an unconditional auto-approve.
        "apply_decision": job.get("apply_decision") or "DO_NOT_APPLY",
        "strongest_label": job.get("strongest_label") or "OutOfScope",
        "confidence_score": _conf(job.get("confidence_score")) if job.get("strongest_label") else 0.0,
        "rationale": job.get("rationale") or "Not classified (company-targeted scrape ran without a classification step)",
        "red_flags": (
            job["red_flags"] if isinstance(job.get("red_flags"), list)
            else [] if job.get("strongest_label")
            else ["Not classified"]
        ),
        "apply_decision_payload": payload,
        "synced": bool(job.get("synced", False)),
        "synced_data": job.get("synced_data") if isinstance(job.get("synced_data"), dict) else {},
        "scraped_at": job.get("scraped_at") or datetime.utcnow().isoformat(),
        "stale": bool(job.get("stale", False)),
        "archived": bool(job.get("archived", False)),
        "pipeline_stage": job.get("pipeline_stage") or "Scraped",
        "min_salary": job.get("min_salary"),
        "max_salary": job.get("max_salary"),
        "is_hourly": bool(job.get("is_hourly", False)),
        "salary_text": job.get("salary_text"),
        "benefits": job.get("benefits") if isinstance(job.get("benefits"), list) else [],
        "canonical_fingerprint": fingerprint,
        "ats_source": ats_platform,
        "sources": [make_source_entry(job_for_fp, ats_platform)],
    }


def upsert_jobs(
    jobs: List[Dict[str, Any]],
    user_id: str,
    _email: str,
    ats_platform: str,
) -> int:
    """Upsert jobs to ``public.jobs`` only. On-demand path — does not write pipeline JSON files."""
    from supabase_client import get_supabase_client

    if not user_id or not jobs:
        return 0

    supabase = get_supabase_client()
    rows = [_row(j, user_id, ats_platform) for j in jobs if j.get("job_url")]
    # Dedupe within batch (same canonical URL twice in one run)
    by_canon: dict[str, dict] = {}
    for r in rows:
        c = r.get("job_url") or ""
        if c:
            by_canon[c] = r
    rows = list(by_canon.values())
    if not rows:
        return 0

    new_columns = ("canonical_fingerprint", "ats_source", "sources")
    batch_size = 50
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        try:
            supabase.table("jobs").upsert(batch, on_conflict="user_id,job_url").execute()
        except Exception as e:
            # canonical_fingerprint/ats_source/sources columns may not exist yet
            # (scripts/add_canonical_fingerprint_columns.sql not yet applied to
            # this install) - retry once without them rather than hard-failing
            # job publishing on a schema mismatch.
            if "column" in str(e).lower() or "42703" in str(e):
                stripped = [{k: v for k, v in r.items() if k not in new_columns} for r in batch]
                supabase.table("jobs").upsert(stripped, on_conflict="user_id,job_url").execute()
            else:
                raise

    return len(rows)
