import json
import os
import sys
import time
import hashlib
from pathlib import Path
from dotenv import load_dotenv
import google.generativeai as genai

def compute_description_hash(description):
    if not description:
        return ""
    normalized = "".join(description.lower().split())
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()

def load_known_hashes(workspace_path):
    approved_hashes = {}
    failed_hashes = {}
    
    approved_path = resolve_path(workspace_path / "approved_jobs.json")
    if approved_path.exists():
        try:
            jobs = json.loads(approved_path.read_text(encoding="utf-8"))
            for j in jobs:
                h = j.get("description_hash")
                if not h and j.get("job_description"):
                    h = compute_description_hash(j["job_description"])
                if h:
                    approved_hashes[h] = j
        except Exception as e:
            print(f"Error loading approved hashes: {e}")
            
    failed_path = resolve_path(workspace_path / "failed_candidate_jobs.json")
    if failed_path.exists():
        try:
            jobs = json.loads(failed_path.read_text(encoding="utf-8"))
            for j in jobs:
                h = j.get("description_hash")
                if not h and j.get("job_description"):
                    h = compute_description_hash(j["job_description"])
                if h:
                    failed_hashes[h] = j
        except Exception as e:
            print(f"Error loading failed hashes: {e}")
            
    return approved_hashes, failed_hashes


_scripts_dir = Path(__file__).resolve().parent
_repo_root = _scripts_dir.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))
from jobsearch_paths import workspace_root
from benefits_extractor import extract_benefits
from jobsearch_constants import ALLOWED_STRONGEST_LABELS
from secrets_scrub import scrub_job_payload_for_storage

WORKSPACE = workspace_root()

def resolve_path(base_path):
    email = os.environ.get("MAAS_USER_EMAIL")
    if not email:
        return base_path
    import re
    suffix = re.sub(r'[^a-zA-Z0-9_.-]', '_', email)
    p = Path(base_path)
    return p.parent / f"{p.stem}_{suffix}{p.suffix}"

load_dotenv(dotenv_path=str(WORKSPACE / ".env"))

import threading

gemini_keys_lock = threading.Lock()
current_key_index = 0

def get_gemini_api_keys():
    keys = []
    gkey = os.getenv("GEMINI_API_KEY")
    if gkey:
        for k in gkey.split(","):
            k_stripped = k.strip()
            if k_stripped and k_stripped not in keys:
                keys.append(k_stripped)
    idx = 1
    while True:
        key_i = os.getenv(f"GEMINI_API_KEY_{idx}")
        if key_i:
            key_i = key_i.strip()
            if key_i and key_i not in keys:
                keys.append(key_i)
            idx += 1
        else:
            break
    return keys

def get_active_gemini_key():
    global current_key_index
    keys = get_gemini_api_keys()
    if not keys:
        return None
    with gemini_keys_lock:
        if current_key_index >= len(keys):
            return None
        return keys[current_key_index]

def rotate_gemini_key(failed_key=None):
    global current_key_index
    keys = get_gemini_api_keys()
    if not keys:
        return False
    with gemini_keys_lock:
        if failed_key and current_key_index < len(keys) and keys[current_key_index] != failed_key:
            return True # already rotated
        current_key_index += 1
        if current_key_index < len(keys):
            print(f"Rotating to Gemini API Key #{current_key_index + 1}...", flush=True)
            return True
        else:
            print("All Gemini API keys in the pool have been exhausted.", flush=True)
            return False

def classify_job_with_gemini(job):
    # Read systemic prompt / policy from Job_classifier_prompt.txt
    prompt_path = str(WORKSPACE / "Job_classifier_prompt.txt")
    system_instruction = ""
    if os.path.exists(prompt_path):
        try:
            with open(prompt_path, 'r') as f:
                system_instruction = f.read()
        except Exception as e:
            print(f"Error reading Job_classifier_prompt.txt: {e}")
            
    if not system_instruction:
        print("Systemic prompt file not found! Falling back to rule-based classification.")
        return None

    # Load API key and build user prompt
    title = job.get("job_title", "Unknown Title")
    description = job.get("job_description", "")
    
    user_prompt = f"""
Analyze this job posting:
Title: {title}
Description:
{description}

Return a JSON object conforming exactly to the following structure (see system instruction for PASS/HUMAN_REVIEW/REJECT rules):
{{
  "all_labels": ["<same as strongest_label first, optional 2nd/3rd labels>"],
  "strongest_label": "DevOps Engineer" | "Cloud Automation Engineer" | "Platform Engineering" | "Cloud Infrastructure Engineer" | "DevSecOps" | "Site Reliability Engineer (SRE)" | "Continuous Integration (CI/CD)" | "System Engineer" | "OutOfScope",
  "other_labels": [],
  "recommendation": "PASS" | "HUMAN_REVIEW" | "REJECT",
  "confidence_score": 0-100,
  "fit_score": 0-100,
  "ownership_strength": "LOW" | "MEDIUM" | "HIGH",
  "review_reason": "short string or empty string",
  "red_flags": [],
  "cloud": {{
    "is_cloud_role": true,
    "primary_cloud": "AWS" | "Azure" | "GCP" | "",
    "cloud_providers": ["AWS", "Azure", "GCP"]
  }},
  "domain_scores": {{
    "devops": 0-10,
    "automation": 0-10,
    "platform": 0-10,
    "infrastructure": 0-10,
    "security": 0-10,
    "devsecops": 0-10,
    "sre": 0-10,
    "cicd": 0-10,
    "system": 0-10,
    "network": 0-10,
    "database": 0-10,
    "cloud_database": 0-10
  }},
  "dominant_domains": [],
  "decision_trace": {{
    "top_score": 0,
    "runner_up_score": 0,
    "tie_break_applied": false,
    "priority_rule_used": "",
    "strong_signal_override": false
  }},
  "rationale": "",
  "rationale_formatted": [],
  "filters": {{ "domain_specialization": false }},
  "benefits": []
}}
"""
    
    try:
        result = None
        while True:
            active_key = get_active_gemini_key()
            if not active_key:
                break
                
            try:
                genai.configure(api_key=active_key)
                model = genai.GenerativeModel(
                    model_name="gemini-2.5-flash",
                    generation_config={"response_mime_type": "application/json"},
                    system_instruction=system_instruction
                )
                last_err = None
                for attempt in range(1, 4):
                    try:
                        response = model.generate_content(user_prompt)
                        result = json.loads(response.text)
                        break
                    except Exception as e:
                        last_err = e
                        err_msg = str(e).lower()
                        if any(term in err_msg for term in ["429", "400", "403", "quota", "limit", "exhausted", "invalid", "blocked", "denied", "resourceexhausted"]):
                            if rotate_gemini_key(active_key):
                                print(f"  Gemini key {active_key[:8]}... hit failure/quota. Rotating...", flush=True)
                                last_err = "rotated"
                                break
                            # No other key to rotate to (e.g. a single-key setup, confirmed
                            # live 2026-06-23 - production only has one GEMINI_API_KEY). A
                            # 429/quota hit here is frequently a transient per-minute rate
                            # limit rather than a hard daily exhaustion, so back off and
                            # retry the SAME key instead of giving up on this job's Gemini
                            # classification immediately (which previously skipped straight
                            # to keyword-only fallback on every single rate-limit hit).
                            if attempt < 3:
                                print(f"  Gemini key {active_key[:8]}... rate-limited with no other key available. Backing off and retrying same key (attempt {attempt}/3)...", flush=True)
                                time.sleep(2.0 * (2 ** (attempt - 1)))
                                continue
                            break
                        if attempt < 3:
                            time.sleep(0.6 * (2 ** (attempt - 1)))
                
                if last_err == "rotated":
                    continue
                    
                if result is None:
                    raise last_err if last_err and not isinstance(last_err, str) else RuntimeError("empty Gemini response")
                
                break
            except Exception as e:
                err_msg = str(e).lower()
                if any(term in err_msg for term in ["429", "400", "403", "quota", "limit", "exhausted", "invalid", "blocked", "denied", "resourceexhausted"]):
                    print(f"  Gemini key {active_key[:8]}... error during configure. Rotating...", flush=True)
                    if rotate_gemini_key(active_key):
                        continue
                raise e

        if result is None:
            return None

        allowed_label_set = set(ALLOWED_STRONGEST_LABELS)
        domain_keys = (
            "devops", "automation", "platform", "infrastructure", "security", "devsecops",
            "sre", "cicd", "system", "network", "database", "cloud_database",
        )

        strongest_label = result.get("strongest_label", "OutOfScope")
        if strongest_label not in allowed_label_set:
            strongest_label = "OutOfScope"

        red_flags = result.get("red_flags", [])
        if not isinstance(red_flags, list):
            red_flags = []
        red_flags = [str(x) for x in red_flags if x]

        recommendation = str(result.get("recommendation", "REJECT")).strip().upper()
        if recommendation not in ("PASS", "HUMAN_REVIEW", "REJECT"):
            recommendation = "REJECT"

        try:
            confidence = int(result.get("confidence_score", 0))
        except (TypeError, ValueError):
            confidence = 0
        confidence = max(0, min(100, confidence))

        try:
            fit_score = int(result.get("fit_score", 0))
        except (TypeError, ValueError):
            fit_score = 0
        fit_score = max(0, min(100, fit_score))

        ownership_strength = str(result.get("ownership_strength", "LOW")).strip().upper()
        if ownership_strength not in ("LOW", "MEDIUM", "HIGH"):
            ownership_strength = "LOW"

        review_reason = str(result.get("review_reason", "") or "").strip()

        domain_scores = result.get("domain_scores", {})
        if not isinstance(domain_scores, dict):
            domain_scores = {}
        for k in domain_keys:
            domain_scores.setdefault(k, 0)
            try:
                domain_scores[k] = max(0, min(10, int(domain_scores[k])))
            except (TypeError, ValueError):
                domain_scores[k] = 0

        all_labels = result.get("all_labels")
        if not isinstance(all_labels, list) or not all_labels:
            all_labels = [strongest_label]
        else:
            all_labels = [str(x) for x in all_labels if x]
            if not all_labels or all_labels[0] != strongest_label:
                all_labels = [strongest_label] + [x for x in all_labels if x != strongest_label]

        other_labels = result.get("other_labels", [])
        if not isinstance(other_labels, list):
            other_labels = []
        other_labels = [str(x) for x in other_labels if x and x != strongest_label]

        cloud = result.get("cloud", {})
        if not isinstance(cloud, dict):
            cloud = {}
        primary_cloud = str(cloud.get("primary_cloud", "") or "")
        if primary_cloud not in ("AWS", "Azure", "GCP", ""):
            primary_cloud = ""
        cloud_providers = cloud.get("cloud_providers", [])
        if not isinstance(cloud_providers, list):
            cloud_providers = []
        cloud_providers = [str(p) for p in cloud_providers if p in ("AWS", "Azure", "GCP")]
        is_cloud = bool(cloud.get("is_cloud_role")) if "is_cloud_role" in cloud else (
            len(cloud_providers) > 0 or primary_cloud != ""
        )
        cloud = {
            "is_cloud_role": bool(is_cloud),
            "primary_cloud": primary_cloud,
            "cloud_providers": cloud_providers,
        }

        decision_trace = result.get("decision_trace", {})
        if not isinstance(decision_trace, dict):
            decision_trace = {}
        numeric_scores = [domain_scores[k] for k in domain_keys if k in domain_scores]
        sorted_scores = sorted(numeric_scores, reverse=True) if numeric_scores else [0, 0]
        top_score = int(decision_trace.get("top_score", sorted_scores[0]))
        runner_up = int(decision_trace.get("runner_up_score", sorted_scores[1] if len(sorted_scores) > 1 else 0))
        decision_trace = {
            "top_score": top_score,
            "runner_up_score": runner_up,
            "tie_break_applied": bool(decision_trace.get("tie_break_applied", False)),
            "priority_rule_used": str(decision_trace.get("priority_rule_used", "") or ""),
            "strong_signal_override": bool(decision_trace.get("strong_signal_override", False)),
        }

        dominant_domains = result.get("dominant_domains", [])
        if not isinstance(dominant_domains, list) or not dominant_domains:
            dominant_domains = [strongest_label] if strongest_label != "OutOfScope" else []

        filters = result.get("filters", {"domain_specialization": False})
        if not isinstance(filters, dict):
            filters = {"domain_specialization": False}
        filters.setdefault("domain_specialization", False)

        benefits = result.get("benefits", [])
        if not benefits or not isinstance(benefits, list):
            benefits = extract_benefits(description)

        rationale = str(result.get("rationale", "") or "")
        rationale_formatted = result.get("rationale_formatted", [])
        if not isinstance(rationale_formatted, list):
            rationale_formatted = []

        pass_labels = allowed_label_set - {"OutOfScope"}

        # Enforce consistency with STEP 8 (safety net)
        if strongest_label == "OutOfScope" or red_flags:
            recommendation = "REJECT"
        elif recommendation == "PASS":
            if confidence < 70 or fit_score < 70:
                recommendation = "REJECT"
                review_reason = (review_reason + "; " if review_reason else "") + "PASS thresholds not met (confidence/fit)."
            elif strongest_label not in pass_labels:
                recommendation = "REJECT"
                review_reason = (review_reason + "; " if review_reason else "") + "Invalid label for PASS."

        if recommendation == "PASS" and ownership_strength == "MEDIUM":
            recommendation = "HUMAN_REVIEW"
            review_reason = (review_reason + "; " if review_reason else "") + "MEDIUM ownership requires human review."

        if recommendation == "HUMAN_REVIEW" and red_flags:
            recommendation = "REJECT"

        apply_decision = (
            "APPLY"
            if recommendation == "PASS" and not red_flags and strongest_label in pass_labels
            else "DO_NOT_APPLY"
        )

        payload = {
            "all_labels": all_labels,
            "strongest_label": strongest_label,
            "other_labels": other_labels,
            "recommendation": recommendation,
            "fit_score": fit_score,
            "ownership_strength": ownership_strength,
            "review_reason": review_reason,
            "apply_decision": apply_decision,
            "red_flags": red_flags,
            "filters": filters,
            "confidence_score": confidence,
            "cloud": cloud,
            "domain_scores": domain_scores,
            "dominant_domains": dominant_domains,
            "dominant_signals": {},
            "decision_trace": decision_trace,
            "rationale": rationale,
            "rationale_formatted": rationale_formatted,
            "benefits": benefits,
        }

        payload = scrub_job_payload_for_storage(payload)

        return {
            "apply_decision": apply_decision,
            "strongest_label": strongest_label,
            "confidence_score": confidence,
            "fit_score": fit_score,
            "ownership_strength": ownership_strength,
            "recommendation": recommendation,
            "review_reason": review_reason,
            "red_flags": red_flags,
            "rationale": rationale,
            "payload": payload,
            "benefits": benefits,
        }
    except Exception as e:
        print(f"Gemini API classification failed: {e}. Falling back to OpenAI/rule-based.", flush=True)
        return None

def classify_job_with_openai(job):
    openai_key = os.getenv("OPENAI_API_KEY")
    if not openai_key:
        return None

    # Read systemic prompt / policy from Job_classifier_prompt.txt
    prompt_path = str(WORKSPACE / "Job_classifier_prompt.txt")
    system_instruction = ""
    if os.path.exists(prompt_path):
        try:
            with open(prompt_path, 'r') as f:
                system_instruction = f.read()
        except Exception as e:
            print(f"Error reading Job_classifier_prompt.txt: {e}")
            
    if not system_instruction:
        print("Systemic prompt file not found! Falling back to rule-based classification.")
        return None

    # Load API key and build user prompt
    title = job.get("job_title", "Unknown Title")
    description = job.get("job_description", "")
    
    user_prompt = f"""
Analyze this job posting:
Title: {title}
Description:
{description}

Return a JSON object conforming exactly to the following structure (see system instruction for PASS/HUMAN_REVIEW/REJECT rules):
{{
  "all_labels": ["<same as strongest_label first, optional 2nd/3rd labels>"],
  "strongest_label": "DevOps Engineer" | "Cloud Automation Engineer" | "Platform Engineering" | "Cloud Infrastructure Engineer" | "DevSecOps" | "Site Reliability Engineer (SRE)" | "Continuous Integration (CI/CD)" | "System Engineer" | "OutOfScope",
  "other_labels": [],
  "recommendation": "PASS" | "HUMAN_REVIEW" | "REJECT",
  "confidence_score": 0-100,
  "fit_score": 0-100,
  "ownership_strength": "LOW" | "MEDIUM" | "HIGH",
  "review_reason": "short string or empty string",
  "red_flags": [],
  "cloud": {{
    "is_cloud_role": true,
    "primary_cloud": "AWS" | "Azure" | "GCP" | "",
    "cloud_providers": ["AWS", "Azure", "GCP"]
  }},
  "domain_scores": {{
    "devops": 0-10,
    "automation": 0-10,
    "platform": 0-10,
    "infrastructure": 0-10,
    "security": 0-10,
    "devsecops": 0-10,
    "sre": 0-10,
    "cicd": 0-10,
    "system": 0-10,
    "network": 0-10,
    "database": 0-10,
    "cloud_database": 0-10
  }},
  "dominant_domains": [],
  "decision_trace": {{
    "top_score": 0,
    "runner_up_score": 0,
    "tie_break_applied": false,
    "priority_rule_used": "",
    "strong_signal_override": false
  }},
  "rationale": "",
  "rationale_formatted": [],
  "filters": {{ "domain_specialization": false }},
  "benefits": []
}}
"""
    
    try:
        from openai import OpenAI
        client = OpenAI(api_key=openai_key)
        result = None
        last_err = None
        for attempt in range(1, 4):
            try:
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": system_instruction},
                        {"role": "user", "content": user_prompt}
                    ],
                    response_format={"type": "json_object"}
                )
                raw_text = response.choices[0].message.content
                result = json.loads(raw_text)
                break
            except Exception as e:
                last_err = e
                if attempt < 3:
                    time.sleep(1.0 * (2 ** (attempt - 1)))
        
        if result is None:
            raise last_err if last_err else RuntimeError("empty OpenAI response")

        allowed_label_set = set(ALLOWED_STRONGEST_LABELS)
        domain_keys = (
            "devops", "automation", "platform", "infrastructure", "security", "devsecops",
            "sre", "cicd", "system", "network", "database", "cloud_database",
        )

        strongest_label = result.get("strongest_label", "OutOfScope")
        if strongest_label not in allowed_label_set:
            strongest_label = "OutOfScope"

        red_flags = result.get("red_flags", [])
        if not isinstance(red_flags, list):
            red_flags = []
        red_flags = [str(x) for x in red_flags if x]

        recommendation = str(result.get("recommendation", "REJECT")).strip().upper()
        if recommendation not in ("PASS", "HUMAN_REVIEW", "REJECT"):
            recommendation = "REJECT"

        try:
            confidence = int(result.get("confidence_score", 0))
        except (TypeError, ValueError):
            confidence = 0
        confidence = max(0, min(100, confidence))

        try:
            fit_score = int(result.get("fit_score", 0))
        except (TypeError, ValueError):
            fit_score = 0
        fit_score = max(0, min(100, fit_score))

        ownership_strength = str(result.get("ownership_strength", "LOW")).strip().upper()
        if ownership_strength not in ("LOW", "MEDIUM", "HIGH"):
            ownership_strength = "LOW"

        review_reason = str(result.get("review_reason", "") or "").strip()

        domain_scores = result.get("domain_scores", {})
        if not isinstance(domain_scores, dict):
            domain_scores = {}
        for k in domain_keys:
            domain_scores.setdefault(k, 0)
            try:
                domain_scores[k] = max(0, min(10, int(domain_scores[k])))
            except (TypeError, ValueError):
                domain_scores[k] = 0

        all_labels = result.get("all_labels")
        if not isinstance(all_labels, list) or not all_labels:
            all_labels = [strongest_label]
        else:
            all_labels = [str(x) for x in all_labels if x]
            if not all_labels or all_labels[0] != strongest_label:
                all_labels = [strongest_label] + [x for x in all_labels if x != strongest_label]

        other_labels = result.get("other_labels", [])
        if not isinstance(other_labels, list):
            other_labels = []
        other_labels = [str(x) for x in other_labels if x and x != strongest_label]

        cloud = result.get("cloud", {})
        if not isinstance(cloud, dict):
            cloud = {}
        primary_cloud = str(cloud.get("primary_cloud", "") or "")
        if primary_cloud not in ("AWS", "Azure", "GCP", ""):
            primary_cloud = ""
        cloud_providers = cloud.get("cloud_providers", [])
        if not isinstance(cloud_providers, list):
            cloud_providers = []
        cloud_providers = [str(p) for p in cloud_providers if p in ("AWS", "Azure", "GCP")]
        is_cloud = bool(cloud.get("is_cloud_role")) if "is_cloud_role" in cloud else (
            len(cloud_providers) > 0 or primary_cloud != ""
        )
        cloud = {
            "is_cloud_role": bool(is_cloud),
            "primary_cloud": primary_cloud,
            "cloud_providers": cloud_providers,
        }

        decision_trace = result.get("decision_trace", {})
        if not isinstance(decision_trace, dict):
            decision_trace = {}
        numeric_scores = [domain_scores[k] for k in domain_keys if k in domain_scores]
        sorted_scores = sorted(numeric_scores, reverse=True) if numeric_scores else [0, 0]
        top_score = int(decision_trace.get("top_score", sorted_scores[0]))
        runner_up = int(decision_trace.get("runner_up_score", sorted_scores[1] if len(sorted_scores) > 1 else 0))
        decision_trace = {
            "top_score": top_score,
            "runner_up_score": runner_up,
            "tie_break_applied": bool(decision_trace.get("tie_break_applied", False)),
            "priority_rule_used": str(decision_trace.get("priority_rule_used", "") or ""),
            "strong_signal_override": bool(decision_trace.get("strong_signal_override", False)),
        }

        dominant_domains = result.get("dominant_domains", [])
        if not isinstance(dominant_domains, list) or not dominant_domains:
            dominant_domains = [strongest_label] if strongest_label != "OutOfScope" else []

        filters = result.get("filters", {"domain_specialization": False})
        if not isinstance(filters, dict):
            filters = {"domain_specialization": False}
        filters.setdefault("domain_specialization", False)

        benefits = result.get("benefits", [])
        if not benefits or not isinstance(benefits, list):
            benefits = extract_benefits(description)

        rationale = str(result.get("rationale", "") or "")
        rationale_formatted = result.get("rationale_formatted", [])
        if not isinstance(rationale_formatted, list):
            rationale_formatted = []

        pass_labels = allowed_label_set - {"OutOfScope"}

        # Enforce consistency with STEP 8 (safety net)
        if strongest_label == "OutOfScope" or red_flags:
            recommendation = "REJECT"
        elif recommendation == "PASS":
            if confidence < 70 or fit_score < 70:
                recommendation = "REJECT"
                review_reason = (review_reason + "; " if review_reason else "") + "PASS thresholds not met (confidence/fit)."
            elif strongest_label not in pass_labels:
                recommendation = "REJECT"
                review_reason = (review_reason + "; " if review_reason else "") + "Invalid label for PASS."

        if recommendation == "PASS" and ownership_strength == "MEDIUM":
            recommendation = "HUMAN_REVIEW"
            review_reason = (review_reason + "; " if review_reason else "") + "MEDIUM ownership requires human review."

        if recommendation == "HUMAN_REVIEW" and red_flags:
            recommendation = "REJECT"

        apply_decision = (
            "APPLY"
            if recommendation == "PASS" and not red_flags and strongest_label in pass_labels
            else "DO_NOT_APPLY"
        )

        payload = {
            "all_labels": all_labels,
            "strongest_label": strongest_label,
            "other_labels": other_labels,
            "recommendation": recommendation,
            "fit_score": fit_score,
            "ownership_strength": ownership_strength,
            "review_reason": review_reason,
            "apply_decision": apply_decision,
            "red_flags": red_flags,
            "filters": filters,
            "confidence_score": confidence,
            "cloud": cloud,
            "domain_scores": domain_scores,
            "dominant_domains": dominant_domains,
            "dominant_signals": {},
            "decision_trace": decision_trace,
            "rationale": rationale,
            "rationale_formatted": rationale_formatted,
            "benefits": benefits,
        }

        payload = scrub_job_payload_for_storage(payload)

        return {
            "apply_decision": apply_decision,
            "strongest_label": strongest_label,
            "confidence_score": confidence,
            "fit_score": fit_score,
            "ownership_strength": ownership_strength,
            "recommendation": recommendation,
            "review_reason": review_reason,
            "red_flags": red_flags,
            "rationale": rationale,
            "payload": payload,
            "benefits": benefits,
        }
    except Exception as e:
        print(f"OpenAI API classification failed: {e}. Falling back to rule-based classification.", flush=True)
        return None

def classify_job_dynamically(job):
    title = job.get("job_title", "").lower()
    desc = job.get("job_description", "").lower()
    
    label_scores = {
        "DevOps Engineer": 0,
        "Cloud Automation Engineer": 0,
        "Platform Engineering": 0,
        "Cloud Infrastructure Engineer": 0,
        "DevSecOps": 0,
        "Site Reliability Engineer (SRE)": 0,
        "Continuous Integration (CI/CD)": 0,
        "System Engineer": 0,
        "Database Engineer": 0,
        "Cloud Database Engineer": 0,
    }
    
    # Simple keyword mapping
    if "devsecops" in title:
        label_scores["DevSecOps"] += 10
    elif "secops" in title or ("security" in title and "engineer" in title):
        label_scores["DevSecOps"] += 8
        label_scores["Cloud Infrastructure Engineer"] += 2
        
    if "sre" in title or "reliability" in title:
        label_scores["Site Reliability Engineer (SRE)"] += 10
        
    if "platform" in title:
        label_scores["Platform Engineering"] += 10
            
    if "automation" in title:
        label_scores["Cloud Automation Engineer"] += 10
        
    if "infrastructure" in title:
        label_scores["Cloud Infrastructure Engineer"] += 10
        
    if "network" in title:
        label_scores["Cloud Infrastructure Engineer"] += 10
        
    if "database" in title or "dba" in title or "sql" in title:
        if "cloud" in title or any(c in title for c in ["aws", "gcp", "azure", "rds", "aurora", "dynamodb"]):
            label_scores["Cloud Database Engineer"] += 10
        else:
            label_scores["Database Engineer"] += 10
        
    if "ci/cd" in title or "cicd" in title or "release" in title or "integration" in title:
        label_scores["Continuous Integration (CI/CD)"] += 10
        
    if "devops" in title:
        label_scores["DevOps Engineer"] += 5
        
    if "system" in title or "systems" in title:
        label_scores["System Engineer"] += 5
        
    # Check description keywords (low weight)
    if "devops" in desc:
        label_scores["DevOps Engineer"] += 1
    if any(k in desc for k in ["slo", "sli", "error budget", "sre", "reliability", "observability"]):
        label_scores["Site Reliability Engineer (SRE)"] += 2
    # Platform Engineering description signals (aligned 2026-06-27 with the
    # Job_classifier_prompt.txt PLATFORM ENGINEERING RULE's MAAS definition:
    # Kubernetes lifecycle ownership + IDP + self-service workflows). Named
    # IDP products and explicit cluster-lifecycle/self-service language are
    # stronger evidence of platform ownership than a bare "kubernetes"
    # mention, so they're weighted higher - simple keyword matching, no NLP,
    # purely additive to this one label so it can't regress other roles.
    if any(k in desc for k in ["backstage", "morpheus", "harness idp", "internal developer platform"]):
        label_scores["Platform Engineering"] += 3
    if any(k in desc for k in ["golden path", "self-service", "self service platform", "developer platform", "platform engineer"]):
        label_scores["Platform Engineering"] += 2
    if any(k in desc for k in ["cluster lifecycle", "node pool", "node group", "multi-tenant kubernetes", "cluster upgrade", "cluster autoscaling"]):
        label_scores["Platform Engineering"] += 2
    if "kubernetes" in desc:
        label_scores["Platform Engineering"] += 1
    if any(k in desc for k in ["ci/cd", "pipeline", "jenkins", "github actions", "gitlab", "circleci"]):
        label_scores["Continuous Integration (CI/CD)"] += 1
    if any(k in desc for k in ["security", "compliance", "iam", "vulnerability", "threat", "soc 2"]):
        if label_scores["DevSecOps"] > 0 or "devsecops" in desc:
            label_scores["DevSecOps"] += 2
        else:
            label_scores["DevSecOps"] += 1
    if any(k in desc for k in ["database administrator", "replication", "backup and recovery", "query optimization", "database clustering", "performance tuning", "high availability"]):
        label_scores["Database Engineer"] += 2
    if any(k in desc for k in ["rds", "aurora", "cloud database", "managed database", "cosmos db", "spanner"]):
        label_scores["Cloud Database Engineer"] += 2
 
    top_label = max(label_scores, key=label_scores.get)
    top_score = label_scores[top_label]

    red_flags = list(job.get("red_flags", []))
    _nw = "Cloud network specialist role — outside MAAS consultant pipeline"
    _sw = "Cloud security specialist role — outside MAAS consultant pipeline"
    _rf = "Retired MAAS role family"
    # Data Platform Engineer / MLOps / AIOps were retired as MAAS target roles.
    # Without this explicit check, titles like "AI Platform Engineer (AIOps)"
    # would still match the generic "platform" in title heuristic above and
    # get misclassified as Platform Engineering / APPLY instead of retired.
    _retired_title_patterns = (
        "data platform engineer", "data infrastructure engineer",
        "mlops", "machine learning engineer",
        "aiops", "ai platform engineer",
        # Database Engineer / Cloud Database Engineer / DBA were retired
        # 2026-06-22 alongside Cloud Network/Security Engineer, but - unlike
        # those two - never got an explicit override check here. Confirmed
        # live 2026-06-25: 14 jobs titled "Database Engineer", "DBA Engineer",
        # "Senior Database Engineer", "Cloud Software Engineer - Database",
        # etc. were still scoring into label_scores["Database Engineer"]/
        # ["Cloud Database Engineer"] and getting auto-approved, since those
        # two labels were still present (scoreable) in the label_scores dict
        # even though the role family itself was supposed to be retired.
        "database engineer", "dba engineer", "database administrator",
    )
    if "cloud network engineer" in title:
        if _nw not in red_flags:
            red_flags.append(_nw)
        top_label = "OutOfScope"
        top_score = 0
    elif "cloud security engineer" in title:
        if _sw not in red_flags:
            red_flags.append(_sw)
        top_label = "OutOfScope"
        top_score = 0
    elif any(p in title for p in _retired_title_patterns):
        if _rf not in red_flags:
            red_flags.append(_rf)
        top_label = "OutOfScope"
        top_score = 0
    elif top_score == 0:
        # Real incident (2026-06-23): zero keyword signal used to default to
        # "DevOps Engineer" + APPLY, which auto-approved completely unrelated
        # roles (Data Scientist, Engineering Program Manager, Sustainability
        # Analyst, SAP FICO Solution Architect, ...) at high confidence
        # whenever Gemini classification failed and this rule-based fallback
        # ran instead. No signal should mean "don't know" -> OutOfScope /
        # DO_NOT_APPLY, never a default approval into the primary label.
        _zs = "No rule-based keyword signal matched any MAAS role family"
        if _zs not in red_flags:
            red_flags.append(_zs)
        top_label = "OutOfScope"

    apply_decision = "APPLY" if not red_flags else "DO_NOT_APPLY"
    recommendation = "PASS" if apply_decision == "APPLY" else "REJECT"
    fit_score = 80 if apply_decision == "APPLY" else 35
    ownership_strength = "HIGH" if apply_decision == "APPLY" else "LOW"
    review_reason = ""

    confidence = 85 if top_score > 0 else 30
    rationale = f"This job was dynamically classified as {top_label} using rule-based keyword signals matching the target role profile."
    if red_flags:
        rationale += f" Red flags detected: {', '.join(red_flags)}."
        
    benefits = extract_benefits(job.get("job_description", ""))

    domain_keys_rb = (
        "devops", "automation", "platform", "infrastructure", "security", "devsecops",
        "sre", "cicd", "system", "network", "database", "cloud_database",
    )
    domain_scores_out = dict.fromkeys(domain_keys_rb, 0)
    label_to_domain = {
        "DevOps Engineer": "devops",
        "Cloud Automation Engineer": "automation",
        "Platform Engineering": "platform",
        "Cloud Infrastructure Engineer": "infrastructure",
        "DevSecOps": "devsecops",
        "Site Reliability Engineer (SRE)": "sre",
        "Continuous Integration (CI/CD)": "cicd",
        "System Engineer": "system",
        "Database Engineer": "database",
        "Cloud Database Engineer": "cloud_database",
        "OutOfScope": "devops",
    }
    primary_dk = label_to_domain.get(top_label, "devops")
    domain_scores_out[primary_dk] = min(10, max(0, int(top_score)))
    if label_scores.get("Database Engineer", 0) > 0:
        domain_scores_out["database"] = min(10, label_scores["Database Engineer"])
    if label_scores.get("Cloud Database Engineer", 0) > 0:
        domain_scores_out["cloud_database"] = min(10, label_scores["Cloud Database Engineer"])

    payload = {
        "all_labels": [top_label],
        "strongest_label": top_label,
        "other_labels": [],
        "recommendation": recommendation,
        "fit_score": fit_score,
        "ownership_strength": ownership_strength,
        "review_reason": review_reason,
        "apply_decision": apply_decision,
        "red_flags": red_flags,
        "filters": {"domain_specialization": False},
        "confidence_score": confidence,
        "cloud": {"is_cloud_role": "cloud" in desc or "aws" in desc or "azure" in desc or "gcp" in desc, "primary_cloud": "", "cloud_providers": []},
        "domain_scores": domain_scores_out,
        "dominant_domains": [top_label],
        "dominant_signals": {},
        "decision_trace": {"top_score": top_score, "runner_up_score": 0, "tie_break_applied": False, "priority_rule_used": "", "strong_signal_override": False},
        "rationale": rationale,
        "rationale_formatted": [rationale],
        "benefits": benefits
    }
    
    return {
        "apply_decision": apply_decision,
        "strongest_label": top_label,
        "confidence_score": confidence,
        "fit_score": fit_score,
        "ownership_strength": ownership_strength,
        "recommendation": recommendation,
        "review_reason": review_reason,
        "red_flags": red_flags,
        "rationale": rationale,
        "payload": payload,
        "benefits": benefits
    }

def _record_classification_call(operation_name, model_name, elapsed_s, prompt_len_chars, success):
    """Per-job classification timing (Gemini/OpenAI/rule-based). Token count
    isn't captured here - the Gemini SDK response object would need to be
    threaded through classify_job_with_gemini()'s several return points to
    get usage_metadata, which risks the kind of invasive internal change
    this task explicitly avoids. Character-length prompt size is used as
    the available proxy instead.
    """
    try:
        from pipeline_metrics import append_pipeline_metric

        append_pipeline_metric(
            str(WORKSPACE),
            "operation",
            {
                "operation_name": operation_name,
                "stage": "classify",
                "duration_ms": int(elapsed_s * 1000),
                "success": success,
                "metadata": {"model": model_name, "prompt_length_chars": prompt_len_chars},
            },
        )
    except Exception:
        pass


def main():
    from datetime import datetime, timezone

    from pipeline_metrics import append_pipeline_metric, generate_run_summary

    _run_start_iso = datetime.now(timezone.utc).isoformat()

    _t0 = time.perf_counter()
    with open(str(resolve_path(WORKSPACE / "active_candidate_jobs.json")), "r") as f:
        jobs = json.load(f)
    append_pipeline_metric(str(WORKSPACE), "operation", {
        "operation_name": "json_load", "stage": "classify",
        "duration_ms": int((time.perf_counter() - _t0) * 1000),
        "success": True, "jobs_processed": len(jobs),
    })

    approved_hashes, failed_hashes = load_known_hashes(WORKSPACE)

    approved_jobs = []

    for job in jobs:
        cls = None
        h = job.get("description_hash")
        if not cls and h:
            if h in approved_hashes:
                print(f"  Cache HIT (Approved) for '{job.get('job_title')}'. Reusing classification.", flush=True)
                matched = approved_hashes[h]
                cls = {
                    "apply_decision": matched.get("apply_decision", "APPLY"),
                    "strongest_label": matched.get("strongest_label", ""),
                    "confidence_score": matched.get("confidence_score", 100),
                    "red_flags": matched.get("red_flags", []),
                    "rationale": matched.get("rationale", ""),
                    "payload": matched.get("apply_decision_payload", {})
                }
                cls["benefits"] = matched.get("benefits") if "benefits" in matched else extract_benefits(matched.get("job_description", ""))
                if "requirement_id" in matched:
                    cls["req_id_override"] = matched["requirement_id"]
                # Copy pipeline & salary fields to prevent wiping them out during runs
                for key in ["pipeline_stage", "min_salary", "max_salary", "is_hourly", "salary_text"]:
                    if key in matched:
                        job[key] = matched[key]
            elif h in failed_hashes:
                print(f"  Cache HIT (Failed) for '{job.get('job_title')}'. Reusing rejection.", flush=True)
                matched = failed_hashes[h]
                cls = {
                    "apply_decision": "DO_NOT_APPLY",
                    "strongest_label": matched.get("strongest_label", ""),
                    "confidence_score": matched.get("confidence_score", 100),
                    "red_flags": matched.get("red_flags", ["Previously rejected"]),
                    "rationale": matched.get("rationale", "Previously rejected cache hit."),
                    "payload": matched.get("apply_decision_payload", {})
                }
                cls["benefits"] = matched.get("benefits") if "benefits" in matched else extract_benefits(matched.get("job_description", ""))
                # Copy pipeline & salary fields for failed cache hits too
                for key in ["pipeline_stage", "min_salary", "max_salary", "is_hourly", "salary_text"]:
                    if key in matched:
                        job[key] = matched[key]
            
        if not cls:
            prompt_len_chars = len(job.get("job_title", "") or "") + len(job.get("job_description", "") or "")

            # Try LLM-driven classification if active Gemini key exists
            active_gemini_key = get_active_gemini_key()
            if active_gemini_key:
                print(f"  Classifying '{job.get('job_title')}' dynamically using Gemini API...", flush=True)
                time.sleep(4)
                _t0 = time.perf_counter()
                cls = classify_job_with_gemini(job)
                _record_classification_call(
                    "gemini_classify", "gemini-2.5-flash", time.perf_counter() - _t0,
                    prompt_len_chars, success=bool(cls),
                )

            # Try OpenAI fallback if Gemini failed or is not available
            if not cls and os.getenv("OPENAI_API_KEY"):
                print(f"  Classifying '{job.get('job_title')}' dynamically using OpenAI API (gpt-4o-mini)...", flush=True)
                time.sleep(1)
                _t0 = time.perf_counter()
                cls = classify_job_with_openai(job)
                _record_classification_call(
                    "openai_classify", "gpt-4o-mini", time.perf_counter() - _t0,
                    prompt_len_chars, success=bool(cls),
                )

            if not cls:
                # Fall back to dynamic rule-based classifier
                print(f"  Classifying '{job.get('job_title')}' dynamically using keyword rules...", flush=True)
                _t0 = time.perf_counter()
                cls = classify_job_dynamically(job)
                _record_classification_call(
                    "rule_based_classify", "none", time.perf_counter() - _t0,
                    prompt_len_chars, success=bool(cls),
                )
            
        job["apply_decision"] = cls["apply_decision"]
        job["strongest_label"] = cls["strongest_label"]
        job["confidence_score"] = cls["confidence_score"]
        job["red_flags"] = cls["red_flags"]
        job["rationale"] = cls["rationale"]
        job["apply_decision_payload"] = cls["payload"]
        job["benefits"] = cls.get("benefits", [])
        _pl = cls.get("payload") or {}
        job["recommendation"] = cls.get("recommendation") or _pl.get(
            "recommendation", "PASS" if cls["apply_decision"] == "APPLY" else "REJECT"
        )
        job["fit_score"] = cls.get("fit_score", _pl.get("fit_score", 80 if cls["apply_decision"] == "APPLY" else 35))
        job["ownership_strength"] = cls.get("ownership_strength", _pl.get("ownership_strength", "LOW"))
        job["review_reason"] = cls.get("review_reason", _pl.get("review_reason", ""))
        
        # Override requirement ID if needed
        if "req_id_override" in cls:
            job["requirement_id"] = cls["req_id_override"]
            
        # Approved-category gate
        allowed_categories = {
            "DevOps Engineer", "Cloud Automation Engineer", "Platform Engineering",
            "Cloud Infrastructure Engineer", "DevSecOps",
            "Site Reliability Engineer (SRE)", "Continuous Integration (CI/CD)",
            "System Engineer"
        }
        if (job["apply_decision"] == "APPLY" and 
            len(job["red_flags"]) == 0 and 
            job["strongest_label"] in allowed_categories and
            job["job_url"] and
            job["requirement_id"] and
            job["requirement_id"] != "Unknown"):
            approved_jobs.append(job)
            
    # Final sanity check: ensure no invalid jobs are written to approved_jobs.json
    from scripts.scrape_and_filter_candidates import check_red_flags
    allowed_categories = {
        "DevOps Engineer", "Cloud Automation Engineer", "Platform Engineering",
        "Cloud Infrastructure Engineer", "DevSecOps",
        "Site Reliability Engineer (SRE)", "Continuous Integration (CI/CD)",
        "System Engineer"
    }
    approved_jobs = [
        j for j in approved_jobs
        if j.get("apply_decision") == "APPLY" and
           len(j.get("red_flags", [])) == 0 and
           j.get("strongest_label") in allowed_categories and
           len(check_red_flags(j)) == 0
    ]
    
    # Write to approved_jobs.json
    _t0 = time.perf_counter()
    output_path = str(resolve_path(WORKSPACE / "approved_jobs.json"))
    with open(output_path, "w") as f:
        json.dump(approved_jobs, f, indent=2)
    append_pipeline_metric(str(WORKSPACE), "operation", {
        "operation_name": "save_to_json", "stage": "classify",
        "duration_ms": int((time.perf_counter() - _t0) * 1000),
        "success": True, "jobs_processed": len(approved_jobs),
        "metadata": {"jobs_in": len(jobs), "jobs_approved": len(approved_jobs)},
    })

    print(f"Successfully classified {len(jobs)} candidates.")
    print(f"Saved {len(approved_jobs)} approved jobs to {output_path}:")
    for j in approved_jobs:
        print(f"  - [{j['company_name']}] {j['job_title']} ({j['strongest_label']}) - Req ID: {j['requirement_id']}")

    generate_run_summary(str(WORKSPACE), _run_start_iso)

if __name__ == '__main__':
    main()
