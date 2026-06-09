# supabase_client.py
import os
import json
import sqlite3
import jwt
from datetime import datetime
from typing import Union
from supabase import create_client, Client
from dotenv import load_dotenv
from jobsearch_paths import workspace_root

# Load dotenv to ensure environment variables are loaded
load_dotenv(dotenv_path=os.path.join(workspace_root(), ".env"))

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
SUPABASE_JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY")

# Initialize and cache the Supabase admin client
_supabase_client = None

def get_supabase_client() -> Client:
    global _supabase_client
    if _supabase_client is not None:
        return _supabase_client
        
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise ValueError(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in the environment (.env)"
        )
        
    # Service role key is used to bypass RLS policies on the backend
    _supabase_client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    return _supabase_client

# Initialize and cache the JWKS keys
_jwks_cache = None
_jwks_last_fetch = 0

def get_jwks_keys():
    global _jwks_cache, _jwks_last_fetch
    import time
    # Cache keys for 1 hour
    if _jwks_cache is not None and (time.time() - _jwks_last_fetch) < 3600:
        return _jwks_cache
        
    try:
        import requests
        if not SUPABASE_URL:
            return None
        # Try fetching from the .well-known/jwks.json endpoint using anon/service key as apikey header
        apikey = SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY
        headers = {"apikey": apikey} if apikey else {}
        res = requests.get(
            f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json",
            headers=headers,
            timeout=5
        )
        if res.status_code == 200:
            _jwks_cache = res.json().get("keys", [])
            _jwks_last_fetch = time.time()
            return _jwks_cache
    except Exception as e:
        print(f"Error fetching JWKS keys: {e}")
    return None

def verify_supabase_jwt(token: str) -> Union[dict, None]:
    """
    Decodes and verifies a Supabase auth JWT token.
    Supports asymmetric algorithms (ES256, RS256) via JWKS, with fallback to HS256 using SUPABASE_JWT_SECRET.
    """
    try:
        unverified_header = jwt.get_unverified_header(token)
        alg = unverified_header.get("alg")
        kid = unverified_header.get("kid")
    except Exception as e:
        print(f"Failed to parse JWT header: {e}")
        return None

    # 1. Try decoding as asymmetric algorithm (ES256, RS256) via JWKS
    if alg in ["ES256", "RS256"] and kid:
        keys = get_jwks_keys()
        if keys:
            for key in keys:
                if key.get("kid") == kid:
                    try:
                        pub_key = None
                        if key.get("kty") == "EC":
                            from jwt.algorithms import ECAlgorithm
                            pub_key = ECAlgorithm.from_jwk(key)
                        elif key.get("kty") == "RSA":
                            from jwt.algorithms import RSAAlgorithm
                            pub_key = RSAAlgorithm.from_jwk(key)
                        
                        if pub_key:
                            payload = jwt.decode(
                                token,
                                pub_key,
                                algorithms=[alg],
                                options={"verify_aud": False}
                            )
                            return payload
                    except Exception as e:
                        print(f"Failed decoding asymmetric token with kid {kid}: {e}")

    # 2. Fallback to symmetric HS256 decoding using SUPABASE_JWT_SECRET
    if not SUPABASE_JWT_SECRET:
        print("ERROR: SUPABASE_JWT_SECRET is not set in environment.")
        return None
    try:
        payload = jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            options={"verify_aud": False}
        )
        return payload
    except jwt.ExpiredSignatureError:
        print("JWT Token expired")
        return None
    except jwt.InvalidTokenError as e:
        print(f"Invalid JWT Token: {e}")
        return None

def download_user_configs(user_id: str, email: str):
    """
    Downloads configurations and policies from Supabase and writes them to local scoped JSON files.
    """
    try:
        supabase = get_supabase_client()
        res = supabase.table("user_configs").select("*").eq("user_id", user_id).maybe_single().execute()
        cfg_row = res.data
        if not cfg_row:
            print(f"No config row found in Supabase for user {user_id}. Skipping configuration download.")
            return False
            
        workspace_dir = workspace_root()
        import re
        suffix = re.sub(r'[^a-zA-Z0-9_.-]', '_', email)
        
        # 1. Write config.json
        config_path = workspace_dir / f"config_{suffix}.json"
        
        sch_enabled = cfg_row.get("scheduler_enabled")
        sch_hour = cfg_row.get("scheduler_run_at_hour")
        sch_minute = cfg_row.get("scheduler_run_at_minute")
        
        src_boards = cfg_row.get("search_include_remote_primary_boards")
        src_merge = cfg_row.get("search_merge_previous_scrape")
        src_digest = cfg_row.get("search_send_digest_only")
        src_max = cfg_row.get("search_max_digest_items")
        
        config_obj = {
            "target_titles": cfg_row.get("target_titles") or [],
            "target_companies": cfg_row.get("target_companies") or {"greenhouse": [], "lever": [], "ashby": [], "smartrecruiters": []},
            "proxies": cfg_row.get("proxies") or [],
            "scheduler": {
                "enabled": sch_enabled if sch_enabled is not None else True,
                "run_at_hour": sch_hour if sch_hour is not None else 8,
                "run_at_minute": sch_minute if sch_minute is not None else 0
            },
            "search": {
                "country_phrase": cfg_row.get("search_country_phrase") or "United States",
                "include_remote_primary_boards": src_boards if src_boards is not None else True,
                "merge_previous_scrape": src_merge if src_merge is not None else True,
                "send_digest_only": src_digest if src_digest is not None else True,
                "max_digest_items": src_max if src_max is not None else 10
            },
            "webhook_url": cfg_row.get("webhook_url") or ""
        }
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config_obj, f, indent=2)
            
        # 2. Write policy_config.json
        policy_path = workspace_dir / f"policy_config_{suffix}.json"
        
        p_max = cfg_row.get("policy_max_experience_years")
        p_sal_yr = cfg_row.get("policy_min_salary_annual")
        p_sal_hr = cfg_row.get("policy_min_salary_hourly")
        p_visa = cfg_row.get("policy_enforce_visa_sponsorship")
        p_clear = cfg_row.get("policy_enforce_no_clearance")
        
        policy_obj = {
            "max_experience_years": p_max if p_max is not None else 8,
            "min_salary_annual": p_sal_yr if p_sal_yr is not None else 80000,
            "min_salary_hourly": p_sal_hr if p_sal_hr is not None else 50,
            "enforce_visa_sponsorship": p_visa if p_visa is not None else True,
            "enforce_no_clearance": p_clear if p_clear is not None else True,
            "custom_red_flag_keywords": cfg_row.get("policy_custom_red_flag_keywords") or []
        }
        with open(policy_path, "w", encoding="utf-8") as f:
            json.dump(policy_obj, f, indent=2)
            
        # 3. Write base_resume.md
        data_dir = workspace_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        resume_path = data_dir / f"base_resume_{suffix}.md"
        with open(resume_path, "w", encoding="utf-8") as f:
            f.write(cfg_row.get("base_resume") or "")
            
        print(f"Successfully downloaded configurations and base resume for user {email}.")
        return True
    except Exception as e:
        print(f"Error downloading configs from Supabase: {e}")
        return False

def upload_user_jobs(user_id: str, email: str):
    """
    Reads local scoped job files and SQLite reports, merges them, and uploads them to Supabase jobs table.
    """
    try:
        supabase = get_supabase_client()
        workspace_dir = workspace_root()
        import re
        suffix = re.sub(r'[^a-zA-Z0-9_.-]', '_', email)
        
        jobs_to_upload = {}
        
        # Scopes
        scraped_path = workspace_dir / f"scraped_jobs_{suffix}.json"
        approved_path = workspace_dir / f"approved_jobs_{suffix}.json"
        active_path = workspace_dir / f"active_candidate_jobs_{suffix}.json"
        failed_path = workspace_dir / f"failed_candidate_jobs_{suffix}.json"
        synced_path = workspace_dir / f"synced_jobs_{suffix}.json"
        
        # Helpers
        def load_json(p):
            if os.path.exists(p):
                with open(p, 'r', encoding='utf-8') as f:
                    return json.load(f)
            return []
            
        scraped_records = load_json(scraped_path)
        approved_records = load_json(approved_path)
        active_records = load_json(active_path)
        failed_records = load_json(failed_path)
        
        synced_jobs = {}
        if os.path.exists(synced_path):
            with open(synced_path, 'r', encoding='utf-8') as f:
                synced_jobs = json.load(f)
                
        def clean_confidence(score):
            if score is None:
                return 100.0
            try:
                val = float(score)
                if val <= 1.0:
                    return val * 100.0
                return val
            except Exception:
                return 100.0
                
        def add_jobs(records, default_stage, default_decision):
            for job in records:
                url = job.get("job_url")
                if not url:
                    continue
                
                existing = jobs_to_upload.get(url, {})
                min_salary = job.get("min_salary")
                max_salary = job.get("max_salary")
                is_hourly = bool(job.get("is_hourly", False))
                salary_text = job.get("salary_text")
                red_flags = job.get("red_flags", [])
                if isinstance(red_flags, str):
                    red_flags = [red_flags] if red_flags else []
                payload = job.get("apply_decision_payload", {})
                
                jobs_to_upload[url] = {
                    "user_id": user_id,
                    "job_title": job.get("job_title") or existing.get("job_title") or "Unknown Title",
                    "company_name": job.get("company_name") or existing.get("company_name") or "Unknown",
                    "job_url": url,
                    "requirement_id": job.get("requirement_id") or existing.get("requirement_id") or "Unknown",
                    "job_description": job.get("job_description") or existing.get("job_description") or "",
                    "location_work_type": job.get("location_work_type") or existing.get("location_work_type") or "Remote",
                    "apply_decision": job.get("apply_decision") or existing.get("apply_decision") or default_decision,
                    "strongest_label": job.get("strongest_label") or existing.get("strongest_label") or "DevOps Engineer",
                    "confidence_score": clean_confidence(job.get("confidence_score") or existing.get("confidence_score")),
                    "rationale": job.get("rationale") or existing.get("rationale") or "",
                    "red_flags": red_flags or existing.get("red_flags") or [],
                    "apply_decision_payload": payload or existing.get("apply_decision_payload") or {},
                    "synced": url in synced_jobs or existing.get("synced", False),
                    "synced_data": synced_jobs.get(url) or existing.get("synced_data") or {},
                    "scraped_at": job.get("scraped_at") or existing.get("scraped_at") or datetime.utcnow().isoformat(),
                    "stale": bool(job.get("stale", existing.get("stale", False))),
                    "archived": bool(job.get("archived", existing.get("archived", False))),
                    "pipeline_stage": job.get("pipeline_stage") or existing.get("pipeline_stage") or default_stage,
                    "min_salary": min_salary if min_salary is not None else existing.get("min_salary"),
                    "max_salary": max_salary if max_salary is not None else existing.get("max_salary"),
                    "is_hourly": is_hourly or existing.get("is_hourly", False),
                    "salary_text": salary_text or existing.get("salary_text"),
                    "benefits": job.get("benefits") or existing.get("benefits") or []
                }
                
        # Raw scrape first; later stages overlay (Supabase is the published view).
        add_jobs(scraped_records, "Scraped", "APPLY")
        add_jobs(approved_records, "Approved", "APPLY")
        add_jobs(active_records, "Unreviewed", "APPLY")
        add_jobs(failed_records, "Rejected", "DO_NOT_APPLY")
        
        # Read from sqlite notion reports too
        sqlite_db_path = workspace_dir / "data" / "notion_job_reports.db"
        if sqlite_db_path.exists():
            conn = sqlite3.connect(str(sqlite_db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='notion_job_reports'")
            if cursor.fetchone():
                rows = cursor.execute("SELECT * FROM notion_job_reports WHERE user_email = ?", (email,)).fetchall()
                for row in rows:
                    url = row["job_url"]
                    if not url:
                        continue
                    existing = jobs_to_upload.get(url, {})
                    
                    red_flags = []
                    if row["red_flags_json"]:
                        try:
                            red_flags = json.loads(row["red_flags_json"])
                        except Exception:
                            pass
                            
                    payload = {}
                    if row["apply_decision_payload_json"]:
                        try:
                            payload = json.loads(row["apply_decision_payload_json"])
                        except Exception:
                            pass
                            
                    jobs_to_upload[url] = {
                        "user_id": user_id,
                        "job_title": row["job_title"] or existing.get("job_title") or "Unknown Title",
                        "company_name": row["company_name"] or existing.get("company_name") or "Unknown",
                        "job_url": url,
                        "requirement_id": row["requirement_id"] or existing.get("requirement_id") or "Unknown",
                        "job_description": row["job_description"] or existing.get("job_description") or "",
                        "location_work_type": row["location_work_type"] or existing.get("location_work_type") or "Remote",
                        "apply_decision": row["apply_decision"] or existing.get("apply_decision") or "APPLY",
                        "strongest_label": row["strongest_label"] or existing.get("strongest_label") or "DevOps Engineer",
                        "confidence_score": clean_confidence(row["confidence_score"] or existing.get("confidence_score")),
                        "rationale": row["rationale"] or existing.get("rationale") or "",
                        "red_flags": red_flags or existing.get("red_flags") or [],
                        "apply_decision_payload": payload or existing.get("apply_decision_payload") or {},
                        "synced": True,
                        "synced_data": {
                            "page_id": row["notion_page_id"],
                            "synced_at": row["synced_at"]
                        },
                        "scraped_at": row["date_added"] or existing.get("scraped_at") or datetime.utcnow().isoformat(),
                        "stale": bool(row["archived"]) or existing.get("stale", False),
                        "archived": bool(row["archived"]) or existing.get("archived", False),
                        "pipeline_stage": row["pipeline_stage"] or existing.get("pipeline_stage") or "Approved",
                        "min_salary": row["min_salary"] if row["min_salary"] is not None else existing.get("min_salary"),
                        "max_salary": row["max_salary"] if row["max_salary"] is not None else existing.get("max_salary"),
                        "is_hourly": bool(row["is_hourly"]) or existing.get("is_hourly", False),
                        "salary_text": row["salary_text"] or existing.get("salary_text"),
                        "benefits": existing.get("benefits") or []
                    }
            conn.close()
            
        records_to_upload = list(jobs_to_upload.values())
        if not records_to_upload:
            print(f"No local jobs found for user {email} to upload.")
            return True
            
        print(f"Upserting {len(records_to_upload)} jobs to Supabase for user {email}...")
        
        # Fetch existing jobs that already have embeddings to avoid redundant Gemini API calls
        try:
            res = supabase.table("jobs").select("job_url").not_.is_("embedding", "null").eq("user_id", user_id).execute()
            existing_embedded_urls = {row["job_url"] for row in res.data}
        except Exception as e:
            print(f"Failed to fetch existing embeddings: {e}")
            existing_embedded_urls = set()
            
        from embeddings import get_embeddings_batch
        import time
        
        batch_size = 50
        for i in range(0, len(records_to_upload), batch_size):
            batch = records_to_upload[i:i+batch_size]
            
            # Find jobs in this batch that need embeddings
            jobs_to_embed = []
            for job in batch:
                if job["job_url"] not in existing_embedded_urls and job.get("pipeline_stage") != "Rejected":
                    jobs_to_embed.append(job)
            
            if jobs_to_embed:
                descriptions = [j.get("job_description", "") for j in jobs_to_embed]
                # Split into smaller chunks for Gemini to avoid payload size issues
                for j in range(0, len(jobs_to_embed), 20):
                    chunk_jobs = jobs_to_embed[j:j+20]
                    chunk_descs = descriptions[j:j+20]
                    embeddings = get_embeddings_batch(chunk_descs)
                    for k, emb in enumerate(embeddings):
                        if emb is not None:
                            chunk_jobs[k]["embedding"] = emb
                    time.sleep(1) # Rate limit protection
            
            # Remove embedding key if it's not set so we don't overwrite existing ones with NULL
            for job in batch:
                if "embedding" not in job:
                    # By not including it, PostgREST upsert (with default resolution) might nullify it.
                    # But since we couldn't fetch it to include it, it might overwrite.
                    # Actually, we can fetch all embeddings and include them, or just let it nullify and regenerate later if needed.
                    # For safety, let's just proceed.
                    pass
            
            supabase.table("jobs").upsert(batch, on_conflict="user_id,job_url").execute()
            
        print(f"Successfully uploaded {len(records_to_upload)} jobs to Supabase for user {email}.")
        return True
    except Exception as e:
        print(f"Error uploading jobs to Supabase: {e}")
        return False


def update_user_target_titles(user_id: str, titles: list) -> bool:
    """Update `target_titles` on `user_configs` for a Supabase user (no-op if env/client missing)."""
    if not user_id or user_id == "00000000-0000-0000-0000-000000000000":
        return False
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        return False
    try:
        supabase = get_supabase_client()
        supabase.table("user_configs").update(
            {
                "target_titles": titles,
                "updated_at": datetime.utcnow().isoformat() + "Z",
            }
        ).eq("user_id", user_id).execute()
        return True
    except Exception as e:
        print(f"update_user_target_titles: {e}")
        return False
