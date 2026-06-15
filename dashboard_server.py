import os
import sys
import json
import re
import base64
import urllib.parse
import subprocess
import threading
import time
import uuid
from datetime import datetime, date, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from dotenv import load_dotenv
import requests

from jobsearch_paths import workspace_root
from benefits_extractor import extract_benefits
from near_dedup import group_and_flag_duplicates
from jobsearch_webhook import effective_webhook_url, public_config_for_api
from notion_sqlite_mirror import upsert_notion_job_report, ensure_notion_mirror_schema
from services.resume_service import generate_resume

# Load env variables from repo root
WORKSPACE_DIR = str(workspace_root())
load_dotenv(dotenv_path=os.path.join(WORKSPACE_DIR, ".env"))

_scripts_dir = os.path.join(WORKSPACE_DIR, "scripts")
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)
if WORKSPACE_DIR not in sys.path:
    sys.path.insert(0, WORKSPACE_DIR)
from pipeline_metrics import append_pipeline_metric  # noqa: E402
import jobsearch_constants as jc  # noqa: E402

# Authentication passwords
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")
USER_PASSWORD = os.environ.get("USER_PASSWORD", "user123")
if ADMIN_PASSWORD == "admin123" and USER_PASSWORD == "user123":
    print("WARNING: Using default fallback credentials ('admin123' and 'user123'). Please set ADMIN_PASSWORD and USER_PASSWORD in your .env file.")

# In-memory session store: token -> dict mapping {"role": role, "email": email}
active_sessions = {}

# Password hashing helpers
import hashlib
import secrets

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    pw_hash = hashlib.sha256((salt + password).encode('utf-8')).hexdigest()
    return f"{salt}:{pw_hash}"

def verify_password(password: str, stored_hash: str) -> bool:
    try:
        salt, pw_hash = stored_hash.split(":", 1)
        calc_hash = hashlib.sha256((salt + password).encode('utf-8')).hexdigest()
        return secrets.compare_digest(calc_hash, pw_hash)
    except Exception:
        return False

# Database user helpers
def verify_user_credentials(email, password):
    from notion_sqlite_mirror import db_path, ensure_notion_mirror_schema
    import sqlite3
    ensure_notion_mirror_schema(WORKSPACE_DIR)
    db_file = db_path(WORKSPACE_DIR)
    
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    created_at = datetime.utcnow().isoformat()
    
    # Verify/Seed admin@hailmary.ai
    cursor.execute("SELECT password_hash FROM users WHERE email = ?", ("admin@hailmary.ai",))
    admin_row = cursor.fetchone()
    if not admin_row:
        admin_hash = hash_password(ADMIN_PASSWORD)
        conn.execute("INSERT INTO users (email, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
                     ("admin@hailmary.ai", admin_hash, "admin", created_at))
        conn.commit()
    elif not verify_password(ADMIN_PASSWORD, admin_row["password_hash"]):
        admin_hash = hash_password(ADMIN_PASSWORD)
        conn.execute("UPDATE users SET password_hash = ? WHERE email = ?", (admin_hash, "admin@hailmary.ai"))
        conn.commit()

    # Verify/Seed user@hailmary.ai
    cursor.execute("SELECT password_hash FROM users WHERE email = ?", ("user@hailmary.ai",))
    user_row = cursor.fetchone()
    if not user_row:
        user_hash = hash_password(USER_PASSWORD)
        conn.execute("INSERT INTO users (email, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
                     ("user@hailmary.ai", user_hash, "user", created_at))
        conn.commit()
    elif not verify_password(USER_PASSWORD, user_row["password_hash"]):
        user_hash = hash_password(USER_PASSWORD)
        conn.execute("UPDATE users SET password_hash = ? WHERE email = ?", (user_hash, "user@hailmary.ai"))
        conn.commit()
        
    cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
    user = cursor.fetchone()
    conn.close()
    
    if user and verify_password(password, user["password_hash"]):
        return {"email": user["email"], "role": user["role"]}
    return None

def register_user(email, password, role="user"):
    from notion_sqlite_mirror import db_path, ensure_notion_mirror_schema
    import sqlite3
    ensure_notion_mirror_schema(WORKSPACE_DIR)
    db_file = db_path(WORKSPACE_DIR)
    
    conn = sqlite3.connect(str(db_file))
    cursor = conn.cursor()
    
    cursor.execute("SELECT 1 FROM users WHERE email = ?", (email,))
    if cursor.fetchone():
        conn.close()
        return False, "Email already registered"
        
    pw_hash = hash_password(password)
    created_at = datetime.utcnow().isoformat()
    try:
        conn.execute("INSERT INTO users (email, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
                     (email, pw_hash, role, created_at))
        conn.commit()
        conn.close()
        return True, "User registered successfully"
    except Exception as e:
        conn.close()
        return False, str(e)

# Filename scoping helper
def resolve_path(base_path, email=None):
    if not email:
        return base_path
    suffix = re.sub(r'[^a-zA-Z0-9_.-]', '_', email)
    dir_name, file_name = os.path.split(base_path)
    name, ext = os.path.splitext(file_name)
    scoped_file_name = f"{name}_{suffix}{ext}"
    return os.path.join(dir_name, scoped_file_name)

# HTTP API + dashboard backend (default 8080). Override if port is busy:
#   JOBSEARCH_DASHBOARD_PORT=8081 python3 dashboard_server.py
PORT = int(os.environ.get("JOBSEARCH_DASHBOARD_PORT", "8080"))
CONFIG_PATH = os.path.join(WORKSPACE_DIR, "config.json")
POLICY_CONFIG_PATH = os.path.join(WORKSPACE_DIR, "policy_config.json")
APPROVED_PATH = os.path.join(WORKSPACE_DIR, "approved_jobs.json")
FAILED_PATH = os.path.join(WORKSPACE_DIR, "failed_candidate_jobs.json")
ACTIVE_PATH = os.path.join(WORKSPACE_DIR, "active_candidate_jobs.json")
SYNCED_PATH = os.path.join(WORKSPACE_DIR, "synced_jobs.json")

# User-scoped scraper and stale check status stores
scraper_states = {}
stale_check_states = {}

# Company-targeted scraper status (keyed by authenticated email)
_COMPANY_SCRAPER_PROGRESS = "COMPANY_SCRAPER_PROGRESS:"
_company_scraper_states = {}
_company_scraper_states_lock = threading.Lock()


def _default_company_scraper_state():
    return {
        "status": "idle",
        "phase": "Idle",
        "phase_key": "idle",
        "started_at": None,
        "finished_at": None,
        "duration_seconds": None,
        "summary": None,
        "error": None,
        "input": None,
    }


def _company_scraper_phase_label(phase_key: str) -> str:
    return {
        "idle": "Idle",
        "discovering": "Discovering careers page...",
        "scraping": "Scraping jobs...",
        "filtering": "Filtering IT jobs...",
        "saving": "Saving to database...",
        "completed": "Completed",
        "failed": "Failed",
    }.get(phase_key or "", "Scraping jobs...")


def get_company_scraper_state(email):
    email_key = (email or "").strip() or "admin@hailmary.ai"
    with _company_scraper_states_lock:
        if email_key not in _company_scraper_states:
            _company_scraper_states[email_key] = _default_company_scraper_state()
        return dict(_company_scraper_states[email_key])

def get_scraper_state(email):
    email_key = email or "admin@hailmary.ai"
    if email_key not in scraper_states:
        scraper_states[email_key] = {
            "status": "idle",
            "message": "Scraper is ready.",
            "last_run": None,
            "last_error": None,
            "last_metrics": {},
        }
    return scraper_states[email_key]

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


def _invalidate_jobs_cache(email=None):
    email_key = email or "admin@hailmary.ai"
    _cached_jobs_data.pop(email_key, None)
    _cached_jobs_mtimes.pop(email_key, None)


_ZERO_UUID_STR = "00000000-0000-0000-0000-000000000000"


def _valid_scrape_tracker_user_id(uid) -> bool:
    return bool(uid and str(uid).strip() and str(uid).strip() != _ZERO_UUID_STR)


def _fetch_user_scrape_runs(uid, limit=20):
    try:
        from supabase_client import get_supabase_client

        if not _valid_scrape_tracker_user_id(uid):
            return []
        r = (
            get_supabase_client()
            .table("scrape_runs")
            .select("*")
            .eq("user_id", uid)
            .order("started_at", desc=True)
            .limit(int(limit))
            .execute()
        )
        return r.data or []
    except Exception:
        return []


def _fetch_user_scrape_run(uid, run_id):
    try:
        uuid.UUID(str(run_id))
        from supabase_client import get_supabase_client

        if not _valid_scrape_tracker_user_id(uid):
            return None
        r = (
            get_supabase_client()
            .table("scrape_runs")
            .select("*")
            .eq("user_id", uid)
            .eq("id", str(run_id))
            .maybe_single()
            .execute()
        )
        return r.data
    except Exception:
        return None


def _fetch_user_active_scrape_runs(uid):
    try:
        from supabase_client import get_supabase_client

        if not _valid_scrape_tracker_user_id(uid):
            return []
        r = (
            get_supabase_client()
            .table("scrape_runs")
            .select("*")
            .eq("user_id", uid)
            .in_("status", ["queued", "running"])
            .order("started_at", desc=True)
            .execute()
        )
        return r.data or []
    except Exception:
        return []


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
    from company_scraper.filters import merge_it_prefs

    db_prefs: dict = {}
    if _valid_scrape_tracker_user_id(user_id):
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
        script = os.path.join(WORKSPACE_DIR, "company_scraper", "main.py")
        p = subprocess.run(
            [sys.executable, script, b64],
            cwd=WORKSPACE_DIR,
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
    if not job_url:
        return False, "Missing job_url"

    approved_path = resolve_path(APPROVED_PATH, email)
    failed_path = resolve_path(FAILED_PATH, email)
    active_path = resolve_path(ACTIVE_PATH, email)

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
        _invalidate_jobs_cache(email)
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

    _invalidate_jobs_cache(email)
    return True, ""

def stale_check_worker(email=None):
    state = get_stale_check_state(email)
    state["status"] = "running"
    state["progress"] = 0
    state["total"] = 0
    state["completed"] = 0
    state["stale_found"] = 0
    
    approved_path = resolve_path(APPROVED_PATH, email)
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
                
            updated_jobs.append(job)
            state["completed"] = idx + 1
            state["progress"] = int((idx + 1) / len(approved_jobs) * 100)
            time.sleep(1)
            
        with open(approved_path, 'w') as f:
            json.dump(updated_jobs, f, indent=2)
            
    except Exception as e:
        print(f"Error in stale check worker: {e}")
    finally:
        state["status"] = "idle"

def archive_job_on_disk(url, email=None):
    if not url:
        return False, "Missing job_url"
        
    approved = []
    approved_path = resolve_path(APPROVED_PATH, email)
    if os.path.exists(approved_path):
        try:
            with open(approved_path, 'r') as f:
                approved = json.load(f)
        except Exception:
            pass
            
    failed = []
    failed_path = resolve_path(FAILED_PATH, email)
    if os.path.exists(failed_path):
        try:
            with open(failed_path, 'r') as f:
                failed = json.load(f)
        except Exception:
            pass
            
    active = []
    active_path = resolve_path(ACTIVE_PATH, email)
    if os.path.exists(active_path):
        try:
            with open(active_path, 'r') as f:
                active = json.load(f)
        except Exception:
            pass
            
    found = False
    
    # Check SQLite database mirror first
    from notion_sqlite_mirror import db_path, ensure_notion_mirror_schema
    try:
        ensure_notion_mirror_schema(WORKSPACE_DIR)
        db_file = db_path(WORKSPACE_DIR)
        if os.path.exists(db_file):
            import sqlite3
            conn = sqlite3.connect(str(db_file))
            cursor = conn.cursor()
            row = cursor.execute("SELECT 1 FROM notion_job_reports WHERE job_url = ? AND user_email = ?", (url, email or 'admin@hailmary.ai')).fetchone()
            if row:
                conn.execute("UPDATE notion_job_reports SET archived = 1 WHERE job_url = ? AND user_email = ?", (url, email or 'admin@hailmary.ai'))
                conn.commit()
                found = True
            conn.close()
    except Exception as e:
        print(f"Error archiving job in SQLite mirror: {e}")
    
    for j in approved:
        if j.get("job_url") == url:
            j["archived"] = True
            found = True
            
    for j in failed:
        if j.get("job_url") == url:
            j["archived"] = True
            found = True
            
    for j in active:
        if j.get("job_url") == url:
            j["archived"] = True
            found = True
            
    if not found:
        return False, "Job not found in any database."
        
    try:
        with open(approved_path, 'w') as f:
            json.dump(approved, f, indent=2)
        with open(failed_path, 'w') as f:
            json.dump(failed, f, indent=2)
        with open(active_path, 'w') as f:
            json.dump(active, f, indent=2)
    except Exception as e:
        return False, f"Failed to save archived state: {e}"
        
    return True, "Job archived successfully."

def load_config(email=None):
    path = resolve_path(CONFIG_PATH, email)
    if os.path.exists(path):
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading config file {path}: {e}")
    # Default config
    return {
        "target_titles": list(jc.DEFAULT_TARGET_TITLES),
        "scheduler": {
            "enabled": True,
            "run_at_hour": 8,
            "run_at_minute": 0
        },
        "webhook_url": "",
        "search": {
            "country_phrase": "United States",
            "include_remote_primary_boards": True,
            "merge_previous_scrape": True,
            "send_digest_only": True,
            "max_digest_items": 10,
        },
    }

def save_config(cfg, email=None):
    try:
        cfg = dict(cfg)
        if os.environ.get("JOBSEARCH_WEBHOOK_URL", "").strip():
            cfg.pop("webhook_url", None)
        path = resolve_path(CONFIG_PATH, email)
        with open(path, 'w') as f:
            json.dump(cfg, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving config file: {e}")
        return False

def load_policy_config(email=None):
    path = resolve_path(POLICY_CONFIG_PATH, email)
    if os.path.exists(path):
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading policy config {path}: {e}")
    return {
        "max_experience_years": 8,
        "min_salary_annual": 80000,
        "min_salary_hourly": 50,
        "enforce_visa_sponsorship": True,
        "enforce_no_clearance": True,
        "custom_red_flag_keywords": []
    }

def save_policy_config(cfg, email=None):
    try:
        path = resolve_path(POLICY_CONFIG_PATH, email)
        with open(path, 'w') as f:
            json.dump(cfg, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving policy config: {e}")
        return False

def rebuild_classifier_prompt(config):
    prompt_path = os.path.join(WORKSPACE_DIR, "Job_classifier_prompt.txt")
    if not os.path.exists(prompt_path):
        return False, "Job_classifier_prompt.txt not found"
    try:
        backup_path = prompt_path + ".bak"
        with open(prompt_path, 'r') as f:
            content = f.read()
        with open(backup_path, 'w') as f:
            f.write(content)
        max_exp = int(config.get("max_experience_years", 8))
        min_sal = int(config.get("min_salary_annual", 80000))
        min_sal_hr = int(config.get("min_salary_hourly", 50))
        enforce_visa = bool(config.get("enforce_visa_sponsorship", True))
        enforce_clearance = bool(config.get("enforce_no_clearance", True))
        custom_red_flags = config.get("custom_red_flag_keywords", [])
        
        visa_rules = ""
        if enforce_visa:
            visa_rules = """- no visa sponsorship / not eligible for sponsorship / unable to sponsor visas / does not sponsor work authorization
- cannot sponsor H1B / cannot provide visa sponsorship now or in the future
- not eligible for immigration sponsorship / this role is not eligible for sponsorship
- must be authorized to work in the US without sponsorship / must have permanent work authorization
- no future sponsorship available / without sponsorship now or in the future / work authorization required without sponsorship / no current or future sponsorship"""
        clearance_rules = ""
        if enforce_clearance:
            clearance_rules = """- active security clearance / government clearance / secret clearance / top secret clearance / TS/SCI
- ITAR / International Traffic in Arms Regulations / export control / export-controlled / U.S. export regulations"""
        custom_rules_str = ""
        if custom_red_flags:
            custom_rules_str = "\n".join([f"- {kw}" for kw in custom_red_flags if kw.strip()])
        min_sal_k = f"{min_sal // 1000}k" if min_sal >= 1000 else str(min_sal)
        
        allowed_max_non_sre = max_exp - 2 if max_exp > 2 else 1
        allowed_max_sre = max_exp - 1 if max_exp > 1 else 1
        allowed_non_sre_ranges = " / ".join([f"{i} / {i}+" for i in range(3, allowed_max_non_sre + 1)])
        allowed_sre_ranges = " / ".join([f"{i} / {i}+" for i in range(5, allowed_max_sre + 1)]) if allowed_max_sre >= 5 else "5 / 5+"
        
        new_red_flags_block = f"""## RED FLAG RULES

Hard rule: if any item below is present, you MUST add the matching red flag and MUST set `apply_decision = DO_NOT_APPLY`.

### Work authorization restriction
- US citizenship only / must be US citizen / US citizens only
{visa_rules}
{clearance_rules}
- must be U.S. person / U.S. persons only / as defined by 8 U.S.C. 1324b(a)(3)
{custom_rules_str}
- If any of these appear: add red_flag: "Work authorization restriction"

### Experience requirement violation
- any requirement ≥{max_exp} years
- ranges where upper bound ≥{max_exp}
- no experience mentioned
- treat written numbers the same as digits: three, four, five, six, seven, eight, nine, ten
- treat plus phrasing the same as numeric plus: 3+, 4+, 5+, 6+, 7+, three plus, five plus, seven plus
Allowed experience ranges (non-SRE): {allowed_non_sre_ranges or "3 / 3+"}
ranges where maximum ≤{allowed_max_non_sre}
Allowed experience ranges (SRE): {allowed_sre_ranges}
ranges where maximum ≤{allowed_max_sre}
- If above the allowed cap: add red_flag: "Experience requirement violation"

### Seniority / title violation
- Manager / Director / Principal / Architect / Lead
- Senior and Staff are allowed only when total experience requirement is ≤{max_exp - 1} years
- If experience >{max_exp - 1} years: treat it as R3
- If the title itself violates this rule: add red_flag: "Seniority / title violation"

### Out of scope
- Pure QA
- Pure development
- EDI
- Desktop support
- Data science
- If present: add red_flag: "Out of scope"

### Salary rule
- Salaried full-time: minimum salary < ${min_sal_k} → DO_NOT_APPLY
- Hourly: ≤ ${min_sal_hr}/hr → DO_NOT_APPLY
- If salary is not listed, do not trigger

If red_flags is non-empty:
MUST set apply_decision = DO_NOT_APPLY

--------------------------------------------------
APPLICATION DECISION
--------------------------------------------------

If red_flags is non-empty:
MUST set apply_decision = DO_NOT_APPLY

Return APPLY when the role belongs to the engineering domains above.

Return DO_NOT_APPLY when the role belongs to:

sales
marketing
finance
HR
business operations
pure project management
pure scrum master / delivery coordination without hands-on engineering scope

--------------------------------------------------
---
"""
        start_marker = "## RED FLAG RULES"
        end_marker = "## DATABASE ENGINEER RULE"
        start_idx = content.find(start_marker)
        end_idx = content.find(end_marker)
        if start_idx == -1 or end_idx == -1:
            return False, "Could not find red flag rule boundaries in prompt file"
        new_content = content[:start_idx] + new_red_flags_block + content[end_idx:]
        with open(prompt_path, 'w') as f:
            f.write(new_content)
        return True, "Classifier prompt rebuilt successfully!"
    except Exception as e:
        return False, f"Rebuild failed: {str(e)}"

def load_synced_jobs(email=None):
    path = resolve_path(SYNCED_PATH, email)
    if os.path.exists(path):
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def mark_job_synced(url, page_id, email=None):
    synced = load_synced_jobs(email)
    synced[url] = {
        "page_id": page_id,
        "synced_at": datetime.utcnow().isoformat()
    }
    try:
        path = resolve_path(SYNCED_PATH, email)
        with open(path, 'w') as f:
            json.dump(synced, f, indent=2)
    except Exception as e:
        print(f"Error saving synced jobs: {e}")

_cached_jobs_data = {}
_cached_jobs_mtimes = {}

def load_all_jobs(email=None):
    global _cached_jobs_data, _cached_jobs_mtimes
    
    email_key = email or "admin@hailmary.ai"
    
    approved_path = resolve_path(APPROVED_PATH, email)
    active_path = resolve_path(ACTIVE_PATH, email)
    failed_path = resolve_path(FAILED_PATH, email)
    synced_path = resolve_path(SYNCED_PATH, email)
    
    paths_to_track = {
        "approved": approved_path,
        "active": active_path,
        "failed": failed_path,
        "synced": synced_path
    }
    
    current_mtimes = {}
    for key, path in paths_to_track.items():
        if os.path.exists(path):
            current_mtimes[key] = os.path.getmtime(path)
        else:
            current_mtimes[key] = 0.0
            
    if email_key in _cached_jobs_data and _cached_jobs_mtimes.get(email_key) == current_mtimes:
        return _cached_jobs_data[email_key]
    jobs = []
    approved_urls = set()
    synced_jobs = load_synced_jobs(email)
    
    # Import salary extractor helper
    try:
        from salary_extractor import extract_salary
    except ImportError:
        extract_salary = None

    # Load synced jobs from local SQLite database (Notion mirror)
    from notion_sqlite_mirror import db_path, ensure_notion_mirror_schema
    try:
        ensure_notion_mirror_schema(WORKSPACE_DIR)
        db_file = db_path(WORKSPACE_DIR)
        if os.path.exists(db_file):
            import sqlite3
            conn = sqlite3.connect(str(db_file))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM notion_job_reports WHERE user_email = ?", (email or 'admin@hailmary.ai',))
            rows = cursor.fetchall()
            for row in rows:
                url = row['job_url']
                if not url:
                    continue
                
                red_flags = []
                if row['red_flags_json']:
                    try:
                        red_flags = json.loads(row['red_flags_json'])
                    except Exception:
                        pass
                
                payload = {}
                if row['apply_decision_payload_json']:
                    try:
                        payload = json.loads(row['apply_decision_payload_json'])
                    except Exception:
                        pass
                
                confidence = row['confidence_score']
                if confidence is not None:
                    if confidence <= 1.0:
                        confidence = confidence * 100.0
                else:
                    confidence = 100.0

                j = {
                    "job_title": row['job_title'] or "Unknown Title",
                    "company_name": row['company_name'] or "Unknown",
                    "job_url": url,
                    "requirement_id": row['requirement_id'] or "Unknown",
                    "job_description": row['job_description'] or "",
                    "location_work_type": row['location_work_type'] or "Remote",
                    "scraped_at": row['date_added'] or datetime.utcnow().strftime("%Y-%m-%d"),
                    "red_flags": red_flags,
                    "apply_decision": row['apply_decision'] or "APPLY",
                    "strongest_label": row['strongest_label'] or "DevOps Engineer",
                    "confidence_score": confidence,
                    "rationale": row['rationale'] or "",
                    "apply_decision_payload": payload,
                    "benefits": payload.get("benefits", []),
                    "status": "approved",
                    "synced": True,
                    "synced_data": {
                        "page_id": row['notion_page_id'],
                        "synced_at": row['synced_at']
                    },
                    "source_file": "notion_job_reports.db",
                    "pipeline_stage": row['pipeline_stage'] or 'Approved',
                    "min_salary": row['min_salary'],
                    "max_salary": row['max_salary'],
                    "is_hourly": bool(row['is_hourly']),
                    "salary_text": row['salary_text'],
                    "archived": bool(row['archived'])
                }
                
                # Retroactive salary parsing
                if not j.get('salary_text') and extract_salary and j.get('job_description'):
                    sal_info = extract_salary(j['job_description'], j.get('job_title', ''))
                    if sal_info:
                        j.update(sal_info)
                        
                approved_urls.add(url)
                jobs.append(j)
            conn.close()
    except Exception as e:
        print(f"Error loading jobs from SQLite mirror: {e}")
    
    # Load approved jobs
    approved_path = resolve_path(APPROVED_PATH, email)
    if os.path.exists(approved_path):
        try:
            with open(approved_path, 'r') as f:
                app_jobs = json.load(f)
                for j in app_jobs:
                    url = j.get('job_url')
                    if url in approved_urls:
                        continue
                    j['status'] = 'approved'
                    j['synced'] = url in synced_jobs
                    j['synced_data'] = synced_jobs.get(url)
                    j['source_file'] = 'approved_jobs.json'
                    
                    if 'archived' not in j:
                        j['archived'] = False
                    
                    # Set default pipeline stage
                    if 'pipeline_stage' not in j:
                        j['pipeline_stage'] = 'Approved'
                    
                    # Retroactive salary parsing
                    if not j.get('salary_text') and extract_salary and j.get('job_description'):
                        sal_info = extract_salary(j['job_description'], j.get('job_title', ''))
                        if sal_info:
                            j.update(sal_info)
                            
                    if url:
                        approved_urls.add(url)
                    jobs.append(j)
        except Exception as e:
            print(f"Error reading approved jobs: {e}")

    # Load active candidates
    active_path = resolve_path(ACTIVE_PATH, email)
    if os.path.exists(active_path):
        try:
            with open(active_path, 'r') as f:
                act_jobs = json.load(f)
                for j in act_jobs:
                    url = j.get('job_url')
                    if not url or url in approved_urls:
                        continue
                    
                    # If not approved, it was rejected during classification
                    j['status'] = 'rejected'
                    j['synced'] = url in synced_jobs
                    j['synced_data'] = synced_jobs.get(url)
                    j['source_file'] = 'active_candidate_jobs.json'
                    
                    # Set default pipeline stage
                    if 'pipeline_stage' not in j:
                        j['pipeline_stage'] = 'Unreviewed'
                    
                    # Retroactive salary parsing
                    if not j.get('salary_text') and extract_salary and j.get('job_description'):
                        sal_info = extract_salary(j['job_description'], j.get('job_title', ''))
                        if sal_info:
                            j.update(sal_info)
                    
                    # Fill in defaults if classify_and_save.py didn't write them
                    if 'apply_decision' not in j:
                        j['apply_decision'] = 'DO_NOT_APPLY'
                    if 'strongest_label' not in j:
                        j['strongest_label'] = 'OutOfScope'
                    if 'confidence_score' not in j:
                        j['confidence_score'] = 0
                    if 'rationale' not in j:
                        j['rationale'] = 'Rejected by classification logic (OutOfScope).'
                    jobs.append(j)
        except Exception as e:
            print(f"Error reading active candidates: {e}")

    # Load failed candidate jobs (failed pre-screen)
    failed_path = resolve_path(FAILED_PATH, email)
    if os.path.exists(failed_path):
        try:
            with open(failed_path, 'r') as f:
                fail_jobs = json.load(f)
                for j in fail_jobs:
                    url = j.get('job_url')
                    if not url:
                        continue
                    if any(x.get('job_url') == url for x in jobs):
                        continue
                    j['status'] = 'rejected'
                    j['synced'] = url in synced_jobs
                    j['synced_data'] = synced_jobs.get(url)
                    j['source_file'] = 'failed_candidate_jobs.json'
                    j['apply_decision'] = 'DO_NOT_APPLY'
                    j['strongest_label'] = 'OutOfScope'
                    j['confidence_score'] = 100
                    j['rationale'] = f"Failed pre-screen regex checks. Red flags: {', '.join(j.get('red_flags', []))}"
                    
                    # Set default pipeline stage
                    if 'pipeline_stage' not in j:
                        j['pipeline_stage'] = 'Rejected'
                    
                    # Retroactive salary parsing
                    if not j.get('salary_text') and extract_salary and j.get('job_description'):
                        sal_info = extract_salary(j['job_description'], j.get('job_title', ''))
                        if sal_info:
                            j.update(sal_info)
                            
                    jobs.append(j)
        except Exception as e:
            print(f"Error reading failed candidates: {e}")

    # Retroactively extract benefits if missing
    for j in jobs:
        if "benefits" not in j:
            j["benefits"] = extract_benefits(j.get("job_description", ""))
            
    # Group and flag duplicates, then filter them out
    jobs = group_and_flag_duplicates(jobs)
    jobs = [j for j in jobs if not j.get('is_duplicate')]

    # Cache results
    _cached_jobs_data[email_key] = jobs
    _cached_jobs_mtimes[email_key] = current_mtimes

    return jobs

def calculate_analytics(email=None):
    jobs = load_all_jobs(email)
    total_jobs = len(jobs)
    
    approved_count = 0
    rejected_count = 0
    pending_count = 0
    
    labels_distribution = {}
    sources_distribution = {}
    rejection_reasons = {
        "Work authorization restriction": 0,
        "Experience requirement violation": 0,
        "Seniority / title violation": 0,
        "Out of scope": 0,
        "Salary rule": 0,
        "Manual Disapproval": 0,
        "Other / Pre-screen fail": 0
    }
    
    for j in jobs:
        decision = j.get("apply_decision")
        red_flags = j.get("red_flags", [])
        
        if decision == 'APPLY' and not red_flags:
            approved_count += 1
            lbl = j.get("strongest_label", "DevOps Engineer")
            labels_distribution[lbl] = labels_distribution.get(lbl, 0) + 1
        elif decision == 'DO_NOT_APPLY' or red_flags:
            rejected_count += 1
            if red_flags:
                for rf in red_flags:
                    rejection_reasons[rf] = rejection_reasons.get(rf, 0) + 1
            else:
                rejection_reasons["Other / Pre-screen fail"] += 1
        else:
            pending_count += 1
            
        url = j.get("job_url", "")
        if url:
            domain = urllib.parse.urlparse(url).netloc
            if "greenhouse.io" in domain:
                src = "Greenhouse"
            elif "lever.co" in domain:
                src = "Lever"
            elif "myworkdayjobs.com" in domain:
                src = "Workday"
            elif "ashbyhq.com" in domain:
                src = "Ashby"
            elif "workable.com" in domain:
                src = "Workable"
            elif "smartrecruiters.com" in domain:
                src = "SmartRecruiters"
            elif "weworkremotely.com" in domain:
                src = "We Work Remotely"
            elif "remote.co" in domain:
                src = "Remote.co"
            elif "linkedin.com" in domain:
                src = "LinkedIn"
            elif "workatastartup.com" in domain or "ycombinator.com" in domain:
                src = "Y Combinator"
            else:
                src = domain or "Other"
            sources_distribution[src] = sources_distribution.get(src, 0) + 1
            
    approval_rate = round((approved_count / total_jobs * 100), 1) if total_jobs > 0 else 0
    
    return {
        "total_sourced": total_jobs,
        "approved": approved_count,
        "rejected": rejected_count,
        "pending": pending_count,
        "approval_rate": approval_rate,
        "labels_distribution": labels_distribution,
        "sources_distribution": sources_distribution,
        "rejection_reasons": rejection_reasons
    }

def override_job_on_disk(updated_job, email=None):
    url = updated_job.get("job_url")
    if not url:
        return False, "Missing job_url"
        
    approved_path = resolve_path(APPROVED_PATH, email)
    failed_path = resolve_path(FAILED_PATH, email)
    active_path = resolve_path(ACTIVE_PATH, email)
    
    approved = []
    if os.path.exists(approved_path):
        try:
            with open(approved_path, 'r') as f:
                approved = json.load(f)
        except Exception:
            pass
            
    failed = []
    if os.path.exists(failed_path):
        try:
            with open(failed_path, 'r') as f:
                failed = json.load(f)
        except Exception:
            pass
            
    active = []
    if os.path.exists(active_path):
        try:
            with open(active_path, 'r') as f:
                active = json.load(f)
        except Exception:
            pass
            
    # Find the job
    target_job = None
    
    # 1. Look in approved
    for j in approved:
        if j.get("job_url") == url:
            target_job = j
            break
            
    # 2. Look in failed (remove if overridden to approved)
    if not target_job:
        for j in failed:
            if j.get("job_url") == url:
                target_job = j
                failed = [x for x in failed if x.get("job_url") != url]
                break
                
    # 3. Look in active
    if not target_job:
        for j in active:
            if j.get("job_url") == url:
                target_job = j
                break
                
    if not target_job:
        target_job = {}
        
    # Update fields
    decision = updated_job.get("apply_decision", "APPLY")
    red_flags = updated_job.get("red_flags", [])
    if decision == "APPLY":
        red_flags = []
        
    allowed_categories = {
        "DevOps Engineer", "Cloud Automation Engineer", "Platform Engineering", 
        "Cloud Infrastructure Engineer", "Cloud Security Engineer", "DevSecOps", 
        "Site Reliability Engineer (SRE)", "Continuous Integration (CI/CD)", 
        "System Engineer", "Cloud Network Engineer", "Data Platform Engineer", 
        "Machine Learning Engineer (MLOps)", "AI Platform Engineer (AIOps)"
    }
    label = updated_job.get("strongest_label", target_job.get("strongest_label", "DevOps Engineer") if target_job else "DevOps Engineer")
    if decision == "APPLY" and label not in allowed_categories:
        return False, f"Category '{label}' is not allowed under the active MAAS classifier policy guidelines."
        
    target_job.update({
        "job_url": url,
        "job_title": updated_job.get("job_title", target_job.get("job_title", "Unknown Title")),
        "company_name": updated_job.get("company_name", target_job.get("company_name", "Unknown")),
        "requirement_id": updated_job.get("requirement_id", target_job.get("requirement_id", "Unknown")),
        "location_work_type": updated_job.get("location_work_type", target_job.get("location_work_type", "Remote")),
        "job_description": updated_job.get("job_description", target_job.get("job_description", "")),
        "red_flags": red_flags,
        "apply_decision": decision,
        "strongest_label": updated_job.get("strongest_label", target_job.get("strongest_label", "DevOps Engineer")),
        "confidence_score": updated_job.get("confidence_score", target_job.get("confidence_score", 100)),
        "rationale": updated_job.get("rationale", target_job.get("rationale", "Manually modified override via dashboard.")),
        "cloud": updated_job.get("cloud", target_job.get("cloud", "Not specified")),
        "seniority": updated_job.get("seniority", target_job.get("seniority", "Not specified")),
        "source": updated_job.get("source", target_job.get("source", "Not specified")),
        "pipeline_stage": updated_job.get("pipeline_stage", target_job.get("pipeline_stage", "Approved")),
        "min_salary": updated_job.get("min_salary", target_job.get("min_salary")),
        "max_salary": updated_job.get("max_salary", target_job.get("max_salary")),
        "is_hourly": updated_job.get("is_hourly", target_job.get("is_hourly", False)),
        "salary_text": updated_job.get("salary_text", target_job.get("salary_text")),
    })

    # If the user passed apply_decision_payload, use it. Otherwise, construct it.
    passed_payload = updated_job.get("apply_decision_payload")
    if passed_payload:
        target_job["apply_decision_payload"] = passed_payload
    else:
        target_job["apply_decision_payload"] = {
            "apply_decision": decision,
            "strongest_label": target_job["strongest_label"],
            "red_flags": red_flags,
            "confidence_score": target_job["confidence_score"],
            "rationale": target_job["rationale"],
            "cloud": {
                "is_cloud_role": target_job["cloud"] != "Not specified",
                "primary_cloud": target_job["cloud"] if target_job["cloud"] != "Not specified" else "",
                "cloud_providers": [target_job["cloud"]] if target_job["cloud"] != "Not specified" else []
            }
        }
    
    # Save to appropriate list
    approved = [j for j in approved if j.get("job_url") != url]
    failed = [j for j in failed if j.get("job_url") != url]
    active = [j for j in active if j.get("job_url") != url]
    
    if decision == "APPLY":
        approved.append(target_job)
        msg = "Job successfully approved and saved."
    else:
        failed.append(target_job)
        msg = "Job successfully rejected and saved."
        
    try:
        with open(approved_path, 'w') as f:
            json.dump(approved, f, indent=2)
        with open(failed_path, 'w') as f:
            json.dump(failed, f, indent=2)
        with open(active_path, 'w') as f:
            json.dump(active, f, indent=2)
        return True, msg
    except Exception as e:
        return False, f"Failed to save changes: {str(e)}"

# Notion Sync Engine
def clean_text_for_notion(text, limit=2000):
    if not text:
        return ""
    if len(text) > limit:
        return text[:limit-3] + "..."
    return text

def build_notion_properties(job, db_properties=None):
    # Ensure correct confidence score formatting for percentage field (95% -> 0.95)
    score = float(job.get("confidence_score", 0))
    if score > 1.0:
        score = score / 100.0
        
    all_possible_props = {
        "Job Title": {
            "title": [{"text": {"content": job.get("job_title", "Unknown Title")}}]
        },
        "Requirement ID": {
            "rich_text": [{"text": {"content": job.get("requirement_id", "Unknown")}}]
        },
        "Job URL": {
            "url": job.get("job_url", "")
        },
        "Company Name": {
            "rich_text": [{"text": {"content": job.get("company_name", "Unknown")}}]
        },
        "Location + Work Type": {
            "rich_text": [{"text": {"content": job.get("location_work_type", "Remote")}}]
        },
        "Job Description": {
            "rich_text": [{"text": {"content": clean_text_for_notion(job.get("job_description", ""))}}]
        },
        "Strongest Label": {
            "rich_text": [{"text": {"content": job.get("strongest_label", "OutOfScope")}}]
        },
        "Confidence Score": {
            "number": score
        },
        "Rationale": {
            "rich_text": [{"text": {"content": clean_text_for_notion(job.get("rationale", ""))}}]
        },
        "Apply Decision Payload": {
            "rich_text": [{"text": {"content": clean_text_for_notion(json.dumps(job.get("apply_decision_payload", {}), indent=2), limit=2000)}}]
        },
        "Date Added": {
            "date": {"start": datetime.utcnow().strftime("%Y-%m-%d")}
        }
    }
    
    # Sync optional pipeline and salary fields if defined
    if job.get("pipeline_stage"):
        all_possible_props["Pipeline Stage"] = {
            "select": {"name": job.get("pipeline_stage")}
        }
    if job.get("salary_text"):
        all_possible_props["Salary Range"] = {
            "rich_text": [{"text": {"content": job.get("salary_text")}}]
        }

    props = {}
    if db_properties:
        # Intersect keys and format dynamically based on database properties schema
        for prop_name, prop_def in db_properties.items():
            prop_type = prop_def.get("type")
            
            if prop_name == "Apply Decision":
                decision_val = job.get("apply_decision", "APPLY")
                if prop_type == "select":
                    allowed = [opt.get("name") for opt in prop_def.get("select", {}).get("options", [])]
                    if allowed and decision_val not in allowed:
                        matched = next((opt for opt in allowed if opt.lower() == decision_val.lower()), None)
                        decision_val = matched if matched else (allowed[0] if allowed else "APPLY")
                    props["Apply Decision"] = {"select": {"name": decision_val}}
                else:
                    props["Apply Decision"] = {"rich_text": [{"text": {"content": decision_val}}]}
                    
            elif prop_name == "Red Flags":
                red_flags = job.get("red_flags", [])
                if isinstance(red_flags, str):
                    red_flags = [red_flags] if red_flags else []
                if prop_type == "multi_select":
                    allowed = [opt.get("name") for opt in prop_def.get("multi_select", {}).get("options", [])]
                    valid_flags = []
                    for flag in red_flags:
                        if flag:
                            flag_name = flag[:100]
                            if not allowed or flag_name in allowed:
                                valid_flags.append({"name": flag_name})
                            else:
                                matched = next((opt for opt in allowed if opt.lower() == flag_name.lower()), None)
                                if matched:
                                    valid_flags.append({"name": matched})
                    props["Red Flags"] = {"multi_select": valid_flags}
                else:
                    props["Red Flags"] = {"rich_text": [{"text": {"content": ", ".join(red_flags)}}]}
                    
            elif prop_name in all_possible_props:
                props[prop_name] = all_possible_props[prop_name]
    else:
        # Fallback if DB schema retrieval failed
        props = all_possible_props
        props["Apply Decision"] = {
            "select": {"name": job.get("apply_decision", "APPLY")}
        }
        red_flags = job.get("red_flags", [])
        if isinstance(red_flags, str):
            red_flags = [red_flags] if red_flags else []
        props["Red Flags"] = {
            "multi_select": [{"name": flag[:100]} for flag in red_flags if flag]
        }
        
    return props

def build_page_children(job_description):
    children = []
    if not job_description:
        return children

    paragraphs = job_description.split("\n")
    current_block = ""
    
    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
        if len(current_block) + len(p) + 2 > 2000:
            children.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": current_block}}]
                }
            })
            current_block = p
        else:
            if current_block:
                current_block += "\n" + p
            else:
                current_block = p
                
    if current_block:
        children.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": current_block}}]
            }
        })
        
    return children[:100]

def check_job_exists_in_notion(job, token, database_id):
    """Check if the job already exists in the Notion database by URL or Req ID."""
    db_url = f"https://api.notion.com/v1/databases/{database_id}/query"
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json"
    }
    
    # 1. Check by Job URL
    job_url = job.get("job_url")
    if job_url:
        payload = {
            "filter": {
                "property": "Job URL",
                "url": {
                    "equals": job_url
                }
            }
        }
        try:
            r = requests.post(db_url, headers=headers, json=payload, timeout=10)
            if r.status_code == 200 and r.json().get("results"):
                return True, r.json()["results"][0]["id"]
        except Exception as e:
            print(f"Warning: URL duplicate check error: {e}")
            
    # 2. Check by Requirement ID
    req_id = job.get("requirement_id")
    if req_id and req_id != "Unknown":
        payload = {
            "filter": {
                "property": "Requirement ID",
                "rich_text": {
                    "equals": req_id
                }
            }
        }
        try:
            r = requests.post(db_url, headers=headers, json=payload, timeout=10)
            if r.status_code == 200 and r.json().get("results"):
                return True, r.json()["results"][0]["id"]
        except Exception as e:
            print(f"Warning: Req ID duplicate check error: {e}")
            
    return False, None


def _mirror_notion_row_to_sqlite(job, page_id, database_id, was_duplicate, email=None):
    try:
        upsert_notion_job_report(
            job,
            page_id,
            database_id,
            was_duplicate=was_duplicate,
            workspace=WORKSPACE_DIR,
            user_email=email or 'admin@hailmary.ai',
        )
    except Exception as e:
        print(f"SQLite Notion mirror warning: {e}")


def sync_job_to_notion(job, token, database_id, email=None):
    # Check duplicate first
    exists, page_id = check_job_exists_in_notion(job, token, database_id)
    if exists:
        _mirror_notion_row_to_sqlite(job, page_id, database_id, was_duplicate=True, email=email)
        return True, page_id, None

    # Fetch database schema to handle columns dynamically
    db_properties = {}
    try:
        db_url = f"https://api.notion.com/v1/databases/{database_id}"
        db_res = requests.get(db_url, headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": "2022-06-28"
        }, timeout=5)
        if db_res.status_code == 200:
            db_properties = db_res.json().get("properties", {})
        else:
            print(f"Notion schema check returned status {db_res.status_code}: {db_res.text}")
    except Exception as e:
        print(f"Notion DB schema retrieval warning: {e}")

    url = "https://api.notion.com/v1/pages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }
    
    properties = build_notion_properties(job, db_properties)
    children = build_page_children(job.get("job_description", ""))
    
    payload = {
        "parent": {"database_id": database_id},
        "properties": properties,
        "children": children
    }
    
    response = requests.post(url, headers=headers, json=payload)
    if response.status_code == 200:
        data = response.json()
        page_id = data.get("id")
        _mirror_notion_row_to_sqlite(job, page_id, database_id, was_duplicate=False, email=email)
        return True, page_id, None
    else:
        # Fallback formatting: if it failed, retry by stripping optional/mismatched properties
        print(f"Notion sync warning: {response.text}. Retrying with simplified fallback...")
        # Strip properties that might have caused a schema check failure (like Pipeline Stage or Salary Range)
        properties.pop("Pipeline Stage", None)
        properties.pop("Salary Range", None)
        
        # Override select/multi_select with simple rich_text if they caused errors
        properties["Apply Decision"] = {
            "rich_text": [{"text": {"content": job.get("apply_decision", "APPLY")}}]
        }
        properties["Red Flags"] = {
            "rich_text": [{"text": {"content": ", ".join(job.get("red_flags", []))}}]
        }
        payload["properties"] = properties
        
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code == 200:
            data = response.json()
            page_id = data.get("id")
            _mirror_notion_row_to_sqlite(job, page_id, database_id, was_duplicate=False, email=email)
            return True, page_id, None
        else:
            return False, None, response.text

# Webhook Notification Dispatcher
def send_webhook_alert(job, page_id, custom_msg=None, email=None):
    cfg = load_config(email)
    webhook_url = effective_webhook_url(cfg)
    if not webhook_url:
        return False
        
    try:
        notion_url = f"https://notion.so/{page_id.replace('-', '')}" if page_id else ""
        
        if custom_msg:
            payload = {"text": custom_msg}
        else:
            # Styled markdown notification (Slack/Discord compatible)
            payload = {
                "text": f"🎉 **New Job Saved to Notion!**\n"
                        f"🏢 **Company**: {job.get('company_name')}\n"
                        f"💼 **Title**: {job.get('job_title')}\n"
                        f"🏷️ **Role**: {job.get('strongest_label')}\n"
                        f"📍 **Location**: {job.get('location_work_type', 'Remote')}\n"
                        f"🆔 **Req ID**: {job.get('requirement_id', 'Unknown')}\n"
                        f"🔗 **Links**: [Career Site]({job.get('job_url')}) | [Notion Database Page]({notion_url})\n"
                        f"📝 **Rationale**: {job.get('rationale', 'No rationale provided.')}"
            }
            
            # If it's a Discord webhook, we can optionally format as embeds
            if "discord.com" in webhook_url:
                payload = {
                    "embeds": [{
                        "title": "🎉 New Job Synced to Notion!",
                        "color": 6512369, # Indigo
                        "fields": [
                            {"name": "Company", "value": job.get('company_name', 'Unknown'), "inline": True},
                            {"name": "Title", "value": job.get('job_title', 'Unknown'), "inline": True},
                            {"name": "Role Type", "value": job.get('strongest_label', 'Unknown'), "inline": True},
                            {"name": "Req ID", "value": job.get('requirement_id', 'Unknown'), "inline": True},
                            {"name": "Location", "value": job.get('location_work_type', 'Remote'), "inline": True},
                            {"name": "Notion Link", "value": f"[View Page]({notion_url})" if notion_url else "N/A", "inline": True}
                        ],
                        "description": f"**Rationale**: {job.get('rationale', 'No rationale')}\n\n[Apply Directly on Career Site]({job.get('job_url')})"
                    }]
                }
                
        r = requests.post(webhook_url, json=payload, timeout=10)
        return r.status_code in [200, 204]
    except Exception as e:
        print(f"Error sending webhook notification: {e}")
        return False

def send_daily_digest_alert(synced_jobs, total_synced_count):
    cfg = load_config()
    webhook_url = effective_webhook_url(cfg)
    if not webhook_url:
        return False
        
    try:
        search_cfg = cfg.get("search") or {}
        max_items = search_cfg.get("max_digest_items", 10)
        
        # Build Discord Embed
        if "discord.com" in webhook_url:
            fields = []
            for job, page_id in synced_jobs[:max_items]:
                notion_url = f"https://notion.so/{page_id.replace('-', '')}" if page_id else ""
                job_title = job.get('job_title', 'Unknown Title')
                company = job.get('company_name', 'Unknown Company')
                role = job.get('strongest_label', 'Unknown Role')
                loc = job.get('location_work_type', 'Remote')
                conf = job.get('confidence_score')
                if conf is not None:
                    if conf <= 1.0:
                        conf = int(conf * 100)
                    else:
                        conf = int(conf)
                    conf_str = f" ({conf}% Match)"
                else:
                    conf_str = ""
                    
                fields.append({
                    "name": f"💼 {job_title} @ {company}",
                    "value": f"🏷️ **Role**: {role}{conf_str}\n"
                             f"📍 **Location**: {loc}\n"
                             f"🔗 [Career Site]({job.get('job_url')}) | [Notion Page]({notion_url})\n"
                             f"📝 **Rationale**: {job.get('rationale', 'No rationale provided.')[:150]}..."
                })
                
            overflow = total_synced_count - len(fields)
            desc = f"Successfully synced **{total_synced_count}** new approved jobs to Notion in this sourcing run!"
            if overflow > 0:
                desc += f"\n*(Showing top {max_items} jobs. {overflow} more synced to Notion)*"
                
            payload = {
                "embeds": [{
                    "title": "💼 MAAS Job Sourcing Run Digest",
                    "color": 3447003, # Dark Slate / Blue
                    "description": desc,
                    "fields": fields,
                    "timestamp": datetime.utcnow().isoformat()
                }]
            }
        else:
            # Plain text fallback (Slack or other text webhook)
            lines = [f"💼 **MAAS Job Sourcing Run Digest**", f"Successfully synced *{total_synced_count}* new approved jobs to Notion!"]
            for job, page_id in synced_jobs[:max_items]:
                notion_url = f"https://notion.so/{page_id.replace('-', '')}" if page_id else ""
                lines.append(f"• *{job.get('job_title')}* at *{job.get('company_name')}* ({job.get('location_work_type', 'Remote')}) - <{notion_url}|Notion Page> | <{job.get('job_url')}|Apply>")
            overflow = total_synced_count - len(synced_jobs[:max_items])
            if overflow > 0:
                lines.append(f"_...and {overflow} more jobs synced to Notion._")
            payload = {"text": "\n".join(lines)}
            
        r = requests.post(webhook_url, json=payload, timeout=15)
        return r.status_code in [200, 204]
    except Exception as e:
        print(f"Error sending daily digest webhook: {e}")
        return False

def _append_pipeline_log(message):
    log_dir = os.path.join(WORKSPACE_DIR, "logs")
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, "pipeline.log")
    ts = datetime.utcnow().isoformat()
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {message}\n")


# Scraper worker thread
def scraper_worker(email=None, past_24h_only=False, user_id=None, scrape_run_id=None):
    if user_id:
        try:
            from supabase_client import download_user_configs
            download_user_configs(user_id, email)
        except Exception as e:
            print(f"Failed to download configurations from Supabase for user {user_id}: {e}")

    tracker = None
    if scrape_run_id and _valid_scrape_tracker_user_id(user_id):
        try:
            from scrape_tracker import ScrapeTracker

            tracker = ScrapeTracker(
                user_id,
                email or "",
                "pipeline",
                existing_run_id=scrape_run_id,
            )
        except Exception:
            tracker = None

    state = get_scraper_state(email)
    state["status"] = "running"
    state["message"] = "Sourcing jobs..."
    state["last_error"] = None
    state["new_jobs"] = []
    start_time = datetime.utcnow().isoformat()
    state["start_time"] = start_time

    def run_step(cmd, label):
        t0 = time.perf_counter()
        _append_pipeline_log(f"START {label}: {' '.join(cmd)}")
        env = os.environ.copy()
        if email:
            env["MAAS_USER_EMAIL"] = email
        if user_id:
            env["MAAS_USER_ID"] = user_id
        p = subprocess.run(cmd, capture_output=True, text=True, cwd=WORKSPACE_DIR, env=env)
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        append_pipeline_metric(
            WORKSPACE_DIR,
            "pipeline_step",
            {
                "step": label,
                "returncode": p.returncode,
                "duration_ms": elapsed_ms,
                "email": email or "",
                "user_id": user_id or "",
            },
        )
        tail_out = (p.stdout or "")[-12000:]
        tail_err = (p.stderr or "")[-8000:]
        _append_pipeline_log(f"END {label} rc={p.returncode}\n--- stdout ---\n{tail_out}\n--- stderr ---\n{tail_err}")
        return p

    def push_supabase_jobs(reason):
        """Publish merged local artifacts to Supabase after each stage (canonical UI store)."""
        if user_id and tracker:
            tracker.update_stage("saving")
        if not user_id:
            return
        try:
            from supabase_client import upload_user_jobs
            upload_user_jobs(user_id, email or "admin@hailmary.ai")
            _append_pipeline_log(f"Supabase jobs sync ok ({reason})")
        except Exception as e:
            print(f"Failed to upload jobs to Supabase ({reason}): {e}")
            _append_pipeline_log(f"WARN Supabase jobs sync ({reason}): {e}")

    try:
        if tracker:
            tracker.update_stage("scraping")
        cmd = [sys.executable, "find_and_scrape_jobs.py"]
        if past_24h_only:
            cmd.append("--past-24h")
        p1 = run_step(cmd, "find_and_scrape_jobs")
        if p1.returncode != 0:
            state["status"] = "failed"
            err = (p1.stderr or p1.stdout or "").strip() or "Unknown error"
            state["message"] = f"Sourcing script failed: {err[:500]}"
            state["last_error"] = err[:4000]
            if tracker:
                tracker.fail(state["message"])
            return

        push_supabase_jobs("after scrape")

        state["message"] = "Running validation and filtering..."
        if tracker:
            tracker.update_stage("filtering")
        filter_script = os.path.join(WORKSPACE_DIR, "scripts", "scrape_and_filter_candidates.py")
        p2 = run_step([sys.executable, filter_script], "scrape_and_filter_candidates")
        if p2.returncode != 0:
            push_supabase_jobs("after filter failure (partial)")
            state["status"] = "failed"
            err = (p2.stderr or p2.stdout or "").strip() or "Unknown error"
            state["message"] = f"Filter script failed: {err[:500]}"
            state["last_error"] = err[:4000]
            if tracker:
                tracker.fail(state["message"])
            return

        push_supabase_jobs("after filter")

        state["message"] = "Applying policy classification..."
        if tracker:
            tracker.update_stage("classifying")
        classify_script = os.path.join(WORKSPACE_DIR, "scripts", "classify_and_save.py")
        p3 = run_step([sys.executable, classify_script], "classify_and_save")
        if p3.returncode != 0:
            push_supabase_jobs("after classify failure (partial)")
            state["status"] = "failed"
            err = (p3.stderr or p3.stdout or "").strip() or "Unknown error"
            state["message"] = f"Classifier failed: {err[:500]}"
            state["last_error"] = err[:4000]
            if tracker:
                tracker.fail(state["message"])
            return

        push_supabase_jobs("after classify")

        metrics = {}
        sj = resolve_path(os.path.join(WORKSPACE_DIR, "scraped_jobs.json"), email)
        approved_path = resolve_path(APPROVED_PATH, email)
        active_path = resolve_path(ACTIVE_PATH, email)
        failed_path = resolve_path(FAILED_PATH, email)
        try:
            if os.path.exists(sj):
                with open(sj, encoding="utf-8") as f:
                    metrics["scraped_jobs_count"] = len(json.load(f))
        except Exception:
            pass
        try:
            if os.path.exists(approved_path):
                with open(approved_path, encoding="utf-8") as f:
                    metrics["approved_jobs_count"] = len(json.load(f))
        except Exception:
            pass
        try:
            if os.path.exists(active_path):
                with open(active_path, encoding="utf-8") as f:
                    metrics["active_candidates_count"] = len(json.load(f))
        except Exception:
            pass
        try:
            if os.path.exists(failed_path):
                with open(failed_path, encoding="utf-8") as f:
                    metrics["failed_candidates_count"] = len(json.load(f))
        except Exception:
            pass
        state["last_metrics"] = metrics

        # Load the newly approved jobs and auto-sync them if cron triggered
        # For auto runs, we sync them and send webhook notifications
        token = os.getenv("NOTION_TOKEN")
        db_id = os.getenv("NOTION_DATABASE_ID")
        if token and db_id and os.path.exists(approved_path):
            try:
                cfg = load_config(email)
                search_cfg = cfg.get("search") or {}
                send_digest_only = search_cfg.get("send_digest_only", True)
                
                with open(approved_path, 'r') as f:
                    app_jobs = json.load(f)
                synced_jobs = load_synced_jobs(email)
                
                newly_synced = []
                for job in app_jobs:
                    url = job.get("job_url")
                    if url and url not in synced_jobs:
                        # Auto sync
                        success, page_id, _ = sync_job_to_notion(job, token, db_id, email=email)
                        if success:
                            mark_job_synced(url, page_id, email)
                            newly_synced.append((job, page_id))
                            if not send_digest_only:
                                send_webhook_alert(job, page_id, email=email)
                                
                if send_digest_only and newly_synced:
                    send_daily_digest_alert(newly_synced, len(newly_synced))
            except Exception as e:
                print(f"Error auto-syncing approved jobs: {e}")
                
        # Identify newly scraped jobs by comparing scraped_at to start_time
        all_jobs = load_all_jobs(email)
        new_jobs = [j for j in all_jobs if j.get('scraped_at') and j['scraped_at'] >= start_time]
        state["new_jobs"] = new_jobs

        state["status"] = "completed"
        state["message"] = f"Job sourcing complete! {len(new_jobs)} new jobs found."
        state["last_run"] = datetime.utcnow().isoformat()
        if tracker:
            summary = {**metrics, "new_jobs_count": len(new_jobs), "message": state["message"]}
            tracker.complete(summary)
    except Exception as e:
        state["status"] = "failed"
        state["message"] = f"Scraper execution error: {str(e)}"
        state["last_error"] = str(e)[:4000]
        if tracker:
            tracker.fail(state["last_error"] or state["message"])


def company_scraper_worker(
    b64_payload,
    email,
    user_id,
    email_key,
    scrape_run_id=None,
    company_input=None,
):
    """Run company_scraper/main.py in a background thread (logs to logs/company_scraper.log)."""
    log_path = os.path.join(WORKSPACE_DIR, "logs", "company_scraper.log")
    started = datetime.utcnow()

    db_tracker = None
    if scrape_run_id and _valid_scrape_tracker_user_id(user_id):
        try:
            from scrape_tracker import ScrapeTracker

            db_tracker = ScrapeTracker(
                user_id,
                email or "",
                "company_targeted",
                input_value=company_input,
                existing_run_id=scrape_run_id,
            )
        except Exception:
            db_tracker = None

    def _finish_state(status: str, phase_key: str, summary=None, error=None):
        finished = datetime.utcnow()
        dur = (finished - started).total_seconds()
        with _company_scraper_states_lock:
            st = _company_scraper_states.setdefault(email_key, _default_company_scraper_state())
            st["status"] = status
            st["phase_key"] = phase_key
            st["phase"] = _company_scraper_phase_label(phase_key)
            st["finished_at"] = finished.isoformat() + "Z"
            st["duration_seconds"] = round(dur, 1)
            if summary is not None:
                st["summary"] = summary
            if error is not None:
                st["error"] = error

    try:
        os.makedirs(os.path.join(WORKSPACE_DIR, "logs"), exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as lf:
            lf.write(
                f"\n[{datetime.utcnow().isoformat()}] company_scrape START email={email!r} user_id={user_id!r} run_id={scrape_run_id!r}\n"
            )
        env = os.environ.copy()
        env["MAAS_USER_EMAIL"] = email or ""
        env["MAAS_USER_ID"] = user_id or ""
        script = os.path.join(WORKSPACE_DIR, "company_scraper", "main.py")
        cmd = [sys.executable, script, b64_payload]
        if scrape_run_id:
            cmd.extend(["--run-id", scrape_run_id])
        p = subprocess.Popen(
            cmd,
            cwd=WORKSPACE_DIR,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        stderr_buf = []

        def _drain_stderr():
            try:
                for line in iter(p.stderr.readline, ""):
                    stderr_buf.append(line)
                    line_st = line.rstrip()
                    if line_st.startswith(_COMPANY_SCRAPER_PROGRESS):
                        try:
                            prog = json.loads(line_st[len(_COMPANY_SCRAPER_PROGRESS) :])
                            pk = prog.get("phase")
                            if isinstance(pk, str):
                                with _company_scraper_states_lock:
                                    st = _company_scraper_states.get(email_key)
                                    if st and st.get("status") == "running":
                                        st["phase_key"] = pk
                                        st["phase"] = _company_scraper_phase_label(pk)
                        except Exception:
                            pass
            except Exception:
                pass

        t_err = threading.Thread(target=_drain_stderr, daemon=True)
        t_err.start()
        stdout_chunks = []
        try:
            for line in iter(p.stdout.readline, ""):
                stdout_chunks.append(line)
        finally:
            rc = p.wait()
        t_err.join(timeout=5)
        full_out = "".join(stdout_chunks)
        full_err = "".join(stderr_buf)
        with open(log_path, "a", encoding="utf-8") as lf:
            lf.write(full_out + "\n")
            lf.write(full_err + "\n")
            lf.write(f"[{datetime.utcnow().isoformat()}] company_scrape END rc={rc}\n")

        summary = None
        for line in reversed(full_out.strip().splitlines()):
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict) and "company" in obj:
                        summary = obj
                        break
                except Exception:
                    continue

        if rc != 0:
            err_msg = f"Process exited with code {rc}"
            _finish_state(
                "failed",
                "failed",
                summary=summary,
                error=err_msg,
            )
            if db_tracker:
                db_tracker.fail(err_msg)
        elif summary and int(summary.get("saved_to_db", 0) or 0) == 0 and (
            (summary.get("errors") and len(summary["errors"]) > 0)
            or int(summary.get("it_jobs_found", 0) or 0) > 0
        ):
            err_msg = "; ".join(summary.get("errors") or []) or "Could not save jobs to the database"
            _finish_state(
                "failed",
                "failed",
                summary=summary,
                error=err_msg,
            )
            if db_tracker:
                db_tracker.fail(err_msg)
        else:
            _finish_state("completed", "completed", summary=summary, error=None)
            if db_tracker:
                db_tracker.complete(summary or {})
    except Exception as e:
        try:
            with open(log_path, "a", encoding="utf-8") as lf:
                lf.write(f"[{datetime.utcnow().isoformat()}] company_scrape ERROR {e!r}\n")
        except Exception:
            pass
        err_s = str(e)[:2000]
        _finish_state("failed", "failed", summary=None, error=err_s)
        if db_tracker:
            db_tracker.fail(err_s)


# Background Scheduler Loop
def scheduler_loop():
    print("Background scheduler thread started (Supabase mode).")
    last_triggered_dates = {}
    
    while True:
        configs = []
        try:
            from supabase_client import get_supabase_client
            supabase = get_supabase_client()
            res = supabase.table("user_configs").select("user_id, scheduler_enabled, scheduler_run_at_hour, scheduler_run_at_minute").execute()
            configs = res.data or []
        except Exception as e:
            print(f"Error querying user configs in scheduler loop: {e}")
            
        for cfg in configs:
            user_id = cfg.get("user_id")
            if not user_id:
                continue
                
            email = None
            try:
                # Resolve user email from Auth using admin API
                user_info = supabase.auth.admin.get_user_by_id(user_id)
                if user_info and user_info.user:
                    email = user_info.user.email
            except Exception as e:
                pass
                
            if not email:
                email = "admin@hailmary.ai" # fallback scoped name
                
            enabled = cfg.get("scheduler_enabled", True)
            if enabled:
                now = datetime.now()
                today = date.today()
                
                target_hour = cfg.get("scheduler_run_at_hour", 8)
                target_minute = cfg.get("scheduler_run_at_minute", 0)
                
                last_triggered_date = last_triggered_dates.get(user_id)
                if now.hour == target_hour and now.minute == target_minute and last_triggered_date != today:
                    print(f"[{now.isoformat()}] Scheduled trigger for {email} ({user_id}): Starting daily job sourcing scraper...")
                    last_triggered_dates[user_id] = today
                    
                    state = get_scraper_state(email)
                    if state["status"] != "running":
                        threading.Thread(target=scraper_worker, args=(email, False, user_id)).start()
                        
        time.sleep(30)

# H1B Sponsor cache and name-matching helpers
_cached_sponsors_cleaned = None
_cached_sponsors_time = 0.0

def clean_company_name(name: str) -> str:
    if not name:
        return ""
    name = name.lower()
    import re
    # Remove common punctuation
    name = re.sub(r'[,.\-\(\)]', ' ', name)
    # Remove common corporate suffixes
    suffixes = [
        r'\binc\b', r'\bllc\b', r'\bcorp\b', r'\bcorporation\b', r'\bincorporated\b',
        r'\bltd\b', r'\blimited\b', r'\bco\b', r'\bsystems\b', r'\btechnologies\b',
        r'\bsolutions\b', r'\bsoftware\b', r'\btechnology\b', r'\bsystem\b', r'\bsolution\b',
        r'\bai\b', r'\bca\b', r'\bus\b', r'\busa\b'
    ]
    for suffix in suffixes:
        name = re.sub(suffix, '', name)
    # Collapse spaces
    name = re.sub(r'\s+', ' ', name).strip()
    return name

def get_h1b_sponsors_cleaned():
    global _cached_sponsors_cleaned, _cached_sponsors_time
    import time
    now = time.time()
    # Cache for 1 hour
    if _cached_sponsors_cleaned is not None and now - _cached_sponsors_time < 3600:
        return _cached_sponsors_cleaned
        
    try:
        from supabase_client import get_supabase_client
        supabase = get_supabase_client()
        sponsors = {}
        offset = 0
        limit = 1000
        while True:
            # Query all metadata fields to attach to jobs
            fields = (
                "company_name, company_type, w2_contractor, employee_count, "
                "linkedin_account, career_portal, website, sponsor_status, "
                "recommended_action, opt_friendly_score, cases_2024, cases_2025, "
                "cases_2026, recent_cases, recent_approvals, trend_label, top_state"
            )
            res = supabase.table("h1b_sponsors").select(fields).eq("is_sponsor", True).range(offset, offset + limit - 1).execute()
            if not res.data:
                break
            for row in res.data:
                name = row.get("company_name")
                if not name:
                    continue
                cleaned = clean_company_name(name)
                if cleaned:
                    sponsors[cleaned] = row
            if len(res.data) < limit:
                break
            offset += limit
            
        _cached_sponsors_cleaned = sponsors
        _cached_sponsors_time = now
        print(f"Loaded {len(sponsors)} cleaned H1B sponsors with metadata into cache.")
        return _cached_sponsors_cleaned
    except Exception as e:
        print(f"Failed to fetch and cache H1B sponsors: {e}")
        return _cached_sponsors_cleaned or {}

def is_sponsor_match(job_company: str, sponsors_cleaned: dict):
    job_comp_clean = clean_company_name(job_company)
    if not job_comp_clean or len(job_comp_clean) < 2:
        return None
        
    # 1. Exact cleaned match
    if job_comp_clean in sponsors_cleaned:
        return sponsors_cleaned[job_comp_clean]
        
    # 2. Part match for longer names
    for clean_sp, sponsor_data in sponsors_cleaned.items():
        if job_comp_clean == clean_sp:
            return sponsor_data
        if len(job_comp_clean) >= 4:
            if job_comp_clean.startswith(clean_sp) or clean_sp.startswith(job_comp_clean):
                return sponsor_data
            if job_comp_clean in clean_sp.split() or clean_sp in job_comp_clean.split():
                return sponsor_data
    return None

# HTTP Handler
class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, DELETE, PATCH")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Private-Network", "true")

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_cors_headers()
        self.end_headers()

    def get_auth_payload(self):
        auth_header = self.headers.get("Authorization")
        if not auth_header:
            return None
        parts = auth_header.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1]
            try:
                from supabase_client import verify_supabase_jwt
                payload = verify_supabase_jwt(token)
                if payload:
                    return payload
            except Exception as e:
                print(f"Supabase JWT decode exception: {e}")
            
            session = active_sessions.get(token)
            if isinstance(session, dict):
                return {
                    "sub": session.get("user_id", "00000000-0000-0000-0000-000000000000"),
                    "email": session.get("email"),
                    "role": session.get("role")
                }
        return None

    def get_auth_email(self):
        payload = self.get_auth_payload()
        if payload:
            email = payload.get("email")
            if not email:
                meta = payload.get("user_metadata")
                if isinstance(meta, dict):
                    email = meta.get("email")
            if email:
                return email
        return "admin@hailmary.ai"

    def get_auth_user_id(self):
        payload = self.get_auth_payload()
        if payload:
            return payload.get("sub")
        return "00000000-0000-0000-0000-000000000000"

    def get_auth_role(self):
        payload = self.get_auth_payload()
        if payload:
            role = payload.get("role")
            if role == "authenticated":
                email = payload.get("email")
                if not email:
                    meta = payload.get("user_metadata")
                    if isinstance(meta, dict):
                        email = meta.get("email")
                # Map admin user specifically or anyone authenticated to user role
                if email == "admin@hailmary.ai":
                    return "admin"
                return "user"
            return role
        return None

    def check_authenticated(self):
        role = self.get_auth_role()
        if role in ["admin", "user", "authenticated"]:
            return True
        
        # Return 401 Unauthorized
        self.send_response(401)
        self.send_header("Content-Type", "application/json")
        self.send_cors_headers()
        self.end_headers()
        res = {"success": False, "message": "Unauthorized. Please log in."}
        self.wfile.write(json.dumps(res).encode('utf-8'))
        return False

    def check_admin(self):
        role = self.get_auth_role()
        if role == "admin":
            return True
            
        # Return 403 Forbidden
        self.send_response(403)
        self.send_header("Content-Type", "application/json")
        self.send_cors_headers()
        self.end_headers()
        res = {"success": False, "message": "Forbidden. Admin access required."}
        self.wfile.write(json.dumps(res).encode('utf-8'))
        return False

    def do_GET(self):
        parsed_url = urllib.parse.urlparse(self.path)
        
        # Authenticate all API endpoints (excluding static page rendering and 404s)
        if parsed_url.path.startswith("/api/"):
            if parsed_url.path == "/api/health":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "workspace": WORKSPACE_DIR}).encode("utf-8"))
                return
            if parsed_url.path == "/api/health/playwright":
                body = {"status": "ok", "webkit": True}
                code = 200
                try:
                    from playwright.sync_api import sync_playwright

                    with sync_playwright() as p:
                        b = p.webkit.launch(headless=True)
                        b.close()
                except Exception as e:
                    body = {"status": "error", "webkit": False, "message": str(e)}
                    code = 503
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps(body).encode("utf-8"))
                return
            if parsed_url.path == "/api/config/default-target-titles":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(
                    json.dumps({"target_titles": list(jc.DEFAULT_TARGET_TITLES)}).encode("utf-8")
                )
                return
            if not self.check_authenticated():
                return
        
        # API: Get all jobs
        if parsed_url.path == "/api/jobs":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_cors_headers()
            self.end_headers()
            
            email = self.get_auth_email()
            uid = self.get_auth_user_id()
            jobs = load_all_jobs(email)
            
            # Fetch match scores from Supabase
            if uid:
                try:
                    from supabase_client import get_supabase_client
                    supabase = get_supabase_client()
                    user_cfg = supabase.table("user_configs").select("resume_embedding").eq("user_id", uid).maybe_single().execute()
                    if user_cfg.data and user_cfg.data.get("resume_embedding"):
                        res_emb = user_cfg.data["resume_embedding"]
                        match_res = supabase.rpc("match_jobs", {
                            "query_embedding": res_emb,
                            "match_threshold": 0.0,
                            "match_count": 5000,
                            "user_id_filter": uid
                        }).execute()
                        
                        if match_res.data:
                            match_dict = {row["job_url"]: row["similarity"] for row in match_res.data}
                            for job in jobs:
                                job_url = job.get("job_url")
                                if job_url in match_dict:
                                    job["match_score"] = round(match_dict[job_url] * 100, 1)
                except Exception as ex:
                    print(f"Failed to fetch match scores: {ex}")

                # Fetch H1B Sponsors and match
                try:
                    sponsors_cleaned = get_h1b_sponsors_cleaned()
                    if sponsors_cleaned:
                        for job in jobs:
                            company = job.get("company_name", "")
                            if company:
                                matched_sponsor = is_sponsor_match(company, sponsors_cleaned)
                                if matched_sponsor:
                                    job["visa_sponsor"] = True
                                    job["sponsor_metadata"] = matched_sponsor
                except Exception as ex:
                    print(f"Failed to fetch and match H1B sponsors: {ex}")
                    
            self.wfile.write(json.dumps(jobs).encode('utf-8'))
            return

        elif parsed_url.path == "/api/new-jobs":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_cors_headers()
            self.end_headers()

            email = self.get_auth_email()
            state = get_scraper_state(email)
            new_jobs = state.get("new_jobs", [])
            self.wfile.write(json.dumps(new_jobs).encode('utf-8'))
            return
            
        # API: Get settings config
        elif parsed_url.path == "/api/config":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_cors_headers()
            self.end_headers()
            
            email = self.get_auth_email()
            cfg = load_config(email)
            self.wfile.write(json.dumps(public_config_for_api(cfg)).encode('utf-8'))
            return

        # API: Get policy config
        elif parsed_url.path == "/api/policy":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_cors_headers()
            self.end_headers()
            
            email = self.get_auth_email()
            cfg = load_policy_config(email)
            self.wfile.write(json.dumps(cfg).encode('utf-8'))
            return

        # API: Get analytics metrics
        elif parsed_url.path == "/api/analytics":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_cors_headers()
            self.end_headers()
            
            email = self.get_auth_email()
            data = calculate_analytics(email)
            self.wfile.write(json.dumps(data).encode('utf-8'))
            return
            
        # API: Test Notion database connection
        elif parsed_url.path == "/api/test-notion":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_cors_headers()
            self.end_headers()
            
            token = os.getenv("NOTION_TOKEN")
            db_id = os.getenv("NOTION_DATABASE_ID")
            
            if not token or not db_id:
                res = {"success": False, "message": "NOTION_TOKEN or NOTION_DATABASE_ID missing in environment."}
            else:
                url = f"https://api.notion.com/v1/databases/{db_id}"
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Notion-Version": "2022-06-28"
                }
                try:
                    r = requests.get(url, headers=headers, timeout=10)
                    if r.status_code == 200:
                        res = {"success": True, "message": "Successfully connected to Notion!", "db_name": r.json().get("title", [{}])[0].get("plain_text", "MAAS Database")}
                    else:
                        res = {"success": False, "message": f"Connection failed (Status {r.status_code}): {r.text}"}
                except Exception as e:
                    res = {"success": False, "message": f"Network error: {str(e)}"}
            
            self.wfile.write(json.dumps(res).encode('utf-8'))
            return
            
        # API: Check scraper status
        elif parsed_url.path == "/api/scraper-status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_cors_headers()
            self.end_headers()
            email = self.get_auth_email()
            self.wfile.write(json.dumps(get_scraper_state(email)).encode('utf-8'))
            return

        elif parsed_url.path == "/api/scrape/company/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_cors_headers()
            self.end_headers()
            email = self.get_auth_email()
            self.wfile.write(json.dumps(get_company_scraper_state(email)).encode("utf-8"))
            return

        elif parsed_url.path == "/api/scrape/active":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_cors_headers()
            self.end_headers()
            uid = self.get_auth_user_id()
            self.wfile.write(
                json.dumps({"runs": _fetch_user_active_scrape_runs(uid)}).encode("utf-8")
            )
            return

        elif parsed_url.path.startswith("/api/scrape/status/"):
            rest = parsed_url.path[len("/api/scrape/status/") :].strip("/")
            uid = self.get_auth_user_id()
            row = _fetch_user_scrape_run(uid, rest) if rest else None
            code = 200 if row else 404
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_cors_headers()
            self.end_headers()
            if row:
                self.wfile.write(json.dumps({"run": row}).encode("utf-8"))
            else:
                self.wfile.write(
                    json.dumps({"success": False, "message": "Run not found or invalid id"}).encode(
                        "utf-8"
                    )
                )
            return

        elif parsed_url.path == "/api/scrape/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_cors_headers()
            self.end_headers()
            uid = self.get_auth_user_id()
            self.wfile.write(json.dumps({"runs": _fetch_user_scrape_runs(uid, 20)}).encode("utf-8"))
            return

        elif parsed_url.path == "/api/watched-companies":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_cors_headers()
            self.end_headers()
            uid = self.get_auth_user_id()
            try:
                from supabase_client import get_supabase_client

                if not _valid_scrape_tracker_user_id(uid):
                    self.wfile.write(json.dumps({"companies": []}).encode("utf-8"))
                    return
                r = (
                    get_supabase_client()
                    .table("watched_companies")
                    .select("*")
                    .eq("user_id", uid)
                    .eq("is_active", True)
                    .order("created_at", desc=True)
                    .execute()
                )
                self.wfile.write(json.dumps({"companies": r.data or []}).encode("utf-8"))
            except Exception as ex:
                print(f"GET /api/watched-companies error: {ex}")
                self.wfile.write(json.dumps({"companies": [], "error": str(ex)}).encode("utf-8"))
            return

        # API: Get stale check status
        elif parsed_url.path == "/api/stale-status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_cors_headers()
            self.end_headers()
            email = self.get_auth_email()
            self.wfile.write(json.dumps(get_stale_check_state(email)).encode('utf-8'))
            return

        # API: Get scraper console logs
        elif parsed_url.path == "/api/logs":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_cors_headers()
            self.end_headers()
            
            log_lines = []
            log_path = os.path.join(WORKSPACE_DIR, "logs", "scrape.log")
            if os.path.exists(log_path):
                try:
                    with open(log_path, 'r', encoding='utf-8') as f:
                        lines = f.readlines()
                        log_lines = lines[-100:]
                except Exception as e:
                    log_lines = [f"Error reading log file: {str(e)}"]
            else:
                log_lines = ["Log file logs/scrape.log not found. Scraper may not have logged a run yet."]
                
            self.wfile.write(json.dumps({"logs": log_lines}).encode('utf-8'))
            return

        # API: Get salary insights
        elif parsed_url.path == "/api/salary-insights":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_cors_headers()
            self.end_headers()
            
            email = self.get_auth_email()
            jobs = load_all_jobs(email)
            approved_jobs = [j for j in jobs if j.get('status') == 'approved' and not j.get('archived')]
            
            yearly_salaries = []
            hourly_salaries = []
            
            for j in approved_jobs:
                min_s = j.get('min_salary')
                max_s = j.get('max_salary')
                is_h = j.get('is_hourly')
                
                if min_s is not None and max_s is not None:
                    avg_s = (min_s + max_s) / 2.0
                    if is_h:
                        hourly_salaries.append(avg_s)
                    else:
                        yearly_salaries.append(avg_s)
            
            yearly_avg = sum(yearly_salaries) / len(yearly_salaries) if yearly_salaries else 0
            yearly_min = min(yearly_salaries) if yearly_salaries else 0
            yearly_max = max(yearly_salaries) if yearly_salaries else 0
            
            hourly_avg = sum(hourly_salaries) / len(hourly_salaries) if hourly_salaries else 0
            hourly_min = min(hourly_salaries) if hourly_salaries else 0
            hourly_max = max(hourly_salaries) if hourly_salaries else 0
            
            insights = {
                "yearly_count": len(yearly_salaries),
                "yearly_avg": yearly_avg,
                "yearly_min": yearly_min,
                "yearly_max": yearly_max,
                "hourly_count": len(hourly_salaries),
                "hourly_avg": hourly_avg,
                "hourly_min": hourly_min,
                "hourly_max": hourly_max,
                "yearly_distribution": yearly_salaries,
                "hourly_distribution": hourly_salaries
            }
            self.wfile.write(json.dumps(insights).encode('utf-8'))
            return

        # API: Get base resume
        elif parsed_url.path == "/api/resume":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_cors_headers()
            self.end_headers()
            
            email = self.get_auth_email()
            data_dir = os.path.join(WORKSPACE_DIR, "data")
            if not os.path.exists(data_dir):
                os.makedirs(data_dir, exist_ok=True)
            resume_path = resolve_path(os.path.join(data_dir, "base_resume.md"), email)
            
            content = ""
            if os.path.exists(resume_path):
                try:
                    with open(resume_path, "r", encoding="utf-8") as f:
                        content = f.read()
                except Exception as e:
                    content = f"Error reading resume: {str(e)}"
            else:
                # Default template if it doesn't exist
                content = (
                    "# Master Resume\n\n"
                    "**Name:** Your Name\n"
                    "**Email:** email@example.com | **LinkedIn:** linkedin.com/in/username\n\n"
                    "## Professional Summary\n"
                    "Experienced engineer specializing in cloud automation, SRE, and DevOps practices.\n\n"
                    "## Core Skills\n"
                    "- Python, Bash, Go\n"
                    "- AWS, GCP, Kubernetes, Terraform\n"
                    "- CI/CD, Git, Linux Administration\n\n"
                    "## Experience\n"
                    "### Senior Platform Engineer | Company Name (2022 - Present)\n"
                    "- Designed and implemented scalable CI/CD pipelines reducing deployment times by 40%.\n"
                    "- Configured Kubernetes clusters and automated infrastructure provisioning using Terraform.\n"
                    "- Established monitoring and alerting frameworks for high-availability cloud services.\n\n"
                    "### DevOps Engineer | Company Name (2020 - 2022)\n"
                    "- Automated configuration management and software provisioning using Ansible.\n"
                    "- Managed AWS cloud resources and optimized cost structure to save 15% annually.\n"
                )
                try:
                    with open(resume_path, "w", encoding="utf-8") as f:
                        f.write(content)
                except Exception:
                    pass
                    
            self.wfile.write(json.dumps({"resume": content}).encode('utf-8'))
            return

        # Serve Frontend index.html
        elif parsed_url.path == "/" or parsed_url.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            
            html_path = os.path.join(WORKSPACE_DIR, "index.html")
            if os.path.exists(html_path):
                with open(html_path, 'rb') as f:
                    self.wfile.write(f.read())
            else:
                self.wfile.write(b"<h1>Dashboard index.html not found!</h1>")
            return

        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")

    def do_POST(self):
        parsed_url = urllib.parse.urlparse(self.path)
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length).decode('utf-8')
        
        try:
            payload = json.loads(post_data) if post_data else {}
        except Exception:
            payload = {}

        # Protect API: login/register open; reset-target-titles + classifier-feedback need any auth; rest admin-only
        _user_authed_post_paths = (
            "/api/config/reset-target-titles",
            "/api/classifier-feedback",
            "/api/watched-companies",
            "/api/job/check-live",
        )
        if parsed_url.path.startswith("/api/"):
            if parsed_url.path in ["/api/login", "/api/register"]:
                pass
            elif parsed_url.path in _user_authed_post_paths:
                if not self.check_authenticated():
                    return
            else:
                if not self.check_admin():
                    return

        # API: Login
        if parsed_url.path == "/api/login":
            email = payload.get("email")
            password = payload.get("password")
            
            # Backward compatibility check
            if not email:
                if password == ADMIN_PASSWORD:
                    email = "admin@hailmary.ai"
                elif password == USER_PASSWORD:
                    email = "user@hailmary.ai"
                else:
                    email = "user@hailmary.ai"
            
            if not email or not password:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "message": "Missing email or password"}).encode('utf-8'))
                return
                
            user_session = verify_user_credentials(email, password)
            if user_session:
                token = str(uuid.uuid4())
                active_sessions[token] = user_session
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({
                    "success": True,
                    "token": token,
                    "role": user_session["role"],
                    "email": user_session["email"]
                }).encode('utf-8'))
            else:
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({
                    "success": False,
                    "message": "Invalid email or password"
                }).encode('utf-8'))
            return

        # API: Register
        elif parsed_url.path == "/api/register":
            email = payload.get("email")
            password = payload.get("password")
            if not email or not password:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "message": "Email and password are required"}).encode('utf-8'))
                return
                
            if "@" not in email or "." not in email:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "message": "Invalid email address format"}).encode('utf-8'))
                return
                
            role = "user"
            if "admin" in email.lower():
                role = "admin"
                
            success, msg = register_user(email, password, role)
            if success:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "message": msg}).encode('utf-8'))
            else:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "message": msg}).encode('utf-8'))
            return

        # API: Reset target job titles to repo defaults (local scoped config + optional Supabase)
        elif parsed_url.path == "/api/config/reset-target-titles":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_cors_headers()
            self.end_headers()
            email = self.get_auth_email()
            uid = self.get_auth_user_id()
            cfg = load_config(email)
            cfg["target_titles"] = list(jc.DEFAULT_TARGET_TITLES)
            ok = save_config(cfg, email)
            try:
                from supabase_client import update_user_target_titles

                update_user_target_titles(uid, list(jc.DEFAULT_TARGET_TITLES))
            except Exception as e:
                print(f"reset-target-titles: optional Supabase update skipped: {e}")
            self.wfile.write(
                json.dumps(
                    {
                        "success": bool(ok),
                        "target_titles": list(jc.DEFAULT_TARGET_TITLES),
                        "message": "Target titles reset to defaults."
                        if ok
                        else "Failed to save local config.",
                    }
                ).encode("utf-8")
            )
            return

        # API: Classifier feedback (append-only jsonl under logs/)
        elif parsed_url.path == "/api/classifier-feedback":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_cors_headers()
            self.end_headers()
            email = self.get_auth_email()
            rec = {"email": email, "payload": payload}
            try:
                log_dir = os.path.join(WORKSPACE_DIR, "logs")
                os.makedirs(log_dir, exist_ok=True)
                path = os.path.join(log_dir, "classifier_feedback.jsonl")
                with open(path, "a", encoding="utf-8") as f:
                    f.write(
                        json.dumps({"ts": datetime.utcnow().isoformat() + "Z", **rec}, default=str) + "\n"
                    )
            except Exception as e:
                self.wfile.write(json.dumps({"success": False, "message": str(e)}).encode("utf-8"))
                return
            self.wfile.write(json.dumps({"success": True}).encode("utf-8"))
            return

        # API: Save settings config
        if parsed_url.path == "/api/config":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_cors_headers()
            self.end_headers()
            
            email = self.get_auth_email()
            success = save_config(payload, email)
            self.wfile.write(json.dumps({"success": success, "message": "Settings saved successfully!" if success else "Failed to save settings."}).encode('utf-8'))
            return

        # API: Save policy config
        elif parsed_url.path == "/api/policy":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_cors_headers()
            self.end_headers()
            
            email = self.get_auth_email()
            success = save_policy_config(payload, email)
            if success:
                rebuild_success, msg = rebuild_classifier_prompt(payload)
                if rebuild_success:
                    self.wfile.write(json.dumps({"success": True, "message": "Policy saved and classifier prompt rebuilt successfully!"}).encode('utf-8'))
                else:
                    self.wfile.write(json.dumps({"success": False, "message": f"Policy saved, but prompt rebuild failed: {msg}"}).encode('utf-8'))
            else:
                self.wfile.write(json.dumps({"success": False, "message": "Failed to save policy configuration."}).encode('utf-8'))
            return

        # API: Test Webhook Connection
        elif parsed_url.path == "/api/test-webhook":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_cors_headers()
            self.end_headers()

            email = self.get_auth_email()
            cfg = load_config(email)
            test_url = (payload.get("webhook_url") or "").strip() or effective_webhook_url(cfg)
            if not test_url:
                self.wfile.write(json.dumps({"success": False, "message": "No Webhook URL provided (form or JOBSEARCH_WEBHOOK_URL / config)."}).encode('utf-8'))
                return

            try:
                if "discord.com" in test_url:
                    wh_payload = {
                        "embeds": [{
                            "title": "MAAS Job Agent Webhook Test",
                            "description": "Successful connection test.",
                            "color": 6512369,
                        }]
                    }
                else:
                    wh_payload = {"text": "🔔 **MAAS Job Agent Webhook Connection Test**: Successful alert! 🎉"}
                r = requests.post(test_url, json=wh_payload, timeout=10)
                success = r.status_code in [200, 204]
            except Exception as e:
                success = False
                err = str(e)
                self.wfile.write(json.dumps({"success": False, "message": f"Failed to dispatch webhook: {err}"}).encode('utf-8'))
                return

            if success:
                self.wfile.write(json.dumps({"success": True, "message": "Test alert sent successfully! Check your Slack/Discord channel."}).encode('utf-8'))
            else:
                self.wfile.write(json.dumps({"success": False, "message": "Failed to dispatch webhook alert. Double check your Webhook URL."}).encode('utf-8'))
            return

        # API: Override approval
        elif parsed_url.path == "/api/override":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_cors_headers()
            self.end_headers()
            
            email = self.get_auth_email()
            success, msg = override_job_on_disk(payload, email)
            self.wfile.write(json.dumps({"success": success, "message": msg}).encode('utf-8'))
            return

        # API: Update application pipeline stage
        elif parsed_url.path == "/api/update-pipeline-stage":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_cors_headers()
            self.end_headers()
            
            url = payload.get("job_url")
            new_stage = payload.get("pipeline_stage")
            if not url or not new_stage:
                self.wfile.write(json.dumps({"success": False, "message": "Missing job_url or pipeline_stage"}).encode('utf-8'))
                return
                
            email = self.get_auth_email()
            approved_path = resolve_path(APPROVED_PATH, email)
            active_path = resolve_path(ACTIVE_PATH, email)
            failed_path = resolve_path(FAILED_PATH, email)

            approved = []
            if os.path.exists(approved_path):
                try:
                    with open(approved_path, 'r') as f:
                        approved = json.load(f)
                except Exception:
                    pass
                    
            active = []
            if os.path.exists(active_path):
                try:
                    with open(active_path, 'r') as f:
                        active = json.load(f)
                except Exception:
                    pass
                    
            failed = []
            if os.path.exists(failed_path):
                try:
                    with open(failed_path, 'r') as f:
                        failed = json.load(f)
                except Exception:
                    pass
            
            # Find and update job
            target_job = None
            found_list = None
            
            for j in approved:
                if j.get("job_url") == url:
                    target_job = j
                    found_list = approved
                    break
            if not target_job:
                for j in active:
                    if j.get("job_url") == url:
                        target_job = j
                        found_list = active
                        break
            if not target_job:
                for j in failed:
                    if j.get("job_url") == url:
                        target_job = j
                        found_list = failed
                        break
            if not target_job:
                # Check SQLite database mirror
                from notion_sqlite_mirror import db_path, ensure_notion_mirror_schema
                try:
                    ensure_notion_mirror_schema(WORKSPACE_DIR)
                    db_file = db_path(WORKSPACE_DIR)
                    if os.path.exists(db_file):
                        import sqlite3
                        conn = sqlite3.connect(str(db_file))
                        conn.row_factory = sqlite3.Row
                        cursor = conn.cursor()
                        row = cursor.execute("SELECT * FROM notion_job_reports WHERE job_url = ? AND user_email = ?", (url, email or 'admin@hailmary.ai')).fetchone()
                        if row:
                            red_flags = []
                            if row['red_flags_json']:
                                try:
                                    red_flags = json.loads(row['red_flags_json'])
                                except Exception:
                                    pass
                            payload_data = {}
                            if row['apply_decision_payload_json']:
                                try:
                                    payload_data = json.loads(row['apply_decision_payload_json'])
                                except Exception:
                                    pass
                            
                            confidence = row['confidence_score']
                            if confidence is not None:
                                if confidence <= 1.0:
                                    confidence = confidence * 100.0
                            else:
                                confidence = 100.0

                            target_job = {
                                "job_title": row['job_title'] or "Unknown Title",
                                "company_name": row['company_name'] or "Unknown",
                                "job_url": url,
                                "requirement_id": row['requirement_id'] or "Unknown",
                                "job_description": row['job_description'] or "",
                                "location_work_type": row['location_work_type'] or "Remote",
                                "scraped_at": row['date_added'],
                                "red_flags": red_flags,
                                "apply_decision": row['apply_decision'] or "APPLY",
                                "strongest_label": row['strongest_label'] or "DevOps Engineer",
                                "confidence_score": confidence,
                                "rationale": row['rationale'] or "",
                                "apply_decision_payload": payload_data,
                                "benefits": payload_data.get("benefits", []),
                                "status": "approved",
                                "synced": True,
                                "synced_data": {
                                    "page_id": row['notion_page_id'],
                                    "synced_at": row['synced_at']
                                },
                                "source_file": "notion_job_reports.db",
                                "pipeline_stage": new_stage,
                                "min_salary": row['min_salary'],
                                "max_salary": row['max_salary'],
                                "is_hourly": bool(row['is_hourly']),
                                "salary_text": row['salary_text'],
                                "archived": bool(row['archived'])
                            }
                            # Update the stage in SQLite
                            conn.execute("UPDATE notion_job_reports SET pipeline_stage = ? WHERE job_url = ? AND user_email = ?", (new_stage, url, email or 'admin@hailmary.ai'))
                            conn.commit()
                        conn.close()
                except Exception as e:
                    print(f"Error checking/updating SQLite mirror in update-pipeline-stage: {e}")
                        
            if not target_job:
                self.wfile.write(json.dumps({"success": False, "message": "Job not found."}).encode('utf-8'))
                return
                
            target_job["pipeline_stage"] = new_stage
            
            # Save back to JSON lists
            try:
                with open(approved_path, 'w') as f:
                    json.dump(approved, f, indent=2)
                with open(active_path, 'w') as f:
                    json.dump(active, f, indent=2)
                with open(failed_path, 'w') as f:
                    json.dump(failed, f, indent=2)
            except Exception as e:
                self.wfile.write(json.dumps({"success": False, "message": f"Failed to save JSON updates: {str(e)}"}).encode('utf-8'))
                return
                
            # Update SQLite mirror if synced
            synced_jobs = load_synced_jobs(email)
            page_id = None
            db_id = os.getenv("NOTION_DATABASE_ID")
            
            if url in synced_jobs:
                page_id = synced_jobs[url].get("page_id")
                
            if page_id:
                try:
                    from notion_sqlite_mirror import upsert_notion_job_report
                    upsert_notion_job_report(target_job, page_id, db_id or "", user_email=email or 'admin@hailmary.ai')
                except Exception as e:
                    print(f"Warning: Failed to update SQLite mirror: {e}")
                    
                # Attempt to sync back to Notion
                token = os.getenv("NOTION_TOKEN")
                if token and page_id:
                    notion_url = f"https://api.notion.com/v1/pages/{page_id}"
                    headers = {
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                        "Notion-Version": "2022-06-28"
                    }
                    notion_payload = {
                        "properties": {
                            "Pipeline Stage": {
                                "select": {"name": new_stage}
                            }
                        }
                    }
                    try:
                        r = requests.patch(notion_url, headers=headers, json=notion_payload, timeout=8)
                        if r.status_code != 200:
                            notion_payload_fallback = {
                                "properties": {
                                    "Pipeline Stage": {
                                        "rich_text": [{"text": {"content": new_stage}}]
                                    }
                                }
                            }
                            requests.patch(notion_url, headers=headers, json=notion_payload_fallback, timeout=8)
                    except Exception:
                        pass
                        
            self.wfile.write(json.dumps({"success": True, "message": f"Pipeline stage updated to '{new_stage}'"}).encode('utf-8'))
            return
            
        # API: Sync job to Notion
        elif parsed_url.path == "/api/sync":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_cors_headers()
            self.end_headers()
            
            url = payload.get("job_url")
            if not url:
                self.wfile.write(json.dumps({"success": False, "message": "Missing job_url"}).encode('utf-8'))
                return
                
            email = self.get_auth_email()
            # Find the job
            all_jobs = load_all_jobs(email)
            target_job = None
            for j in all_jobs:
                if j.get("job_url") == url:
                    target_job = j
                    break
                    
            if not target_job:
                self.wfile.write(json.dumps({"success": False, "message": "Job not found."}).encode('utf-8'))
                return
                
            token = os.getenv("NOTION_TOKEN")
            db_id = os.getenv("NOTION_DATABASE_ID")
            
            if not token or not db_id:
                self.wfile.write(json.dumps({"success": False, "message": "Notion environment variables not configured in .env."}).encode('utf-8'))
                return
                
            success, page_id, error_msg = sync_job_to_notion(target_job, token, db_id, email)
            if success:
                mark_job_synced(url, page_id, email)
                # Dispatch Webhook alert!
                send_webhook_alert(target_job, page_id, email=email)
                self.wfile.write(json.dumps({"success": True, "message": "Successfully synced to Notion!", "page_id": page_id}).encode('utf-8'))
            else:
                self.wfile.write(json.dumps({"success": False, "message": f"Notion Sync failed: {error_msg}"}).encode('utf-8'))
            return

        # API: Trigger scraping run
        elif parsed_url.path == "/api/scrape":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_cors_headers()
            self.end_headers()
            
            email = self.get_auth_email()
            user_id = self.get_auth_user_id()
            state = get_scraper_state(email)
            if state["status"] == "running":
                res = {"success": False, "message": "Scraper is already running."}
            else:
                past_24h_only = payload.get("past_24h_only", False)
                scrape_run_id = None
                if _valid_scrape_tracker_user_id(user_id):
                    try:
                        from scrape_tracker import ScrapeTracker

                        tr = ScrapeTracker(user_id, email or "", "pipeline")
                        scrape_run_id = tr.start() or None
                    except Exception:
                        scrape_run_id = None
                threading.Thread(
                    target=lambda rid=scrape_run_id: scraper_worker(
                        email, past_24h_only, user_id=user_id, scrape_run_id=rid
                    )
                ).start()
                res = {
                    "success": True,
                    "message": "Scraper started in background.",
                    "run_id": scrape_run_id,
                }
                
            self.wfile.write(json.dumps(res).encode('utf-8'))
            return

        # API: Company-targeted scrape (Greenhouse / Lever / Workday / iCIMS / generic)
        elif parsed_url.path == "/api/scrape/company":
            email = self.get_auth_email()
            user_id = self.get_auth_user_id()
            email_key = (email or "").strip() or "admin@hailmary.ai"
            inp = (payload.get("input") or "").strip()
            if not inp:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(
                    json.dumps({"success": False, "message": "Missing JSON field: input"}).encode("utf-8")
                )
                return
            scrape_run_id = None
            if _valid_scrape_tracker_user_id(user_id):
                try:
                    from scrape_tracker import ScrapeTracker

                    comp_scrape_run = ScrapeTracker(user_id, email or "", "company_targeted", input_value=inp)
                    scrape_run_id = comp_scrape_run.start() or None
                except Exception:
                    scrape_run_id = None
            with _company_scraper_states_lock:
                st = _company_scraper_states.get(email_key)
                if st and st.get("status") == "running":
                    self.send_response(409)
                    self.send_header("Content-Type", "application/json")
                    self.send_cors_headers()
                    self.end_headers()
                    self.wfile.write(
                        json.dumps(
                            {"success": False, "message": "Company scrape is already running."}
                        ).encode("utf-8")
                    )
                    return
                base = _default_company_scraper_state()
                base.update(
                    {
                        "status": "running",
                        "phase": _company_scraper_phase_label("scraping"),
                        "phase_key": "scraping",
                        "started_at": datetime.utcnow().isoformat() + "Z",
                        "input": inp,
                    }
                )
                _company_scraper_states[email_key] = base

            self.send_response(202)
            self.send_header("Content-Type", "application/json")
            self.send_cors_headers()
            self.end_headers()

            b64 = base64.b64encode(
                json.dumps(
                    {
                        "input": inp,
                        "it_prefs": _resolved_company_scraper_it_prefs(
                            user_id, payload.get("it_prefs") if isinstance(payload.get("it_prefs"), dict) else {}
                        ),
                    }
                ).encode("utf-8")
            ).decode("ascii")
            threading.Thread(
                target=company_scraper_worker,
                args=(b64, email, user_id, email_key, scrape_run_id, inp),
            ).start()
            res = {
                "success": True,
                "accepted": True,
                "message": "Company scrape started in background. See logs/company_scraper.log for progress.",
                "run_id": scrape_run_id,
            }
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        elif parsed_url.path == "/api/watched-companies":
            uid = self.get_auth_user_id()
            email = self.get_auth_email()
            inp = (payload.get("input") or "").strip()
            if not inp:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(
                    json.dumps({"success": False, "message": "Missing JSON field: input"}).encode("utf-8")
                )
                return
            if not _valid_scrape_tracker_user_id(uid):
                self.send_response(403)
                self.send_header("Content-Type", "application/json")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(
                    json.dumps({"success": False, "message": "Supabase user id required."}).encode("utf-8")
                )
                return
            resolved, err = resolve_watched_company_input(inp)
            if not resolved:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "message": err or "Resolve failed"}).encode("utf-8"))
                return
            try:
                from supabase_client import get_supabase_client

                row = {
                    "user_id": uid,
                    "user_email": email or None,
                    **resolved,
                    "is_active": True,
                    "scrape_frequency": "daily",
                }
                ins = get_supabase_client().table("watched_companies").insert(row).execute()
                data = (ins.data or [None])[0] or {}
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(
                    json.dumps(
                        {
                            "id": data.get("id"),
                            "company_name": data.get("company_name"),
                            "careers_url": data.get("careers_url"),
                            "ats_platform": data.get("ats_platform"),
                        }
                    ).encode("utf-8")
                )
            except Exception as ex:
                print(f"POST /api/watched-companies error: {ex}")
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "message": str(ex)}).encode("utf-8"))
            return

        # API: Trigger stale job check
        elif parsed_url.path == "/api/check-stale":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_cors_headers()
            self.end_headers()
            
            email = self.get_auth_email()
            state = get_stale_check_state(email)
            if state["status"] == "running":
                res = {"success": False, "message": "Stale job check is already running."}
            else:
                threading.Thread(target=stale_check_worker, args=(email,)).start()
                res = {"success": True, "message": "Stale job check started in background."}
                
            self.wfile.write(json.dumps(res).encode('utf-8'))
            return

        # API: Per-job posting liveness / stale probe (optionally persist to disk + Supabase)
        elif parsed_url.path == "/api/job/check-live":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_cors_headers()
            self.end_headers()

            job_url = (payload.get("job_url") or "").strip()
            if not job_url:
                self.wfile.write(
                    json.dumps({"success": False, "message": "Missing job_url"}).encode("utf-8")
                )
                return

            email = self.get_auth_email()
            uid = self.get_auth_user_id()
            persist = bool(payload.get("persist", True))
            job_id = payload.get("job_id") or payload.get("id")

            try:
                from job_link_health import check_job_posting_live

                info = check_job_posting_live(job_url)
            except Exception as e:
                self.wfile.write(
                    json.dumps({"success": False, "message": str(e)}).encode("utf-8")
                )
                return

            stale = bool(info.get("stale"))
            uncertain = bool(info.get("uncertain"))
            body = {
                "success": True,
                "stale": stale,
                "uncertain": uncertain,
                "reason": info.get("reason"),
                "http_status": info.get("http_status"),
                "final_url": info.get("final_url"),
                "persisted_disk": False,
                "persisted_supabase": False,
            }
            notes = []

            if persist:
                ok_disk, msg_disk = persist_job_stale_flag(email, job_url, stale)
                body["persisted_disk"] = ok_disk
                if msg_disk:
                    notes.append(msg_disk)

                if _valid_scrape_tracker_user_id(uid):
                    try:
                        from supabase_client import get_supabase_client

                        sb = get_supabase_client()
                        req = sb.table("jobs").update({"stale": stale})
                        jid = str(job_id).strip() if job_id else ""
                        if jid:
                            req = req.eq("id", jid)
                        else:
                            req = req.eq("job_url", job_url)
                        req.eq("user_id", str(uid)).execute()
                        body["persisted_supabase"] = True
                    except Exception as ex:
                        body["persisted_supabase"] = False
                        notes.append(f"Supabase: {ex}")

            if notes:
                body["persist_notes"] = notes

            self.wfile.write(json.dumps(body).encode("utf-8"))
            return

        # API: Archive / delete job
        elif parsed_url.path == "/api/delete":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_cors_headers()
            self.end_headers()
            
            url = payload.get("job_url")
            if not url:
                self.wfile.write(json.dumps({"success": False, "message": "Missing job_url"}).encode('utf-8'))
                return
                
            email = self.get_auth_email()
            success, msg = archive_job_on_disk(url, email)
            self.wfile.write(json.dumps({"success": success, "message": msg}).encode('utf-8'))
            return

        # API: Sync all approved, unsynced jobs to Notion (batch sync)
        elif parsed_url.path == "/api/sync-notion":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_cors_headers()
            self.end_headers()
            
            email = self.get_auth_email()
            token = os.getenv("NOTION_TOKEN")
            db_id = os.getenv("NOTION_DATABASE_ID")
            if not token or not db_id:
                self.wfile.write(json.dumps({"success": False, "message": "Notion environment variables not configured in .env."}).encode('utf-8'))
                return
                
            all_jobs = load_all_jobs(email)
            unsynced_approved = [j for j in all_jobs if j.get("status") == "approved" and not j.get("synced")]
            
            if not unsynced_approved:
                self.wfile.write(json.dumps({"success": True, "message": "No new approved jobs to sync."}).encode('utf-8'))
                return
                
            synced_count = 0
            failed_count = 0
            last_err = ""
            
            for j in unsynced_approved:
                url = j.get("job_url")
                success, page_id, error_msg = sync_job_to_notion(j, token, db_id, email)
                if success:
                    mark_job_synced(url, page_id, email)
                    send_webhook_alert(j, page_id, email=email)
                    synced_count += 1
                else:
                    failed_count += 1
                    last_err = error_msg
                    
            msg = f"Successfully synced {synced_count} jobs."
            if failed_count > 0:
                msg += f" Failed to sync {failed_count} jobs. Last error: {last_err}"
            
            self.wfile.write(json.dumps({"success": synced_count > 0, "message": msg}).encode('utf-8'))
            return

        # API: Sync job statuses from Notion back to local SQLite/JSON databases (Two-Way Sync)
        elif parsed_url.path == "/api/sync-notion-status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_cors_headers()
            self.end_headers()
            
            token = os.getenv("NOTION_TOKEN")
            db_id = os.getenv("NOTION_DATABASE_ID")
            if not token or not db_id:
                self.wfile.write(json.dumps({"success": False, "message": "Notion environment variables not configured in .env."}).encode('utf-8'))
                return
                
            email = self.get_auth_email()
            synced_jobs = load_synced_jobs(email)
            if not synced_jobs:
                self.wfile.write(json.dumps({"success": True, "message": "No synced jobs to check."}).encode('utf-8'))
                return
                
            headers = {
                "Authorization": f"Bearer {token}",
                "Notion-Version": "2022-06-28"
            }
            
            updated_count = 0
            errors = 0
            
            approved_path = resolve_path(APPROVED_PATH, email)
            active_path = resolve_path(ACTIVE_PATH, email)

            approved = []
            if os.path.exists(approved_path):
                try:
                    with open(approved_path, 'r') as f:
                        approved = json.load(f)
                except Exception:
                    pass
            
            active = []
            if os.path.exists(active_path):
                try:
                    with open(active_path, 'r') as f:
                        active = json.load(f)
                except Exception:
                    pass
                    
            for url, sync_info in list(synced_jobs.items()):
                page_id = sync_info.get("page_id")
                if not page_id:
                    continue
                    
                page_url = f"https://api.notion.com/v1/pages/{page_id}"
                try:
                    r = requests.get(page_url, headers=headers, timeout=8)
                    if r.status_code == 200:
                        page_data = r.json()
                        props = page_data.get("properties", {}) or {}
                        
                        decision = None
                        decision_prop = props.get("Apply Decision") or {}
                        if "select" in decision_prop:
                            sel = decision_prop["select"]
                            decision = sel.get("name") if sel else None
                        elif "rich_text" in decision_prop:
                            rt = decision_prop["rich_text"]
                            decision = "".join([t.get("text", {}).get("content", "") for t in rt]).strip()
                            
                        if decision:
                            found = False
                            for job in approved:
                                if job.get("job_url") == url:
                                    if job.get("apply_decision") != decision:
                                        job["apply_decision"] = decision
                                        updated_count += 1
                                    found = True
                                    break
                            
                            if not found:
                                for job in active:
                                    if job.get("job_url") == url:
                                        if job.get("apply_decision") != decision:
                                            job["apply_decision"] = decision
                                            updated_count += 1
                                        found = True
                                        break
                                        
                            # Also update in the SQLite database mirror
                            from notion_sqlite_mirror import db_path, ensure_notion_mirror_schema
                            try:
                                ensure_notion_mirror_schema(WORKSPACE_DIR)
                                db_file = db_path(WORKSPACE_DIR)
                                if os.path.exists(db_file):
                                    import sqlite3
                                    conn = sqlite3.connect(str(db_file))
                                    cursor = conn.cursor()
                                    row = cursor.execute("SELECT apply_decision FROM notion_job_reports WHERE job_url = ? AND user_email = ?", (url, email or 'admin@hailmary.ai')).fetchone()
                                    if row:
                                        if row[0] != decision:
                                            conn.execute("UPDATE notion_job_reports SET apply_decision = ? WHERE job_url = ? AND user_email = ?", (decision, url, email or 'admin@hailmary.ai'))
                                            conn.commit()
                                            if not found:
                                                updated_count += 1
                                    conn.close()
                            except Exception as e:
                                print(f"Error updating SQLite mirror in two-way sync: {e}")
                                        
                except Exception as e:
                    errors += 1
                    
            if updated_count > 0:
                try:
                    with open(approved_path, 'w') as f:
                        json.dump(approved, f, indent=2)
                    with open(active_path, 'w') as f:
                        json.dump(active, f, indent=2)
                except Exception as e:
                    self.wfile.write(json.dumps({"success": False, "message": f"Failed to save synced states: {str(e)}"}).encode('utf-8'))
                    return
                    
            msg = f"Two-way sync complete. Updated {updated_count} job decisions."
            if errors > 0:
                msg += f" (Encountered {errors} network check warnings)."
            self.wfile.write(json.dumps({"success": True, "message": msg}).encode('utf-8'))
            return

        # API: Save base resume
        elif parsed_url.path == "/api/resume":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_cors_headers()
            self.end_headers()
            
            email = self.get_auth_email()
            resume_content = payload.get("resume", "")
            data_dir = os.path.join(WORKSPACE_DIR, "data")
            if not os.path.exists(data_dir):
                os.makedirs(data_dir, exist_ok=True)
            resume_path = resolve_path(os.path.join(data_dir, "base_resume.md"), email)
            
            try:
                with open(resume_path, "w", encoding="utf-8") as f:
                    f.write(resume_content)
                    
                # Generate embedding and save to Supabase
                try:
                    from embeddings import get_embedding
                    from supabase_client import get_supabase_client
                    emb = get_embedding(resume_content)
                    if emb:
                        supabase = get_supabase_client()
                        uid = self.get_auth_user_id()
                        if uid:
                            supabase.table("user_configs").update({"resume_embedding": emb}).eq("user_id", uid).execute()
                            print(f"Updated resume embedding for {email}")
                except Exception as ex:
                    print(f"Failed to update resume embedding: {ex}")
                    
                self.wfile.write(json.dumps({"success": True, "message": "Base resume saved successfully!"}).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({"success": False, "message": f"Failed to save resume: {str(e)}"}).encode('utf-8'))
            return

        # API: Generate tailored resume edits and cover letter using Gemini
        elif parsed_url.path == "/api/generate-tailoring":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_cors_headers()
            self.end_headers()
            
            job_url = payload.get("job_url", "")
            if not job_url:
                self.wfile.write(json.dumps({"success": False, "message": "Missing job_url in payload"}).encode('utf-8'))
                return
            
            # Simple local URL normalizer
            def _norm(u):
                if not u:
                    return ""
                try:
                    p = urllib.parse.urlparse(u)
                    nl = p.netloc.lower()
                    if nl.startswith("www."):
                        nl = nl[4:]
                    pth = p.path.rstrip('/')
                    return f"{nl}{pth}"
                except Exception:
                    return u
            
            email = self.get_auth_email()
            jobs = load_all_jobs(email)
            target_job = None
            norm_target = _norm(job_url)
            for j in jobs:
                if _norm(j.get("job_url", "")) == norm_target:
                    target_job = j
                    break
                    
            if not target_job:
                self.wfile.write(json.dumps({"success": False, "message": "Job posting not found in local database."}).encode('utf-8'))
                return
                
            resume_path = resolve_path(os.path.join(WORKSPACE_DIR, "data", "base_resume.md"), email)
            base_resume = ""
            if os.path.exists(resume_path):
                try:
                    with open(resume_path, "r", encoding="utf-8") as f:
                        base_resume = f.read()
                except Exception:
                    pass
                    
            if not base_resume:
                self.wfile.write(json.dumps({"success": False, "message": "Base resume is empty. Please set your base resume in the 'Base Resume' tab first."}).encode('utf-8'))
                return
                
            import google.generativeai as genai
            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                self.wfile.write(json.dumps({"success": False, "message": "GEMINI_API_KEY environment variable not set in .env."}).encode('utf-8'))
                return
                
            system_instruction = (
                "You are an expert technical resume writer and career coach specializing in SRE, DevOps, and Platform Engineering.\n"
                "Your task is to tailor a candidate's resume and draft a compelling cover letter for a specific job description.\n"
                "You must return a JSON response with the following keys:\n"
                "{\n"
                "  \"cover_letter\": \"<markdown formatted cover letter text, including placeholders or direct details matching the company>\",\n"
                "  \"resume_suggestions\": [\n"
                "    {\n"
                "      \"original_bullet\": \"<the exact bullet point from the base resume that you are proposing to change>\",\n"
                "      \"suggested_bullet\": \"<the rewritten, tailored version of that bullet point>\",\n"
                "      \"rationale\": \"<brief explanation of why this change fits the job description and what keywords/achievements it highlights>\"\n"
                "    }\n"
                "  ]\n"
                "}\n"
                "Guidelines:\n"
                "- Align the cover letter closely with the requirements, tone, and technologies mentioned in the job description.\n"
                "- The cover letter should be professional, concise (3-4 paragraphs), and formatted in Markdown.\n"
                "- Select 3-5 high-impact bullets from the base resume that correspond most directly to requirements in the job description, and rewrite them to highlight matching skills (e.g. AWS, Kubernetes, Terraform, CI/CD tools) and quantify results if possible.\n"
                "- Do not hallucinate credentials or experiences the candidate does not have in the base resume; only adapt existing statements to align terminology and context."
            )
            
            user_prompt = (
                f"=== JOB TITLE ===\n{target_job.get('job_title')}\n\n"
                f"=== COMPANY ===\n{target_job.get('company_name')}\n\n"
                f"=== JOB DESCRIPTION ===\n{target_job.get('job_description')}\n\n"
                f"=== BASE RESUME ===\n{base_resume}\n"
            )
            
            try:
                genai.configure(api_key=api_key)
                model = genai.GenerativeModel(
                    model_name="gemini-2.5-flash",
                    generation_config={"response_mime_type": "application/json"},
                    system_instruction=system_instruction
                )
                response = model.generate_content(user_prompt)
                result = json.loads(response.text)
                
                self.wfile.write(json.dumps({
                    "success": True,
                    "cover_letter": result.get("cover_letter", ""),
                    "resume_suggestions": result.get("resume_suggestions", [])
                }).encode('utf-8'))
            except Exception as e:
                self.wfile.write(json.dumps({"success": False, "message": f"Gemini API tailoring failed: {str(e)}"}).encode('utf-8'))
            return

        # API: Generate tailored resume with GPT-4o
        elif parsed_url.path == "/api/resume/generate":
            jd = payload.get("jd", "").strip()
            if not jd:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Missing 'jd' parameter in request body."}).encode('utf-8'))
                return

            result = generate_resume(jd)
            if "error" in result:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"error": result["error"]}).encode('utf-8'))
            else:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps(result).encode('utf-8'))
            return

        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")

    def do_DELETE(self):
        parsed_url = urllib.parse.urlparse(self.path)
        if parsed_url.path.startswith("/api/"):
            if parsed_url.path == "/api/health":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok"}).encode("utf-8"))
                return
            if not self.check_authenticated():
                return
        if not parsed_url.path.startswith("/api/watched-companies/"):
            self.send_response(404)
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(b"Not Found")
            return
        uid = self.get_auth_user_id()
        rest = parsed_url.path[len("/api/watched-companies/") :].strip("/")
        try:
            uuid.UUID(rest)
        except Exception:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps({"success": False, "message": "Invalid id"}).encode("utf-8"))
            return
        try:
            from supabase_client import get_supabase_client

            get_supabase_client().table("watched_companies").update({"is_active": False}).eq(
                "id", rest
            ).eq("user_id", uid).execute()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps({"success": True}).encode("utf-8"))
        except Exception as ex:
            print(f"DELETE /api/watched-companies error: {ex}")
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps({"success": False, "message": str(ex)}).encode("utf-8"))

    def do_PATCH(self):
        parsed_url = urllib.parse.urlparse(self.path)
        content_length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(content_length).decode("utf-8")
        try:
            payload = json.loads(raw) if raw else {}
        except Exception:
            payload = {}
        if parsed_url.path.startswith("/api/"):
            if parsed_url.path == "/api/health":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok"}).encode("utf-8"))
                return
            if not self.check_authenticated():
                return
        if not parsed_url.path.startswith("/api/watched-companies/"):
            self.send_response(404)
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(b"Not Found")
            return
        uid = self.get_auth_user_id()
        rest = parsed_url.path[len("/api/watched-companies/") :].strip("/")
        try:
            uuid.UUID(rest)
        except Exception:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps({"success": False, "message": "Invalid id"}).encode("utf-8"))
            return
        updates = {}
        if "scrape_frequency" in payload:
            f = str(payload.get("scrape_frequency") or "").lower()
            if f in ("daily", "weekly"):
                updates["scrape_frequency"] = f
        if "is_active" in payload:
            updates["is_active"] = bool(payload.get("is_active"))
        if not updates:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(
                json.dumps({"success": False, "message": "No valid fields to update"}).encode("utf-8")
            )
            return
        try:
            from supabase_client import get_supabase_client

            get_supabase_client().table("watched_companies").update(updates).eq("id", rest).eq(
                "user_id", uid
            ).execute()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps({"success": True}).encode("utf-8"))
        except Exception as ex:
            print(f"PATCH /api/watched-companies error: {ex}")
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps({"success": False, "message": str(ex)}).encode("utf-8"))


def main():
    try:
        ensure_notion_mirror_schema(WORKSPACE_DIR)
    except Exception as e:
        print(f"Notion SQLite mirror init warning: {e}")

    # Start background scheduler thread
    sched_thread = threading.Thread(target=scheduler_loop, daemon=True)
    sched_thread.start()

    watched_thread = threading.Thread(target=watched_companies_scheduler_loop, daemon=True)
    watched_thread.start()
    
    server = ThreadingHTTPServer(('0.0.0.0', PORT), DashboardHandler)
    print(f"MAAS Job Sourcing Agent Dashboard running at: http://localhost:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping dashboard server...")
        server.server_close()

if __name__ == '__main__':
    main()
