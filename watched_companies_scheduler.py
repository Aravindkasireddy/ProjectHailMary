"""Watched-company resolution and hourly scraper scheduler helpers.

Extracted verbatim from dashboard_server.py. Depends on module-level state
(_watched_scrape_inflight / _watched_scrape_inflight_lock, kept here as the
single source of truth and imported back into dashboard_server.py), plus
WORKSPACE_DIR and _valid_scrape_tracker_user_id() which remain in
dashboard_server.py and are imported lazily to avoid a circular import.
"""
import base64
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone

_watched_scrape_inflight = set()
_watched_scrape_inflight_lock = threading.Lock()

# Real incident (2026-06-25): the scheduler loop used to spawn a new thread
# for every due row with no cap at all. Registering 307 OPT-friendly
# companies (all with no last_scraped_at yet, so all instantly "due" on the
# very first tick) spawned ~300 concurrent company_scraper subprocesses on a
# 2-vCPU production VM, overloading it so badly even SSH stopped responding
# and the box needed a hard reset. Cap how many scrapes can run at once;
# anything due beyond the cap waits for a slot on a later tick (60s later)
# instead of all firing in the same instant.
MAX_CONCURRENT_WATCHED_SCRAPES = 3


def _watched_hint_from_url(url: str) -> str:
    from company_scraper.detector import brand_label_from_careers_url

    return brand_label_from_careers_url(url or "") or ""


def resolve_watched_company_input(raw: str):
    """Resolve display name, careers URL, and ATS for a watched-company row (no scraping)."""
    from company_scraper.detector import detect_ats, detect_input_type
    from company_scraper.discovery import find_careers_url

    s = (raw or "").strip()
    if not s:
        return None, "Empty input"
    errors = []
    kind = detect_input_type(s)
    careers_url = ""
    company_display = ""
    if kind == "company_name":
        company_display = s
        careers_url = find_careers_url(s, errors) or ""
        if not careers_url:
            return None, "Could not find a careers page for that company"
    elif kind == "careers_url":
        careers_url = s.rstrip("/")
        company_display = _watched_hint_from_url(careers_url) or s
    else:
        careers_url = s
        company_display = _watched_hint_from_url(s) or s

    ats = detect_ats(careers_url)
    return (
        {
            "input_value": s,
            "company_name": company_display or s,
            "careers_url": careers_url,
            "ats_platform": ats,
        },
        None,
    )


def _watched_parse_last_scraped_ts(ts):
    if not ts:
        return None
    try:
        s = str(ts).replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _parse_company_stdout_json_summary(blob: str):
    for line in reversed((blob or "").strip().splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                obj = json.loads(line)
                if isinstance(obj, dict) and "company" in obj:
                    return obj
            except Exception:
                continue
    return None


def _resolved_company_scraper_it_prefs(user_id, payload_prefs):
    """Merge DB ``company_scraper_it`` with optional per-request overrides from JSON body."""
    import dashboard_server as ds
    from company_scraper.filters import merge_it_prefs

    db_prefs: dict = {}
    if ds._valid_scrape_tracker_user_id(user_id):
        try:
            from supabase_client import get_supabase_client

            r = (
                get_supabase_client()
                .table("user_configs")
                .select("company_scraper_it")
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            rows = r.data or []
            if rows:
                raw = rows[0].get("company_scraper_it")
                if isinstance(raw, dict):
                    db_prefs = raw
        except Exception:
            pass
    merged = merge_it_prefs(db_prefs)
    if isinstance(payload_prefs, dict):
        for k, v in payload_prefs.items():
            if k in merged:
                merged[k] = v
        merged = merge_it_prefs(merged)
    return merged


def _fire_instant_alerts_for_opt_friendly_company(row: dict, user_id: str, email: str, since) -> None:
    """Send an immediate per-job webhook alert for jobs this scrape just found,
    instead of waiting for the next daily digest.

    Only called for watched_companies rows with is_opt_friendly=true (the
    307-company fast-poll list verified by scripts/probe_opt_friendly_ats.py)
    - the whole point of fast-polling these specifically is that a user
    shouldn't have to wait until the next digest to hear about a new OPT-
    friendly posting.
    """
    import dashboard_server as ds

    try:
        from supabase_client import get_supabase_client

        sb = get_supabase_client()
        res = (
            sb.table("jobs")
            .select("*")
            .eq("user_id", user_id)
            .eq("company_name", row.get("company_name") or "")
            .gte("scraped_at", since.isoformat())
            .eq("apply_decision", "APPLY")
            .execute()
        )
        new_jobs = res.data or []
        for job in new_jobs:
            ds.send_webhook_alert(job, email=email)
    except Exception as e:
        print(f"watched_companies: instant OPT-friendly alert failed for {row.get('company_name')}: {e}")


def _watched_company_scrape_thread(row: dict):
    """Run company_scraper/main.py for a watched row; update last_jobs_found; clear inflight."""
    import dashboard_server as ds

    row_id = str(row.get("id") or "")
    try:
        uid = str(row.get("user_id") or "")
        email = str(row.get("user_email") or "")
        inp = str(row.get("input_value") or "").strip()
        if not uid or not email or not inp:
            return
        b64 = base64.b64encode(json.dumps({"input": inp}).encode("utf-8")).decode("ascii")
        env = os.environ.copy()
        env["MAAS_USER_ID"] = uid
        env["MAAS_USER_EMAIL"] = email
        script = os.path.join(ds.WORKSPACE_DIR, "company_scraper", "main.py")
        scrape_started_at = datetime.now(timezone.utc)
        p = subprocess.run(
            [sys.executable, script, b64],
            cwd=ds.WORKSPACE_DIR,
            env=env,
            capture_output=True,
            text=True,
            timeout=7200,
        )
        blob = (p.stdout or "") + "\n" + (p.stderr or "")
        summary = _parse_company_stdout_json_summary(blob)
        if summary is not None and "it_jobs_found" in summary:
            try:
                from supabase_client import get_supabase_client

                n = int(summary.get("it_jobs_found") or 0)
                get_supabase_client().table("watched_companies").update({"last_jobs_found": n}).eq(
                    "id", row_id
                ).execute()
            except Exception as ex:
                print(f"watched_companies: last_jobs_found update failed {row_id}: {ex}")

        if row.get("is_opt_friendly"):
            _fire_instant_alerts_for_opt_friendly_company(row, uid, email, scrape_started_at)
    except Exception as e:
        print(f"watched_companies scrape thread error {row_id}: {e}")
    finally:
        with _watched_scrape_inflight_lock:
            _watched_scrape_inflight.discard(row_id)


def _is_company_due(company: dict, now) -> bool:
    last = company.get("last_scraped_at")
    last_dt = _watched_parse_last_scraped_ts(last)
    poll_minutes = company.get("poll_interval_minutes")
    if last_dt is None:
        return True
    if last_dt.tzinfo is None:
        last_dt = last_dt.replace(tzinfo=timezone.utc)
    if poll_minutes:
        return (now - last_dt).total_seconds() >= (int(poll_minutes) * 60)
    freq = (company.get("scrape_frequency") or "daily").lower()
    if freq not in ("daily", "weekly"):
        freq = "daily"
    delta = (now - last_dt).total_seconds()
    return delta >= (86400 if freq == "daily" else 604800)


def _run_scheduler_tick(supabase, start_thread=None) -> int:
    """Run one tick of the watched-companies scheduler. Returns how many
    scrapes were actually started (kept separate from the infinite loop so
    it's unit-testable, in particular the concurrency cap).
    """
    if start_thread is None:
        start_thread = lambda company: threading.Thread(
            target=_watched_company_scrape_thread, args=(dict(company),), daemon=True
        ).start()

    started = 0
    res = supabase.table("watched_companies").select("*").eq("is_active", True).execute()
    rows = res.data or []
    now = datetime.now(timezone.utc)
    for company in rows:
        row_id = str(company.get("id") or "")
        if not row_id or not _is_company_due(company, now):
            continue
        with _watched_scrape_inflight_lock:
            if row_id in _watched_scrape_inflight:
                continue
            if len(_watched_scrape_inflight) >= MAX_CONCURRENT_WATCHED_SCRAPES:
                # At capacity this tick - leave last_scraped_at untouched so
                # this row is picked up again (still due) on a later tick.
                continue
            _watched_scrape_inflight.add(row_id)
        try:
            supabase.table("watched_companies").update(
                {"last_scraped_at": now.isoformat()}
            ).eq("id", row_id).execute()
        except Exception as ex:
            with _watched_scrape_inflight_lock:
                _watched_scrape_inflight.discard(row_id)
            print(f"watched_companies scheduler: bump last_scraped_at failed {row_id}: {ex}")
            continue
        start_thread(company)
        started += 1
    return started


def watched_companies_scheduler_loop():
    """Scrape due active watched companies (service role).

    Tick interval dropped from hourly to 60s (2026-06-25) so companies with a
    poll_interval_minutes set (OPT-friendly fast-poll companies, typically
    5-10 min) actually get checked at that cadence instead of being capped at
    once/hour regardless of what was configured. The per-row "is this due"
    check still defaults to scrape_frequency's daily/weekly text logic when
    poll_interval_minutes isn't set, so existing daily/weekly watched
    companies are unaffected - they just get checked more frequently (cheap,
    a single SELECT) without becoming due any sooner than before.
    """
    while True:
        time.sleep(60)
        try:
            from supabase_client import get_supabase_client

            _run_scheduler_tick(get_supabase_client())
        except Exception as e:
            print(f"Watched companies scheduler error: {e}")
