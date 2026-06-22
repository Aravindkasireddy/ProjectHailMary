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
    except Exception as e:
        print(f"watched_companies scrape thread error {row_id}: {e}")
    finally:
        with _watched_scrape_inflight_lock:
            _watched_scrape_inflight.discard(row_id)


def watched_companies_scheduler_loop():
    """Hourly: scrape due active watched companies (service role)."""
    while True:
        time.sleep(3600)
        try:
            from supabase_client import get_supabase_client

            supabase = get_supabase_client()
            res = supabase.table("watched_companies").select("*").eq("is_active", True).execute()
            rows = res.data or []
            now = datetime.now(timezone.utc)
            for company in rows:
                row_id = str(company.get("id") or "")
                if not row_id:
                    continue
                freq = (company.get("scrape_frequency") or "daily").lower()
                if freq not in ("daily", "weekly"):
                    freq = "daily"
                last = company.get("last_scraped_at")
                last_dt = _watched_parse_last_scraped_ts(last)
                if last_dt is None:
                    due = True
                else:
                    if last_dt.tzinfo is None:
                        last_dt = last_dt.replace(tzinfo=timezone.utc)
                    delta = (now - last_dt).total_seconds()
                    due = delta >= (86400 if freq == "daily" else 604800)
                if not due:
                    continue
                with _watched_scrape_inflight_lock:
                    if row_id in _watched_scrape_inflight:
                        continue
                    _watched_scrape_inflight.add(row_id)
                try:
                    now_iso = now.isoformat()
                    supabase.table("watched_companies").update({"last_scraped_at": now_iso}).eq(
                        "id", row_id
                    ).execute()
                except Exception as ex:
                    with _watched_scrape_inflight_lock:
                        _watched_scrape_inflight.discard(row_id)
                    print(f"watched_companies scheduler: bump last_scraped_at failed {row_id}: {ex}")
                    continue
                threading.Thread(
                    target=_watched_company_scrape_thread, args=(dict(company),), daemon=True
                ).start()
        except Exception as e:
            print(f"Watched companies scheduler error: {e}")
