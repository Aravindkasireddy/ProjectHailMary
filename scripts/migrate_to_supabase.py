# scripts/migrate_to_supabase.py
import os
import sys
import json
import sqlite3
import argparse
from pathlib import Path
from datetime import datetime

# Add root folder to sys.path so we can import supabase_client
sys.path.append(str(Path(__file__).resolve().parent.parent))
from supabase_client import get_supabase_client

def load_json_file(file_path):
    if not os.path.exists(file_path):
        return []
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                return list(data.values())
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
    return []

def clean_confidence_score(score):
    if score is None:
        return 100.0
    try:
        val = float(score)
        if val <= 1.0:
            return val * 100.0
        return val
    except Exception:
        return 100.0

def migrate(user_id):
    print("Initializing Supabase Client...")
    try:
        supabase = get_supabase_client()
    except Exception as e:
        print(f"Failed to initialize Supabase client: {e}")
        sys.exit(1)

    workspace_dir = Path(__file__).resolve().parent.parent
    jobs_to_migrate = {}

    print("Gathering legacy jobs from JSON files...")
    # Scan root directory for JSON job files
    json_files = list(workspace_dir.glob("*.json"))
    
    # Also check if there's any file in data directory
    if os.path.exists(workspace_dir / "data"):
        json_files.extend(list((workspace_dir / "data").glob("*.json")))

    for path in json_files:
        name = path.name.lower()
        if not any(k in name for k in ["jobs", "scraped", "candidate", "approved", "failed", "synced"]):
            continue
        
        print(f"Processing JSON file: {path.name}")
        records = load_json_file(path)
        
        # Determine status and pipeline stage from name
        default_stage = "Scraped"
        default_decision = "APPLY"
        
        if "approved" in name:
            default_stage = "Approved"
            default_decision = "APPLY"
        elif "failed" in name:
            default_stage = "Rejected"
            default_decision = "DO_NOT_APPLY"
        elif "candidate" in name:
            default_stage = "Unreviewed"
            default_decision = "APPLY"
        
        for job in records:
            url = job.get("job_url")
            if not url:
                continue
                
            # Keep unique jobs and merge details (favouring approved/processed details)
            existing = jobs_to_migrate.get(url, {})
            
            # Extract salary info
            min_salary = job.get("min_salary")
            max_salary = job.get("max_salary")
            is_hourly = bool(job.get("is_hourly", False))
            salary_text = job.get("salary_text")
            
            red_flags = job.get("red_flags", [])
            if isinstance(red_flags, str):
                red_flags = [red_flags] if red_flags else []
                
            payload = job.get("apply_decision_payload", {})
            if not payload and isinstance(job.get("apply_decision_payload_json"), str):
                try:
                    payload = json.loads(job.get("apply_decision_payload_json"))
                except Exception:
                    pass

            merged = {
                "user_id": user_id,
                "job_title": job.get("job_title") or existing.get("job_title") or "Unknown Title",
                "company_name": job.get("company_name") or existing.get("company_name") or "Unknown",
                "job_url": url,
                "requirement_id": job.get("requirement_id") or existing.get("requirement_id") or "Unknown",
                "job_description": job.get("job_description") or existing.get("job_description") or "",
                "location_work_type": job.get("location_work_type") or existing.get("location_work_type") or "Remote",
                "apply_decision": job.get("apply_decision") or existing.get("apply_decision") or default_decision,
                "strongest_label": job.get("strongest_label") or existing.get("strongest_label") or "DevOps Engineer",
                "confidence_score": clean_confidence_score(job.get("confidence_score") or existing.get("confidence_score")),
                "rationale": job.get("rationale") or existing.get("rationale") or "",
                "red_flags": red_flags or existing.get("red_flags") or [],
                "apply_decision_payload": payload or existing.get("apply_decision_payload") or {},
                "synced": bool(job.get("synced", existing.get("synced", False))),
                "synced_data": job.get("synced_data") or existing.get("synced_data") or {},
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
            jobs_to_migrate[url] = merged

    # Process SQLite databases
    sqlite_db_path = workspace_dir / "data" / "notion_job_reports.db"
    if sqlite_db_path.exists():
        print(f"Processing SQLite database: {sqlite_db_path.name}")
        try:
            conn = sqlite3.connect(str(sqlite_db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Check if table exists
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='notion_job_reports'")
            if cursor.fetchone():
                rows = cursor.execute("SELECT * FROM notion_job_reports").fetchall()
                print(f"Found {len(rows)} synced reports in SQLite mirror.")
                for row in rows:
                    url = row["job_url"]
                    if not url:
                        continue
                        
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
                            
                    existing = jobs_to_migrate.get(url, {})
                    
                    merged = {
                        "user_id": user_id,
                        "job_title": row["job_title"] or existing.get("job_title") or "Unknown Title",
                        "company_name": row["company_name"] or existing.get("company_name") or "Unknown",
                        "job_url": url,
                        "requirement_id": row["requirement_id"] or existing.get("requirement_id") or "Unknown",
                        "job_description": row["job_description"] or existing.get("job_description") or "",
                        "location_work_type": row["location_work_type"] or existing.get("location_work_type") or "Remote",
                        "apply_decision": row["apply_decision"] or existing.get("apply_decision") or "APPLY",
                        "strongest_label": row["strongest_label"] or existing.get("strongest_label") or "DevOps Engineer",
                        "confidence_score": clean_confidence_score(row["confidence_score"] or existing.get("confidence_score")),
                        "rationale": row["rationale"] or existing.get("rationale") or "",
                        "red_flags": red_flags or existing.get("red_flags") or [],
                        "apply_decision_payload": payload or existing.get("apply_decision_payload") or {},
                        "synced": True,
                        "synced_data": {
                            "page_id": row["notion_page_id"],
                            "synced_at": row["synced_at"]
                        },
                        "scraped_at": row["date_added"] or existing.get("scraped_at") or datetime.utcnow().isoformat(),
                        "stale": bool(row["archived"]) or existing.get("stale", False), # fallback stale check
                        "archived": bool(row["archived"]) or existing.get("archived", False),
                        "pipeline_stage": row["pipeline_stage"] or existing.get("pipeline_stage") or "Approved",
                        "min_salary": row["min_salary"] if row["min_salary"] is not None else existing.get("min_salary"),
                        "max_salary": row["max_salary"] if row["max_salary"] is not None else existing.get("max_salary"),
                        "is_hourly": bool(row["is_hourly"]) or existing.get("is_hourly", False),
                        "salary_text": row["salary_text"] or existing.get("salary_text"),
                        "benefits": existing.get("benefits") or []
                    }
                    jobs_to_migrate[url] = merged
            conn.close()
        except Exception as e:
            print(f"SQLite reading error: {e}")

    job_list = list(jobs_to_migrate.values())
    total_jobs = len(job_list)
    print(f"Aggregated {total_jobs} unique jobs to migrate.")

    if total_jobs == 0:
        print("No jobs found to migrate. Exiting.")
        return

    # Bulk insert to Supabase
    print("Uploading jobs to Supabase...")
    batch_size = 50
    success_count = 0
    
    for i in range(0, total_jobs, batch_size):
        batch = job_list[i:i+batch_size]
        try:
            # We use upsert so that re-runs are safe and don't create duplicates
            # By default unique_user_job_url (user_id, job_url) is unique constraint in schema.sql
            res = supabase.table("jobs").upsert(batch, on_conflict="user_id,job_url").execute()
            success_count += len(batch)
            print(f"Uploaded batch {i // batch_size + 1}: {success_count}/{total_jobs} complete.")
        except Exception as e:
            print(f"Failed to upload batch {i // batch_size + 1}: {e}")
            # Try uploading individually in case of a single bad row
            print("Attempting to insert batch records individually...")
            for record in batch:
                try:
                    supabase.table("jobs").upsert(record, on_conflict="user_id,job_url").execute()
                    success_count += 1
                except Exception as ex:
                    print(f"Failed to upload job {record.get('job_url')}: {ex}")

    print(f"\nMigration completed successfully! Scraped, cleaned, and migrated {success_count}/{total_jobs} jobs to Supabase.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate local job files and sqlite mirror to Supabase.")
    parser.add_argument("--user-id", required=True, help="UUID of the Supabase auth user to assign the migrated records to.")
    args = parser.parse_args()
    
    migrate(args.user_id)
