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

# User-scoped scraper status store
scraper_states = {}
# Stale-check status store + helpers moved to stale_checker.py; import the
# same dict object here so it remains the single source of truth.
from stale_checker import stale_check_states  # noqa: E402

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

from stale_checker import get_stale_check_state  # noqa: E402


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


# Watched-company resolution and scheduler helpers moved to watched_companies_scheduler.py
from watched_companies_scheduler import (  # noqa: E402,F401
    _watched_scrape_inflight,
    _watched_scrape_inflight_lock,
    _watched_hint_from_url,
    resolve_watched_company_input,
    _watched_parse_last_scraped_ts,
    _parse_company_stdout_json_summary,
    _resolved_company_scraper_it_prefs,
    _watched_company_scrape_thread,
    watched_companies_scheduler_loop,
)


# Stale-job checking helpers moved to stale_checker.py
from stale_checker import check_url_stale, persist_job_stale_flag, stale_check_worker  # noqa: E402,F401

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

# Config/policy persistence helpers (moved to dashboard_config_store.py)
from dashboard_config_store import (  # noqa: E402,F401
    load_config,
    save_config,
    load_policy_config,
    save_policy_config,
    rebuild_classifier_prompt,
)

_cached_jobs_data = {}
_cached_jobs_mtimes = {}

def load_all_jobs(email=None):
    global _cached_jobs_data, _cached_jobs_mtimes

    email_key = email or "admin@hailmary.ai"

    approved_path = resolve_path(APPROVED_PATH, email)
    active_path = resolve_path(ACTIVE_PATH, email)
    failed_path = resolve_path(FAILED_PATH, email)

    paths_to_track = {
        "approved": approved_path,
        "active": active_path,
        "failed": failed_path,
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

    # Import salary extractor helper
    try:
        from salary_extractor import extract_salary
    except ImportError:
        extract_salary = None

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
        "System Engineer", "Cloud Network Engineer"
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

# Webhook Notification Dispatcher
def send_webhook_alert(job, custom_msg=None, email=None):
    cfg = load_config(email)
    webhook_url = effective_webhook_url(cfg)
    if not webhook_url:
        return False

    try:
        if custom_msg:
            payload = {"text": custom_msg}
        else:
            # Styled markdown notification (Slack/Discord compatible)
            payload = {
                "text": f"🎉 **New Approved Job!**\n"
                        f"🏢 **Company**: {job.get('company_name')}\n"
                        f"💼 **Title**: {job.get('job_title')}\n"
                        f"🏷️ **Role**: {job.get('strongest_label')}\n"
                        f"📍 **Location**: {job.get('location_work_type', 'Remote')}\n"
                        f"🆔 **Req ID**: {job.get('requirement_id', 'Unknown')}\n"
                        f"🔗 **Apply**: [Career Site]({job.get('job_url')})\n"
                        f"📝 **Rationale**: {job.get('rationale', 'No rationale provided.')}"
            }

            # If it's a Discord webhook, we can optionally format as embeds
            if "discord.com" in webhook_url:
                payload = {
                    "embeds": [{
                        "title": "🎉 New Approved Job!",
                        "color": 6512369, # Indigo
                        "fields": [
                            {"name": "Company", "value": job.get('company_name', 'Unknown'), "inline": True},
                            {"name": "Title", "value": job.get('job_title', 'Unknown'), "inline": True},
                            {"name": "Role Type", "value": job.get('strongest_label', 'Unknown'), "inline": True},
                            {"name": "Req ID", "value": job.get('requirement_id', 'Unknown'), "inline": True},
                            {"name": "Location", "value": job.get('location_work_type', 'Remote'), "inline": True},
                        ],
                        "description": f"**Rationale**: {job.get('rationale', 'No rationale')}\n\n[Apply Directly on Career Site]({job.get('job_url')})"
                    }]
                }

        r = requests.post(webhook_url, json=payload, timeout=10)
        return r.status_code in [200, 204]
    except Exception as e:
        print(f"Error sending webhook notification: {e}")
        return False

def send_daily_digest_alert(new_jobs, total_new_count):
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
            for job in new_jobs[:max_items]:
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
                             f"🔗 [Apply on Career Site]({job.get('job_url')})\n"
                             f"📝 **Rationale**: {job.get('rationale', 'No rationale provided.')[:150]}..."
                })

            overflow = total_new_count - len(fields)
            desc = f"Found **{total_new_count}** new approved jobs in this sourcing run!"
            if overflow > 0:
                desc += f"\n*(Showing top {max_items} jobs. {overflow} more found)*"

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
            lines = [f"💼 **MAAS Job Sourcing Run Digest**", f"Found *{total_new_count}* new approved jobs!"]
            for job in new_jobs[:max_items]:
                lines.append(f"• *{job.get('job_title')}* at *{job.get('company_name')}* ({job.get('location_work_type', 'Remote')}) - <{job.get('job_url')}|Apply>")
            overflow = total_new_count - len(new_jobs[:max_items])
            if overflow > 0:
                lines.append(f"_...and {overflow} more new jobs._")
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

        # Identify newly scraped jobs by comparing scraped_at to start_time
        all_jobs = load_all_jobs(email)
        new_jobs = [j for j in all_jobs if j.get('scraped_at') and j['scraped_at'] >= start_time]
        state["new_jobs"] = new_jobs

        # Webhook notification for newly approved jobs found in this run
        try:
            cfg = load_config(email)
            search_cfg = cfg.get("search") or {}
            send_digest_only = search_cfg.get("send_digest_only", True)

            newly_approved = [j for j in new_jobs if j.get("status") == "approved"]
            if newly_approved:
                if send_digest_only:
                    send_daily_digest_alert(newly_approved, len(newly_approved))
                else:
                    for job in newly_approved:
                        send_webhook_alert(job, email=email)
        except Exception as e:
            print(f"Error sending webhook notification for new jobs: {e}")

        state["status"] = "completed"
        state["message"] = f"Job sourcing complete! {len(new_jobs)} new jobs found."
        state["last_run"] = datetime.utcnow().isoformat()
        if tracker:
            summary = {**metrics, "new_jobs_count": len(new_jobs), "message": state["message"]}
            tracker.complete(summary)

        # Auto-run staleness checking after every scrape (was previously
        # manual-trigger only via a UI button that, confirmed live, nobody had
        # ever clicked - 0 of 2777 Supabase rows had ever been flagged stale).
        # Fire-and-forget in its own thread so it doesn't delay this run's
        # "complete" status; reuses the same per-email staleness state/lock
        # the manual /api/check-stale button uses, so they won't double-run.
        try:
            stale_state = get_stale_check_state(email)
            if stale_state["status"] != "running":
                threading.Thread(target=stale_check_worker, args=(email, user_id)).start()
        except Exception as e:
            print(f"Failed to auto-start stale check after scrape: {e}")
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

# H1B Sponsor cache and name-matching helpers (moved to h1b_sponsors.py)
from h1b_sponsors import clean_company_name, get_h1b_sponsors_cleaned, is_sponsor_match  # noqa: E402,F401

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
            
        # API: Check scraper status
        elif parsed_url.path == "/api/scraper-status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_cors_headers()
            self.end_headers()
            email = self.get_auth_email()
            self.wfile.write(json.dumps(get_scraper_state(email)).encode('utf-8'))
            return

        elif parsed_url.path == "/api/apify-usage":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_cors_headers()
            self.end_headers()
            from company_scraper.scrapers import apify_client

            self.wfile.write(json.dumps(apify_client.get_usage_summary()).encode("utf-8"))
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
            if parsed_url.path in _user_authed_post_paths:
                if not self.check_authenticated():
                    return
            else:
                if not self.check_admin():
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

            self.wfile.write(json.dumps({"success": True, "message": f"Pipeline stage updated to '{new_stage}'"}).encode('utf-8'))
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
            uid = self.get_auth_user_id()
            state = get_stale_check_state(email)
            if state["status"] == "running":
                res = {"success": False, "message": "Stale job check is already running."}
            else:
                threading.Thread(target=stale_check_worker, args=(email, uid)).start()
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
