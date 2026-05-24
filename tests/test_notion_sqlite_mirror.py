import sqlite3

from notion_sqlite_mirror import db_path, upsert_notion_job_report


def test_upsert_notion_job_report_roundtrip(tmp_path):
    job = {
        "job_url": "https://example.com/job/1",
        "requirement_id": "REQ-1",
        "job_title": "DevOps Engineer",
        "company_name": "Acme",
        "location_work_type": "Remote",
        "job_description": "Long JD text",
        "apply_decision": "APPLY",
        "strongest_label": "DevOps Engineer",
        "confidence_score": 95,
        "rationale": "Good fit",
        "apply_decision_payload": {"a": 1},
        "red_flags": [],
    }
    upsert_notion_job_report(
        job, "page-uuid-1", "db-uuid-2", was_duplicate=False, workspace=tmp_path
    )
    upsert_notion_job_report(
        job, "page-uuid-updated", "db-uuid-2", was_duplicate=True, workspace=tmp_path
    )

    path = db_path(tmp_path)
    con = sqlite3.connect(path)
    cur = con.execute(
        "SELECT notion_page_id, was_duplicate FROM notion_job_reports WHERE job_url = ?",
        (job["job_url"],),
    )
    row = cur.fetchone()
    con.close()
    assert row[0] == "page-uuid-updated"
    assert row[1] == 1
