"""Stale-job-link checking helpers and per-user state store.

Extracted verbatim from dashboard_server.py. Depends on module-level paths
(APPROVED_PATH, FAILED_PATH, ACTIVE_PATH), resolve_path(), and
_invalidate_jobs_cache(), all of which still live in dashboard_server.py.
Imported lazily inside each function to avoid a circular import.
"""
import os
import json
import time

# User-scoped stale check status store (single source of truth lives here;
# dashboard_server.py imports this same dict object).
stale_check_states = {}


def get_stale_check_state(email):
    email_key = email or "admin@hailmary.ai"
    if email_key not in stale_check_states:
        stale_check_states[email_key] = {
            "status": "idle",
            "progress": 0,
            "total": 0,
            "completed": 0,
            "stale_found": 0,
        }
    return stale_check_states[email_key]


def check_url_stale(url):
    """Return True if the posting is likely closed (used by batch stale checker)."""
    try:
        from job_link_health import check_job_posting_live

        return bool(check_job_posting_live(url, timeout=5.0).get("stale"))
    except Exception:
        return False


def persist_job_stale_flag(email, job_url, stale):
    """
    Set ``stale`` on a job in local JSON stores (approved / active / failed).
    Only writes files that contained the job URL. Returns (ok, message).
    """
    import dashboard_server as ds

    if not job_url:
        return False, "Missing job_url"

    approved_path = ds.resolve_path(ds.APPROVED_PATH, email)
    failed_path = ds.resolve_path(ds.FAILED_PATH, email)
    active_path = ds.resolve_path(ds.ACTIVE_PATH, email)

    approved = []
    if os.path.exists(approved_path):
        try:
            with open(approved_path, "r", encoding="utf-8") as f:
                approved = json.load(f)
        except Exception:
            pass

    failed = []
    if os.path.exists(failed_path):
        try:
            with open(failed_path, "r", encoding="utf-8") as f:
                failed = json.load(f)
        except Exception:
            pass

    active = []
    if os.path.exists(active_path):
        try:
            with open(active_path, "r", encoding="utf-8") as f:
                active = json.load(f)
        except Exception:
            pass

    touched_a = touched_f = touched_act = False
    for j in approved:
        if j.get("job_url") == job_url:
            j["stale"] = bool(stale)
            touched_a = True
    for j in failed:
        if j.get("job_url") == job_url:
            j["stale"] = bool(stale)
            touched_f = True
    for j in active:
        if j.get("job_url") == job_url:
            j["stale"] = bool(stale)
            touched_act = True

    if not (touched_a or touched_f or touched_act):
        ds._invalidate_jobs_cache(email)
        return False, "Job URL not found in local JSON stores (approved/active/failed)."

    try:
        if touched_a:
            with open(approved_path, "w", encoding="utf-8") as f:
                json.dump(approved, f, indent=2)
        if touched_f:
            with open(failed_path, "w", encoding="utf-8") as f:
                json.dump(failed, f, indent=2)
        if touched_act:
            with open(active_path, "w", encoding="utf-8") as f:
                json.dump(active, f, indent=2)
    except Exception as e:
        return False, f"Failed to save stale flag: {e}"

    ds._invalidate_jobs_cache(email)
    return True, ""


def stale_check_worker(email=None, user_id=None):
    """Bulk-check approved jobs for staleness and persist the result.

    Real incident (2026-06-24): this used to only read/write the local
    ``approved_jobs.json`` file. Supabase ``public.jobs`` is the sole
    job-data store for the dashboard (see CLAUDE.md), so those local-only
    writes never reached the table the UI actually reads from - confirmed
    live, 0 of 2777 Supabase rows had ever been flagged stale despite jobs
    sitting unverified for over a week. Now also updates Supabase per job
    when a user_id is available, same as the single-job check-live endpoint.
    """
    import dashboard_server as ds

    state = get_stale_check_state(email)
    state["status"] = "running"
    state["progress"] = 0
    state["total"] = 0
    state["completed"] = 0
    state["stale_found"] = 0

    sb = None
    if user_id:
        try:
            from supabase_client import get_supabase_client

            sb = get_supabase_client()
        except Exception as e:
            print(f"Stale check worker: could not init Supabase client: {e}")

    approved_path = ds.resolve_path(ds.APPROVED_PATH, email)
    try:
        if not os.path.exists(approved_path):
            state["status"] = "idle"
            return

        with open(approved_path, 'r') as f:
            approved_jobs = json.load(f)

        state["total"] = len(approved_jobs)
        if not approved_jobs:
            state["status"] = "idle"
            return

        from datetime import datetime, timezone, timedelta
        AUTO_ARCHIVE_DAYS = 30
        now = datetime.now(timezone.utc)
        auto_archived = 0

        updated_jobs = []
        for idx, job in enumerate(approved_jobs):
            url = job.get("job_url")
            is_stale = False
            if url:
                is_stale = check_url_stale(url)

            if is_stale:
                job["stale"] = True
                state["stale_found"] += 1
            else:
                job["stale"] = False

            # Auto-archive jobs that are stale AND older than AUTO_ARCHIVE_DAYS
            scraped_at = job.get("scraped_at") or job.get("created_at")
            should_archive = False
            if is_stale and scraped_at:
                try:
                    age = now - datetime.fromisoformat(scraped_at.replace("Z", "+00:00"))
                    if age.days >= AUTO_ARCHIVE_DAYS:
                        should_archive = True
                except Exception:
                    pass

            if url and sb is not None:
                try:
                    update = {"stale": job["stale"]}
                    if should_archive:
                        update["archived"] = True
                        auto_archived += 1
                    sb.table("jobs").update(update).eq("job_url", url).eq(
                        "user_id", str(user_id)
                    ).execute()
                except Exception as e:
                    print(f"Stale check worker: Supabase update failed for {url}: {e}")

            updated_jobs.append(job)
            state["completed"] = idx + 1
            state["progress"] = int((idx + 1) / len(approved_jobs) * 100)
            time.sleep(1)

        if auto_archived:
            print(f"Stale check worker: auto-archived {auto_archived} jobs older than {AUTO_ARCHIVE_DAYS} days")

        with open(approved_path, 'w') as f:
            json.dump(updated_jobs, f, indent=2)

    except Exception as e:
        print(f"Error in stale check worker: {e}")
    finally:
        state["status"] = "idle"
