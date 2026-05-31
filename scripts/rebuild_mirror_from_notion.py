import os
import sys
import json
import sqlite3
import requests
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

# Set up paths and load environment variables
SCRIPTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS_DIR.parent
sys.path.insert(0, str(REPO_ROOT))

from jobsearch_paths import workspace_root
from notion_sqlite_mirror import upsert_notion_job_report, ensure_notion_mirror_schema, db_path

WORKSPACE = workspace_root()
load_dotenv(WORKSPACE / ".env")

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

if not NOTION_TOKEN or not DATABASE_ID:
    print("Error: NOTION_TOKEN or NOTION_DATABASE_ID not found in .env file.")
    sys.exit(1)

headers = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def get_text(prop):
    if not prop:
        return ""
    ptype = prop.get("type")
    if ptype in ["rich_text", "title"]:
        elements = prop.get(ptype) or []
        return "".join(e.get("text", {}).get("content", "") for e in elements).strip()
    return ""

def get_select(prop):
    if not prop:
        return None
    sel = prop.get("select")
    if sel:
        return sel.get("name")
    # Fallback to rich_text if it was saved as text
    if prop.get("type") == "rich_text":
        return get_text(prop)
    return None

def get_multi_select(prop):
    if not prop:
        return []
    ptype = prop.get("type")
    if ptype == "multi_select":
        ms = prop.get("multi_select") or []
        return [item.get("name") for item in ms if item.get("name")]
    if ptype == "rich_text":
        val = get_text(prop)
        return [f.strip() for f in val.split(",") if f.strip()]
    return []

def main():
    print(f"Connecting to Notion Database ID: {DATABASE_ID}...")
    url = f"https://api.notion.com/v1/databases/{DATABASE_ID}/query"
    
    synced_jobs = {}
    total_fetched = 0
    has_more = True
    start_cursor = None
    
    # Initialize the local database mirror schema
    ensure_notion_mirror_schema(WORKSPACE)
    
    while has_more:
        payload = {}
        if start_cursor:
            payload["start_cursor"] = start_cursor
            
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        if response.status_code != 200:
            print(f"Error querying Notion API (Status {response.status_code}): {response.text}")
            sys.exit(1)
            
        data = response.json()
        results = data.get("results", [])
        total_fetched += len(results)
        print(f"Fetched {len(results)} pages (Total fetched: {total_fetched})...")
        
        for page in results:
            page_id = page.get("id")
            props = page.get("properties", {})
            
            job_url = props.get("Job URL", {}).get("url")
            if not job_url:
                continue
                
            # Extract attributes from Notion properties
            job_title = get_text(props.get("Job Title"))
            company_name = get_text(props.get("Company Name"))
            location = get_text(props.get("Location + Work Type")) or "Remote"
            requirement_id = get_text(props.get("Requirement ID")) or "Unknown"
            job_description = get_text(props.get("Job Description"))
            apply_decision = get_select(props.get("Apply Decision")) or "APPLY"
            strongest_label = get_text(props.get("Strongest Label")) or "DevOps Engineer"
            confidence = props.get("Confidence Score", {}).get("number")
            rationale = get_text(props.get("Rationale"))
            red_flags = get_multi_select(props.get("Red Flags"))
            pipeline_stage = get_select(props.get("Pipeline Stage")) or "Approved"
            
            # Reconstruct apply decision payload if possible
            payload_str = get_text(props.get("Apply Decision Payload"))
            payload_json = {}
            if payload_str:
                try:
                    payload_json = json.loads(payload_str)
                except Exception:
                    pass
            
            # Reconstruct job dict
            job = {
                "job_title": job_title,
                "company_name": company_name,
                "job_url": job_url,
                "requirement_id": requirement_id,
                "job_description": job_description,
                "location_work_type": location,
                "apply_decision": apply_decision,
                "strongest_label": strongest_label,
                "confidence_score": (confidence * 100.0) if (confidence is not None and confidence <= 1.0) else (confidence or 100.0),
                "rationale": rationale,
                "red_flags": red_flags,
                "apply_decision_payload": payload_json,
                "pipeline_stage": pipeline_stage,
                "min_salary": props.get("Min Salary", {}).get("number"),
                "max_salary": props.get("Max Salary", {}).get("number"),
                "is_hourly": bool(props.get("Is Hourly", {}).get("checkbox")),
                "salary_text": get_text(props.get("Salary Text"))
            }
            
            # Reconstruct sync time from page metadata
            last_edited = page.get("last_edited_time") or datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
            
            # Rebuild synced_jobs map
            synced_jobs[job_url] = {
                "page_id": page_id,
                "synced_at": last_edited
            }
            
            # Upsert into SQLite mirror
            try:
                upsert_notion_job_report(
                    job,
                    page_id,
                    DATABASE_ID,
                    was_duplicate=False,
                    workspace=WORKSPACE
                )
            except Exception as e:
                print(f"Warning: Failed to insert job to SQLite mirror: {e}")
                
        has_more = data.get("has_more", False)
        start_cursor = data.get("next_cursor")
        
    # Write the synced_jobs.json mapping file
    synced_path = WORKSPACE / "synced_jobs.json"
    with open(synced_path, "w", encoding="utf-8") as f:
        json.dump(synced_jobs, f, indent=2)
        
    print("\nRebuild complete!")
    print(f"Successfully reconstructed {len(synced_jobs)} records into:")
    print(f"  - SQLite Mirror: {db_path(WORKSPACE)}")
    print(f"  - Synced Mapping: {synced_path}")

if __name__ == '__main__':
    main()
