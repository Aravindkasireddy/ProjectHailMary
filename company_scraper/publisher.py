"""Publish company-scraped jobs to Supabase public.jobs only (no intermediate JSON on disk)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List


def _row(
    job: Dict[str, Any],
    user_id: str,
    ats_platform: str,
) -> Dict[str, Any]:
    url = job.get("job_url") or ""
    payload = dict(job.get("apply_decision_payload") or {})
    payload.setdefault("source", "company_scraper")
    payload["ats_platform"] = ats_platform
    payload["is_company_targeted"] = True

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
        "apply_decision": job.get("apply_decision") or "APPLY",
        "strongest_label": job.get("strongest_label") or "DevOps Engineer",
        "confidence_score": _conf(job.get("confidence_score")),
        "rationale": job.get("rationale") or "Company-targeted scrape",
        "red_flags": job.get("red_flags") if isinstance(job.get("red_flags"), list) else [],
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
    if not rows:
        return 0

    batch_size = 50
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        supabase.table("jobs").upsert(batch, on_conflict="user_id,job_url").execute()

    return len(rows)
