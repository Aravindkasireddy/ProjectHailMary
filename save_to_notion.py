import os
import sys
import json
import requests
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

if not NOTION_TOKEN or not DATABASE_ID:
    print("Error: NOTION_TOKEN or NOTION_DATABASE_ID not found in environment.")
    sys.exit(1)

headers = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def clean_text_for_notion(text, limit=2000):
    """Truncate text to fit Notion's single rich text block limit."""
    if not text:
        return ""
    if len(text) > limit:
        return text[:limit-3] + "..."
    return text

def build_notion_properties(job):
    # Standard properties dictionary
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
            "number": float(job.get("confidence_score", 0)) / 100.0 if float(job.get("confidence_score", 0)) > 1.0 else float(job.get("confidence_score", 0))
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

    # Format Red Flags property
    # If the database has it as Multi-select, we map each flag. If it's empty, we send an empty list.
    red_flags = job.get("red_flags", [])
    if isinstance(red_flags, str):
        red_flags = [red_flags] if red_flags else []
    
    # We will format it as a multi-select, trimming flag name to 100 chars to avoid API failures
    props["Red Flags"] = {
        "multi_select": [{"name": flag[:100]} for flag in red_flags if flag]
    }

    return props

def build_page_children(job_description):
    """Chunk the job description into paragraph blocks for the page body."""
    children = []
    if not job_description:
        return children

    # Split job description by lines or paragraphs
    paragraphs = job_description.split("\n")
    current_block = ""
    
    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
        # Notion paragraph blocks have a limit of 2000 characters
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
        
    return children[:100]  # Notion limit is 100 children per page creation request

def check_job_exists(job):
    """Check if the job already exists in the Notion database by URL or Req ID."""
    db_url = f"https://api.notion.com/v1/databases/{DATABASE_ID}/query"
    
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

def save_job_to_notion(job):
    # Check duplicate first
    exists, page_id = check_job_exists(job)
    if exists:
        print(f"Job '{job.get('job_title')}' at '{job.get('company_name')}' already exists in Notion (Page ID: {page_id}). Skipping.")
        try:
            from notion_sqlite_mirror import upsert_notion_job_report

            upsert_notion_job_report(
                job,
                page_id,
                DATABASE_ID,
                was_duplicate=True,
                workspace=ROOT,
            )
        except Exception as e:
            print(f"SQLite mirror warning: {e}")
        return True

    url = "https://api.notion.com/v1/pages"
    
    properties = build_notion_properties(job)
    children = build_page_children(job.get("job_description", ""))
    
    payload = {
        "parent": {"database_id": DATABASE_ID},
        "properties": properties,
        "children": children
    }
    
    response = requests.post(url, headers=headers, json=payload)
    if response.status_code == 200:
        print(f"Successfully saved '{job.get('job_title')}' at '{job.get('company_name')}' to Notion.")
        try:
            from notion_sqlite_mirror import upsert_notion_job_report

            page_id = response.json().get("id")
            if page_id:
                upsert_notion_job_report(
                    job, page_id, DATABASE_ID, was_duplicate=False, workspace=ROOT
                )
        except Exception as e:
            print(f"SQLite mirror warning: {e}")
        return True
    else:
        # If it failed because of select/multi_select property type mismatches,
        # try falling back to rich_text/text for select properties
        print(f"Warning: Failed to save with select properties (Status {response.status_code}): {response.text}")
        print("Retrying with fallback text properties...")
        
        # Fallback formatting: replace select/multi-select with rich_text
        properties["Apply Decision"] = {
            "rich_text": [{"text": {"content": job.get("apply_decision", "APPLY")}}]
        }
        properties["Strongest Label"] = {
            "rich_text": [{"text": {"content": job.get("strongest_label", "OutOfScope")}}]
        }
        properties["Red Flags"] = {
            "rich_text": [{"text": {"content": ", ".join(job.get("red_flags", []))}}]
        }
        
        payload["properties"] = properties
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code == 200:
            print(f"Successfully saved '{job.get('job_title')}' (using text fallback) to Notion.")
            try:
                from notion_sqlite_mirror import upsert_notion_job_report

                page_id = response.json().get("id")
                if page_id:
                    upsert_notion_job_report(
                        job, page_id, DATABASE_ID, was_duplicate=False, workspace=ROOT
                    )
            except Exception as e:
                print(f"SQLite mirror warning: {e}")
            return True
        else:
            print(f"Error: Failed to save to Notion (Status {response.status_code}): {response.text}")
            return False

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 save_to_notion.py <jobs_json_file>")
        sys.exit(1)
        
    json_file = sys.argv[1]
    if not os.path.exists(json_file):
        print(f"Error: File '{json_file}' not found.")
        sys.exit(1)
        
    with open(json_file, 'r') as f:
        jobs = json.load(f)
        
    if not isinstance(jobs, list):
        jobs = [jobs]
        
    success_count = 0
    for job in jobs:
        if save_job_to_notion(job):
            success_count += 1
            
    print(f"\nDone. Successfully saved {success_count}/{len(jobs)} jobs to Notion.")

if __name__ == '__main__':
    main()
