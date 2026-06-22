"""Notion property building and job-sync helpers.

Extracted verbatim from dashboard_server.py. These are distinct from the
standalone script save_to_notion.py at the repo root (which has different
function signatures, e.g. build_notion_properties(job) without db_properties,
and is invoked as a CLI script rather than imported) -- kept separate here to
avoid changing save_to_notion.py's behavior.

_mirror_notion_row_to_sqlite depends on WORKSPACE_DIR, which still lives in
dashboard_server.py as the single source of truth; imported lazily to avoid
a circular import.
"""
import json
from datetime import datetime

import requests

from notion_sqlite_mirror import upsert_notion_job_report


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
    import dashboard_server as ds

    try:
        upsert_notion_job_report(
            job,
            page_id,
            database_id,
            was_duplicate=was_duplicate,
            workspace=ds.WORKSPACE_DIR,
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
