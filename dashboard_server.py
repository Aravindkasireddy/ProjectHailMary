import os
import sys
import json
import re
import urllib.parse
import subprocess
import threading
import time
from datetime import datetime, date
from http.server import BaseHTTPRequestHandler, HTTPServer
from dotenv import load_dotenv
import requests

from jobsearch_paths import workspace_root
from jobsearch_webhook import effective_webhook_url, public_config_for_api
from notion_sqlite_mirror import upsert_notion_job_report, ensure_notion_mirror_schema

# Load env variables from repo root
WORKSPACE_DIR = str(workspace_root())
load_dotenv(dotenv_path=os.path.join(WORKSPACE_DIR, ".env"))

# HTTP API + dashboard backend (default 8080). Override if port is busy:
#   JOBSEARCH_DASHBOARD_PORT=8081 python3 dashboard_server.py
PORT = int(os.environ.get("JOBSEARCH_DASHBOARD_PORT", "8080"))
CONFIG_PATH = os.path.join(WORKSPACE_DIR, "config.json")
POLICY_CONFIG_PATH = os.path.join(WORKSPACE_DIR, "policy_config.json")
APPROVED_PATH = os.path.join(WORKSPACE_DIR, "approved_jobs.json")
FAILED_PATH = os.path.join(WORKSPACE_DIR, "failed_candidate_jobs.json")
ACTIVE_PATH = os.path.join(WORKSPACE_DIR, "active_candidate_jobs.json")
SYNCED_PATH = os.path.join(WORKSPACE_DIR, "synced_jobs.json")

# Global scraper status
scraper_state = {
    "status": "idle",
    "message": "Scraper is ready.",
    "last_run": None,
    "last_error": None,
    "last_metrics": {},
}

# Global stale check status
stale_check_state = {
    "status": "idle",
    "progress": 0,
    "total": 0,
    "completed": 0,
    "stale_found": 0,
}

def check_url_stale(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }
    try:
        r = requests.get(url, headers=headers, timeout=5, allow_redirects=True)
        if r.status_code == 404:
            return True
            
        final_url = r.url.lower()
        parsed_final = urllib.parse.urlparse(final_url)
        path = parsed_final.path
        
        if "greenhouse.io" in parsed_final.netloc:
            if "error=true" in final_url or "/jobs/" not in path:
                return True
        elif "lever.co" in parsed_final.netloc:
            path_parts = [p for p in path.split('/') if p]
            if len(path_parts) < 2:
                return True
            if "jobs at" in r.text.lower() or "current openings" in r.text.lower():
                return True
        elif "ashbyhq.com" in parsed_final.netloc:
            path_parts = [p for p in path.split('/') if p]
            if len(path_parts) <= 1:
                return True
                
        text_lower = r.text.lower()
        closed_keywords = [
            "this job is no longer available",
            "posting has closed",
            "job is closed",
            "no longer accepting applications",
            "position has been filled",
            "job posting was not found"
        ]
        if any(kw in text_lower for kw in closed_keywords):
            return True
    except Exception:
        pass
    return False

def stale_check_worker():
    global stale_check_state
    stale_check_state["status"] = "running"
    stale_check_state["progress"] = 0
    stale_check_state["total"] = 0
    stale_check_state["completed"] = 0
    stale_check_state["stale_found"] = 0
    
    try:
        if not os.path.exists(APPROVED_PATH):
            stale_check_state["status"] = "idle"
            return
            
        with open(APPROVED_PATH, 'r') as f:
            approved_jobs = json.load(f)
            
        stale_check_state["total"] = len(approved_jobs)
        if not approved_jobs:
            stale_check_state["status"] = "idle"
            return
            
        updated_jobs = []
        for idx, job in enumerate(approved_jobs):
            url = job.get("job_url")
            is_stale = False
            if url:
                is_stale = check_url_stale(url)
            
            if is_stale:
                job["stale"] = True
                stale_check_state["stale_found"] += 1
            else:
                job["stale"] = False
                
            updated_jobs.append(job)
            stale_check_state["completed"] = idx + 1
            stale_check_state["progress"] = int((idx + 1) / len(approved_jobs) * 100)
            time.sleep(1)
            
        with open(APPROVED_PATH, 'w') as f:
            json.dump(updated_jobs, f, indent=2)
            
    except Exception as e:
        print(f"Error in stale check worker: {e}")
    finally:
        stale_check_state["status"] = "idle"

def archive_job_on_disk(url):
    if not url:
        return False, "Missing job_url"
        
    approved = []
    if os.path.exists(APPROVED_PATH):
        try:
            with open(APPROVED_PATH, 'r') as f:
                approved = json.load(f)
        except Exception:
            pass
            
    failed = []
    if os.path.exists(FAILED_PATH):
        try:
            with open(FAILED_PATH, 'r') as f:
                failed = json.load(f)
        except Exception:
            pass
            
    active = []
    if os.path.exists(ACTIVE_PATH):
        try:
            with open(ACTIVE_PATH, 'r') as f:
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
        with open(APPROVED_PATH, 'w') as f:
            json.dump(approved, f, indent=2)
        with open(FAILED_PATH, 'w') as f:
            json.dump(failed, f, indent=2)
        with open(ACTIVE_PATH, 'w') as f:
            json.dump(active, f, indent=2)
        return True, "Job successfully archived."
    except Exception as e:
        return False, f"Failed to save changes: {str(e)}"

def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading config.json: {e}")
    # Default config
    return {
        "target_titles": [
            "DevOps Engineer",
            "Cloud Automation Engineer",
            "Platform Engineer",
            "Cloud Infrastructure Engineer",
            "Cloud Security Engineer",
            "DevSecOps",
            "Site Reliability Engineer",
            "CI/CD Engineer",
            "Systems Engineer",
            "Cloud Network Engineer",
            "Data Platform Engineer",
            "Machine Learning Engineer",
            "AI Platform Engineer"
        ],
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

def save_config(cfg):
    try:
        cfg = dict(cfg)
        if os.environ.get("JOBSEARCH_WEBHOOK_URL", "").strip():
            cfg.pop("webhook_url", None)
        with open(CONFIG_PATH, 'w') as f:
            json.dump(cfg, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving config.json: {e}")
        return False

def load_policy_config():
    if os.path.exists(POLICY_CONFIG_PATH):
        try:
            with open(POLICY_CONFIG_PATH, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading policy_config.json: {e}")
    return {
        "max_experience_years": 8,
        "min_salary_annual": 80000,
        "min_salary_hourly": 50,
        "enforce_visa_sponsorship": True,
        "enforce_no_clearance": True,
        "custom_red_flag_keywords": []
    }

def save_policy_config(cfg):
    try:
        with open(POLICY_CONFIG_PATH, 'w') as f:
            json.dump(cfg, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving policy_config.json: {e}")
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

def load_synced_jobs():
    if os.path.exists(SYNCED_PATH):
        try:
            with open(SYNCED_PATH, 'r') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def mark_job_synced(url, page_id):
    synced = load_synced_jobs()
    synced[url] = {
        "page_id": page_id,
        "synced_at": datetime.utcnow().isoformat()
    }
    try:
        with open(SYNCED_PATH, 'w') as f:
            json.dump(synced, f, indent=2)
    except Exception as e:
        print(f"Error saving synced jobs: {e}")

def load_all_jobs():
    jobs = []
    approved_urls = set()
    synced_jobs = load_synced_jobs()
    
    # Import salary extractor helper
    try:
        from salary_extractor import extract_salary
    except ImportError:
        extract_salary = None
    
    # Load approved jobs
    if os.path.exists(APPROVED_PATH):
        try:
            with open(APPROVED_PATH, 'r') as f:
                app_jobs = json.load(f)
                for j in app_jobs:
                    url = j.get('job_url')
                    j['status'] = 'approved'
                    j['synced'] = url in synced_jobs
                    j['synced_data'] = synced_jobs.get(url)
                    j['source_file'] = 'approved_jobs.json'
                    
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
    if os.path.exists(ACTIVE_PATH):
        try:
            with open(ACTIVE_PATH, 'r') as f:
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
    if os.path.exists(FAILED_PATH):
        try:
            with open(FAILED_PATH, 'r') as f:
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

    return jobs

def calculate_analytics():
    jobs = load_all_jobs()
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

def override_job_on_disk(updated_job):
    url = updated_job.get("job_url")
    if not url:
        return False, "Missing job_url"
        
    approved = []
    if os.path.exists(APPROVED_PATH):
        try:
            with open(APPROVED_PATH, 'r') as f:
                approved = json.load(f)
        except Exception:
            pass
            
    failed = []
    if os.path.exists(FAILED_PATH):
        try:
            with open(FAILED_PATH, 'r') as f:
                failed = json.load(f)
        except Exception:
            pass
            
    active = []
    if os.path.exists(ACTIVE_PATH):
        try:
            with open(ACTIVE_PATH, 'r') as f:
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
        with open(APPROVED_PATH, 'w') as f:
            json.dump(approved, f, indent=2)
        with open(FAILED_PATH, 'w') as f:
            json.dump(failed, f, indent=2)
        with open(ACTIVE_PATH, 'w') as f:
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

def build_notion_properties(job):
    # Ensure correct confidence score formatting for percentage field (95% -> 0.95)
    score = float(job.get("confidence_score", 0))
    if score > 1.0:
        score = score / 100.0
        
    props = {
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
        "Apply Decision": {
            "select": {"name": job.get("apply_decision", "APPLY")}
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
        props["Pipeline Stage"] = {
            "select": {"name": job.get("pipeline_stage")}
        }
    if job.get("salary_text"):
        props["Salary Range"] = {
            "rich_text": [{"text": {"content": job.get("salary_text")}}]
        }

    # Format Red Flags
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


def _mirror_notion_row_to_sqlite(job, page_id, database_id, was_duplicate):
    try:
        upsert_notion_job_report(
            job,
            page_id,
            database_id,
            was_duplicate=was_duplicate,
            workspace=WORKSPACE_DIR,
        )
    except Exception as e:
        print(f"SQLite Notion mirror warning: {e}")


def sync_job_to_notion(job, token, database_id):
    # Check duplicate first
    exists, page_id = check_job_exists_in_notion(job, token, database_id)
    if exists:
        _mirror_notion_row_to_sqlite(job, page_id, database_id, was_duplicate=True)
        return True, page_id, None

    url = "https://api.notion.com/v1/pages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }
    
    properties = build_notion_properties(job)
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
        _mirror_notion_row_to_sqlite(job, page_id, database_id, was_duplicate=False)
        return True, page_id, None
    else:
        # Fallback formatting
        print(f"Notion sync warning: {response.text}. Retrying with text fallback...")
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
            _mirror_notion_row_to_sqlite(job, page_id, database_id, was_duplicate=False)
            return True, page_id, None
        else:
            return False, None, response.text

# Webhook Notification Dispatcher
def send_webhook_alert(job, page_id, custom_msg=None):
    cfg = load_config()
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
def scraper_worker():
    global scraper_state
    scraper_state["status"] = "running"
    scraper_state["message"] = "Starting search query sourcing..."
    scraper_state["last_error"] = None
    scraper_state["last_metrics"] = {}

    def run_step(cmd, label):
        _append_pipeline_log(f"START {label}: {' '.join(cmd)}")
        p = subprocess.run(cmd, capture_output=True, text=True, cwd=WORKSPACE_DIR)
        tail_out = (p.stdout or "")[-12000:]
        tail_err = (p.stderr or "")[-8000:]
        _append_pipeline_log(f"END {label} rc={p.returncode}\n--- stdout ---\n{tail_out}\n--- stderr ---\n{tail_err}")
        return p

    try:
        p1 = run_step([sys.executable, "find_and_scrape_jobs.py"], "find_and_scrape_jobs")
        if p1.returncode != 0:
            scraper_state["status"] = "failed"
            err = (p1.stderr or p1.stdout or "").strip() or "Unknown error"
            scraper_state["message"] = f"Sourcing script failed: {err[:500]}"
            scraper_state["last_error"] = err[:4000]
            return

        scraper_state["message"] = "Running validation and filtering..."
        filter_script = os.path.join(WORKSPACE_DIR, "scripts", "scrape_and_filter_candidates.py")
        p2 = run_step([sys.executable, filter_script], "scrape_and_filter_candidates")
        if p2.returncode != 0:
            scraper_state["status"] = "failed"
            err = (p2.stderr or p2.stdout or "").strip() or "Unknown error"
            scraper_state["message"] = f"Filter script failed: {err[:500]}"
            scraper_state["last_error"] = err[:4000]
            return

        scraper_state["message"] = "Applying policy classification..."
        classify_script = os.path.join(WORKSPACE_DIR, "scripts", "classify_and_save.py")
        p3 = run_step([sys.executable, classify_script], "classify_and_save")
        if p3.returncode != 0:
            scraper_state["status"] = "failed"
            err = (p3.stderr or p3.stdout or "").strip() or "Unknown error"
            scraper_state["message"] = f"Classifier failed: {err[:500]}"
            scraper_state["last_error"] = err[:4000]
            return

        metrics = {}
        try:
            sj = os.path.join(WORKSPACE_DIR, "scraped_jobs.json")
            if os.path.exists(sj):
                with open(sj, encoding="utf-8") as f:
                    metrics["scraped_jobs_count"] = len(json.load(f))
        except Exception:
            pass
        try:
            if os.path.exists(APPROVED_PATH):
                with open(APPROVED_PATH, encoding="utf-8") as f:
                    metrics["approved_jobs_count"] = len(json.load(f))
        except Exception:
            pass
        try:
            if os.path.exists(ACTIVE_PATH):
                with open(ACTIVE_PATH, encoding="utf-8") as f:
                    metrics["active_candidates_count"] = len(json.load(f))
        except Exception:
            pass
        try:
            if os.path.exists(FAILED_PATH):
                with open(FAILED_PATH, encoding="utf-8") as f:
                    metrics["failed_candidates_count"] = len(json.load(f))
        except Exception:
            pass
        scraper_state["last_metrics"] = metrics

        # Load the newly approved jobs and auto-sync them if cron triggered
        # For auto runs, we sync them and send webhook notifications
        token = os.getenv("NOTION_TOKEN")
        db_id = os.getenv("NOTION_DATABASE_ID")
        if token and db_id and os.path.exists(APPROVED_PATH):
            try:
                cfg = load_config()
                search_cfg = cfg.get("search") or {}
                send_digest_only = search_cfg.get("send_digest_only", True)
                
                with open(APPROVED_PATH, 'r') as f:
                    app_jobs = json.load(f)
                synced_jobs = load_synced_jobs()
                
                newly_synced = []
                for job in app_jobs:
                    url = job.get("job_url")
                    if url and url not in synced_jobs:
                        # Auto sync
                        success, page_id, _ = sync_job_to_notion(job, token, db_id)
                        if success:
                            mark_job_synced(url, page_id)
                            newly_synced.append((job, page_id))
                            if not send_digest_only:
                                send_webhook_alert(job, page_id)
                                
                if send_digest_only and newly_synced:
                    send_daily_digest_alert(newly_synced, len(newly_synced))
            except Exception as e:
                print(f"Error auto-syncing approved jobs: {e}")
                
        scraper_state["status"] = "completed"
        scraper_state["message"] = "Job sourcing and validation complete!"
        scraper_state["last_run"] = datetime.utcnow().isoformat()
    except Exception as e:
        scraper_state["status"] = "failed"
        scraper_state["message"] = f"Scraper execution error: {str(e)}"
        scraper_state["last_error"] = str(e)[:4000]

# Background Scheduler Loop
def scheduler_loop():
    print("Background scheduler thread started.")
    last_triggered_date = None
    
    while True:
        cfg = load_config()
        sched_cfg = cfg.get("scheduler", {})
        
        if sched_cfg.get("enabled", False):
            now = datetime.now()
            today = date.today()
            
            target_hour = sched_cfg.get("run_at_hour", 8)
            target_minute = sched_cfg.get("run_at_minute", 0)
            
            # Check if it matches target hour and minute, and hasn't run today yet
            if now.hour == target_hour and now.minute == target_minute and last_triggered_date != today:
                print(f"[{now.isoformat()}] Scheduled trigger: Starting daily job sourcing scraper...")
                last_triggered_date = today
                
                # Trigger scraper run if not already running
                global scraper_state
                if scraper_state["status"] != "running":
                    threading.Thread(target=scraper_worker).start()
                    
        # Sleep for 30 seconds before checking again
        time.sleep(30)

# HTTP Handler
class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_cors_headers()
        self.end_headers()

    def do_GET(self):
        parsed_url = urllib.parse.urlparse(self.path)
        
        # API: Get all jobs
        if parsed_url.path == "/api/jobs":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_cors_headers()
            self.end_headers()
            
            jobs = load_all_jobs()
            self.wfile.write(json.dumps(jobs).encode('utf-8'))
            return
            
        # API: Get settings config
        elif parsed_url.path == "/api/config":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_cors_headers()
            self.end_headers()
            
            cfg = load_config()
            self.wfile.write(json.dumps(public_config_for_api(cfg)).encode('utf-8'))
            return

        # API: Get policy config
        elif parsed_url.path == "/api/policy":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_cors_headers()
            self.end_headers()
            
            cfg = load_policy_config()
            self.wfile.write(json.dumps(cfg).encode('utf-8'))
            return

        # API: Get analytics metrics
        elif parsed_url.path == "/api/analytics":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_cors_headers()
            self.end_headers()
            
            data = calculate_analytics()
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
            self.wfile.write(json.dumps(scraper_state).encode('utf-8'))
            return

        # API: Get stale check status
        elif parsed_url.path == "/api/stale-status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps(stale_check_state).encode('utf-8'))
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
            
            jobs = load_all_jobs()
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
            
            data_dir = os.path.join(WORKSPACE_DIR, "data")
            if not os.path.exists(data_dir):
                os.makedirs(data_dir, exist_ok=True)
            resume_path = os.path.join(data_dir, "base_resume.md")
            
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

        # API: Save settings config
        if parsed_url.path == "/api/config":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_cors_headers()
            self.end_headers()
            
            success = save_config(payload)
            self.wfile.write(json.dumps({"success": success, "message": "Settings saved successfully!" if success else "Failed to save settings."}).encode('utf-8'))
            return

        # API: Save policy config
        elif parsed_url.path == "/api/policy":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_cors_headers()
            self.end_headers()
            
            success = save_policy_config(payload)
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

            cfg = load_config()
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
            
            success, msg = override_job_on_disk(payload)
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
                
            approved = []
            if os.path.exists(APPROVED_PATH):
                try:
                    with open(APPROVED_PATH, 'r') as f:
                        approved = json.load(f)
                except Exception:
                    pass
                    
            active = []
            if os.path.exists(ACTIVE_PATH):
                try:
                    with open(ACTIVE_PATH, 'r') as f:
                        active = json.load(f)
                except Exception:
                    pass
                    
            failed = []
            if os.path.exists(FAILED_PATH):
                try:
                    with open(FAILED_PATH, 'r') as f:
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
                with open(APPROVED_PATH, 'w') as f:
                    json.dump(approved, f, indent=2)
                with open(ACTIVE_PATH, 'w') as f:
                    json.dump(active, f, indent=2)
                with open(FAILED_PATH, 'w') as f:
                    json.dump(failed, f, indent=2)
            except Exception as e:
                self.wfile.write(json.dumps({"success": False, "message": f"Failed to save JSON updates: {str(e)}"}).encode('utf-8'))
                return
                
            # Update SQLite mirror if synced
            synced_jobs = load_synced_jobs()
            page_id = None
            db_id = os.getenv("NOTION_DATABASE_ID")
            
            if url in synced_jobs:
                page_id = synced_jobs[url].get("page_id")
                
            if page_id:
                try:
                    from notion_sqlite_mirror import upsert_notion_job_report
                    upsert_notion_job_report(target_job, page_id, db_id or "")
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
                
            # Find the job
            all_jobs = load_all_jobs()
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
                
            success, page_id, error_msg = sync_job_to_notion(target_job, token, db_id)
            if success:
                mark_job_synced(url, page_id)
                # Dispatch Webhook alert!
                send_webhook_alert(target_job, page_id)
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
            
            global scraper_state
            if scraper_state["status"] == "running":
                res = {"success": False, "message": "Scraper is already running."}
            else:
                threading.Thread(target=scraper_worker).start()
                res = {"success": True, "message": "Scraper started in background."}
                
            self.wfile.write(json.dumps(res).encode('utf-8'))
            return

        # API: Trigger stale job check
        elif parsed_url.path == "/api/check-stale":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_cors_headers()
            self.end_headers()
            
            global stale_check_state
            if stale_check_state["status"] == "running":
                res = {"success": False, "message": "Stale job check is already running."}
            else:
                threading.Thread(target=stale_check_worker).start()
                res = {"success": True, "message": "Stale job check started in background."}
                
            self.wfile.write(json.dumps(res).encode('utf-8'))
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
                
            success, msg = archive_job_on_disk(url)
            self.wfile.write(json.dumps({"success": success, "message": msg}).encode('utf-8'))
            return

        # API: Sync all approved, unsynced jobs to Notion (batch sync)
        elif parsed_url.path == "/api/sync-notion":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_cors_headers()
            self.end_headers()
            
            token = os.getenv("NOTION_TOKEN")
            db_id = os.getenv("NOTION_DATABASE_ID")
            if not token or not db_id:
                self.wfile.write(json.dumps({"success": False, "message": "Notion environment variables not configured in .env."}).encode('utf-8'))
                return
                
            all_jobs = load_all_jobs()
            unsynced_approved = [j for j in all_jobs if j.get("status") == "approved" and not j.get("synced")]
            
            if not unsynced_approved:
                self.wfile.write(json.dumps({"success": True, "message": "No new approved jobs to sync."}).encode('utf-8'))
                return
                
            synced_count = 0
            failed_count = 0
            last_err = ""
            
            for j in unsynced_approved:
                url = j.get("job_url")
                success, page_id, error_msg = sync_job_to_notion(j, token, db_id)
                if success:
                    mark_job_synced(url, page_id)
                    send_webhook_alert(j, page_id)
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
                
            synced_jobs = load_synced_jobs()
            if not synced_jobs:
                self.wfile.write(json.dumps({"success": True, "message": "No synced jobs to check."}).encode('utf-8'))
                return
                
            headers = {
                "Authorization": f"Bearer {token}",
                "Notion-Version": "2022-06-28"
            }
            
            updated_count = 0
            errors = 0
            
            approved = []
            if os.path.exists(APPROVED_PATH):
                try:
                    with open(APPROVED_PATH, 'r') as f:
                        approved = json.load(f)
                except Exception:
                    pass
            
            active = []
            if os.path.exists(ACTIVE_PATH):
                try:
                    with open(ACTIVE_PATH, 'r') as f:
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
                                        
                except Exception as e:
                    errors += 1
                    
            if updated_count > 0:
                try:
                    with open(APPROVED_PATH, 'w') as f:
                        json.dump(approved, f, indent=2)
                    with open(ACTIVE_PATH, 'w') as f:
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
            
            resume_content = payload.get("resume", "")
            data_dir = os.path.join(WORKSPACE_DIR, "data")
            if not os.path.exists(data_dir):
                os.makedirs(data_dir, exist_ok=True)
            resume_path = os.path.join(data_dir, "base_resume.md")
            
            try:
                with open(resume_path, "w", encoding="utf-8") as f:
                    f.write(resume_content)
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
            
            jobs = load_all_jobs()
            target_job = None
            norm_target = _norm(job_url)
            for j in jobs:
                if _norm(j.get("job_url", "")) == norm_target:
                    target_job = j
                    break
                    
            if not target_job:
                self.wfile.write(json.dumps({"success": False, "message": "Job posting not found in local database."}).encode('utf-8'))
                return
                
            resume_path = os.path.join(WORKSPACE_DIR, "data", "base_resume.md")
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

        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")

def main():
    try:
        ensure_notion_mirror_schema(WORKSPACE_DIR)
    except Exception as e:
        print(f"Notion SQLite mirror init warning: {e}")

    # Start background scheduler thread
    sched_thread = threading.Thread(target=scheduler_loop, daemon=True)
    sched_thread.start()
    
    server = HTTPServer(('0.0.0.0', PORT), DashboardHandler)
    print(f"MAAS Job Sourcing Agent Dashboard running at: http://localhost:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping dashboard server...")
        server.server_close()

if __name__ == '__main__':
    main()
