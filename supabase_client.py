# supabase_client.py
import os
import json
import time
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
        
        db_jooble_key = cfg_row.get("jooble_api_key") or ""
        target_companies_val = cfg_row.get("target_companies")
        fallback_jooble_key = target_companies_val.get("jooble_api_key") if isinstance(target_companies_val, dict) else ""
        jooble_key = db_jooble_key or fallback_jooble_key or ""

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
                "max_digest_items": src_max if src_max is not None else 10,
                "jooble_api_key": jooble_key
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

_ATS_HOST_HINTS = (
    ("greenhouse.io", "greenhouse"),
    ("lever.co", "lever"),
    ("myworkdayjobs.com", "workday"),
    ("workdayjobs.com", "workday"),
    ("icims.com", "icims"),
    ("ashbyhq.com", "ashby"),
    ("smartrecruiters.com", "smartrecruiters"),
    ("linkedin.com", "linkedin"),
    ("indeed.com", "indeed"),
    ("weworkremotely.com", "weworkremotely"),
    ("remote.co", "remote_co"),
    ("workatastartup.com", "ycombinator"),
)


def _guess_ats_source(job_url: str) -> str:
    domain = (job_url or "").lower()
    for hint, name in _ATS_HOST_HINTS:
        if hint in domain:
            return name
    return "generic"


def _dedupe_by_canonical_fingerprint(supabase, user_id: str, records: list) -> list:
    """Merge same-canonical-job records (same company+title+location, different
    job_url) into one row with multiple tracked sources, instead of letting a
    Workday posting / LinkedIn repost / company-page repost become 3 separate
    rows. Real problem this fixes: a user sees the same opening 2-4 times in
    their feed under different URLs - this collapses them to 1 job, N sources.
    """
    from job_fingerprint import canonical_fingerprint, make_source_entry

    for r in records:
        r["canonical_fingerprint"] = canonical_fingerprint(r)
        r.setdefault("ats_source", _guess_ats_source(r.get("job_url", "")))

    fingerprints = list({r["canonical_fingerprint"] for r in records if r.get("canonical_fingerprint")})
    if not fingerprints:
        return records

    # Look up existing canonical rows for this user that already own one of
    # these fingerprints, so a repost discovered today merges into whatever
    # row already exists instead of creating a new duplicate.
    existing_by_fp: dict[str, dict] = {}
    try:
        res = (
            supabase.table("jobs")
            .select("job_url,canonical_fingerprint,sources")
            .eq("user_id", user_id)
            .in_("canonical_fingerprint", fingerprints)
            .execute()
        )
        for row in res.data or []:
            fp = row.get("canonical_fingerprint")
            if fp and fp not in existing_by_fp:
                existing_by_fp[fp] = row
    except Exception as e:
        # canonical_fingerprint column may not exist yet on this install
        # (schema migration not yet applied) - degrade to no-op, same
        # behavior as before this feature existed.
        print(f"Canonical-fingerprint dedup skipped (schema not migrated yet?): {e}")
        return records

    merged: dict[str, dict] = {}
    sources_to_append: dict[str, list] = {}  # existing job_url -> new source entries

    for r in records:
        fp = r.get("canonical_fingerprint")
        existing_row = existing_by_fp.get(fp) if fp else None

        if existing_row and existing_row["job_url"] != r["job_url"]:
            # A different URL already canonically owns this fingerprint -
            # don't insert this record as a new row, just record its URL as
            # an extra source on the existing canonical row.
            sources_to_append.setdefault(existing_row["job_url"], []).append(
                make_source_entry(r, r.get("ats_source"))
            )
            continue

        if fp in merged:
            # Two new records in this same batch share a fingerprint (e.g.
            # discovered via two sources in the same run) - keep the first as
            # canonical, fold the rest in as extra sources on it.
            merged[fp].setdefault("sources", [])
            merged[fp]["sources"].append(make_source_entry(r, r.get("ats_source")))
            continue

        r.setdefault("sources", [])
        r["sources"].append(make_source_entry(r, r.get("ats_source")))
        merged[fp] = r

    for existing_url, new_sources in sources_to_append.items():
        try:
            current = existing_by_fp[
                next(fp for fp, row in existing_by_fp.items() if row["job_url"] == existing_url)
            ].get("sources") or []
            existing_urls = {s.get("source_url") for s in current}
            additions = [s for s in new_sources if s.get("source_url") not in existing_urls]
            if additions:
                supabase.table("jobs").update({"sources": current + additions}).eq(
                    "user_id", user_id
                ).eq("job_url", existing_url).execute()
        except Exception as e:
            print(f"Failed to append merged sources for {existing_url}: {e}")

    return list(merged.values())


def _attach_sponsorship_fields(records: list) -> None:
    """Compute sponsorship_status/sponsorship_confidence in place for each record.

    Deterministic (regex + h1b_sponsors lookup), not an LLM call - see
    sponsorship_classifier.py for why. get_h1b_sponsors_cleaned() is its own
    1-hour cache, so this doesn't add a new Supabase round-trip per call.
    """
    try:
        from h1b_sponsors import get_h1b_sponsors_cleaned
        from sponsorship_classifier import classify_sponsorship

        sponsors_cleaned = get_h1b_sponsors_cleaned()
    except Exception as e:
        print(f"Sponsorship classification skipped (h1b_sponsors unavailable): {e}")
        return

    for r in records:
        try:
            result = classify_sponsorship(r, sponsors_cleaned)
            r["sponsorship_status"] = result["sponsorship_status"]
            r["sponsorship_confidence"] = result["confidence_score"]
        except Exception as e:
            print(f"Sponsorship classification failed for {r.get('job_url')}: {e}")


def _record_supabase_upsert(elapsed_s, batch_size, success):
    try:
        from pipeline_metrics import append_pipeline_metric

        append_pipeline_metric(
            str(workspace_root()),
            "operation",
            {
                "operation_name": "supabase_upsert",
                "stage": "classify",
                "duration_ms": int(elapsed_s * 1000),
                "success": success,
                "jobs_processed": batch_size,
            },
        )
    except Exception:
        pass


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
                    # Real incident (2026-06-25): this used to default unconditionally to
                    # "DevOps Engineer" regardless of default_decision. A job with no
                    # apply_decision/strongest_label is one classify_and_save.py never
                    # finished classifying (it only ever writes the APPROVED subset back
                    # out - rejected jobs are silently dropped, and active_candidate_jobs.json
                    # is never updated in place). Defaulting those to "DevOps Engineer"/APPLY
                    # put real rejects (confirmed live: "Cloud Security Engineer", "Senior
                    # Database Engineer" - both retired role families) into the live Approved
                    # feed. "Don't know" should default to OutOfScope, never an auto-approve.
                    "strongest_label": job.get("strongest_label") or existing.get("strongest_label") or (
                        "OutOfScope" if default_decision == "DO_NOT_APPLY" else "DevOps Engineer"
                    ),
                    "confidence_score": clean_confidence(job.get("confidence_score") or existing.get("confidence_score")),
                    "rationale": job.get("rationale") or existing.get("rationale") or "",
                    "red_flags": red_flags or existing.get("red_flags") or [],
                    "apply_decision_payload": payload or existing.get("apply_decision_payload") or {},
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
        # "Unreviewed" retired (2026-06-25): there is no human-review step in this
        # pipeline - classify_and_save.py auto-decides APPLY/DO_NOT_APPLY for every
        # job. active_candidate_jobs.json entries that reach this call are ones
        # classify_and_save.py never wrote a final decision for (i.e. it rejected
        # them, since it only writes the approved subset back out) - default them
        # to DO_NOT_APPLY/Rejected, not APPLY, so an unclassified job can't look
        # like an approved one in the live feed.
        add_jobs(active_records, "Rejected", "DO_NOT_APPLY")
        add_jobs(failed_records, "Rejected", "DO_NOT_APPLY")
        
        records_to_upload = list(jobs_to_upload.values())

        # US-location gate: never upload non-US jobs to Supabase.
        # The pipeline filters at discovery/scrape time but scraped_jobs.json
        # (stage-1 output) is uploaded raw above — some non-US entries can
        # slip through before stage 2/3 filtering runs. This is the final
        # backstop so no non-US row ever lands in public.jobs.
        try:
            from find_and_scrape_jobs import is_us_location as _is_us
            before_us = len(records_to_upload)
            records_to_upload = [
                r for r in records_to_upload
                if _is_us(r.get("location_work_type") or "") or not (r.get("location_work_type") or "").strip()
            ]
            dropped_us = before_us - len(records_to_upload)
            if dropped_us:
                print(f"US-location gate: dropped {dropped_us} non-US jobs before Supabase upload for {email}.")
        except Exception as e:
            print(f"US-location gate unavailable, skipping: {e}")

        official_only = False
        try:
            cfg_res = (
                supabase.table("user_configs")
                .select("search_official_career_job_urls_only")
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            cfg_rows = cfg_res.data or []
            if cfg_rows:
                official_only = bool(cfg_rows[0].get("search_official_career_job_urls_only"))
        except Exception:
            pass

        if official_only:
            from employer_job_url import is_official_company_careers_job_url

            before_ct = len(records_to_upload)
            records_to_upload = [
                r for r in records_to_upload if is_official_company_careers_job_url(r.get("job_url") or "")
            ]
            dropped = before_ct - len(records_to_upload)
            if dropped:
                print(
                    f"search_official_career_job_urls_only: excluded {dropped} non-company-hosted apply URLs from upload for {email}."
                )

        if not records_to_upload:
            print(f"No local jobs found for user {email} to upload.")
            return True

        records_to_upload = _dedupe_by_canonical_fingerprint(supabase, user_id, records_to_upload)
        _attach_sponsorship_fields(records_to_upload)

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
            
            _t_upsert = time.perf_counter()
            _upsert_ok = True
            try:
                supabase.table("jobs").upsert(batch, on_conflict="user_id,job_url").execute()
            except Exception as e:
                # canonical_fingerprint/ats_source/sources columns may not exist
                # yet (scripts/add_canonical_fingerprint_columns.sql not yet
                # applied to this install) - retry once without them rather than
                # hard-failing the whole upload on a schema mismatch.
                if "column" in str(e).lower() or "42703" in str(e):
                    new_columns = ("canonical_fingerprint", "ats_source", "sources", "sponsorship_status", "sponsorship_confidence")
                    stripped = [{k: v for k, v in r.items() if k not in new_columns} for r in batch]
                    supabase.table("jobs").upsert(stripped, on_conflict="user_id,job_url").execute()
                else:
                    _upsert_ok = False
                    raise
            finally:
                _record_supabase_upsert(time.perf_counter() - _t_upsert, len(batch), _upsert_ok)

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
