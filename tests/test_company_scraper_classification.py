"""Tests for company_scraper's classification safety net.

Real incident (2026-06-23): company_scraper/publisher.py never ran any
classifier before upserting to Supabase - it defaulted every row missing
apply_decision/strongest_label to APPLY/"DevOps Engineer"/100% confidence.
Since main.py's IT-relevance filter (passes_it_job) is a loose title/dept
heuristic, not the real MAAS classifier, this meant every company-scraped
job that merely sounded IT-adjacent got auto-approved as DevOps Engineer
regardless of actual content. Confirmed live: "Perception Software Engineer
- ADAS" and "Sr. Process Engineer, Body in White" both landed in the
Approved feed this way. main.py now runs classify_job_dynamically() on every
company-scraped job before publishing; publisher.py's own fallback defaults
were also hardened to "don't know" (OutOfScope/DO_NOT_APPLY) instead of an
unconditional auto-approve, in case classification is ever skipped again.
"""
from company_scraper.publisher import _row


def test_row_with_no_classification_fields_defaults_to_out_of_scope():
    job = {
        "job_title": "Perception Software Engineer - ADAS",
        "company_name": "Acme Motors",
        "job_url": "https://example.com/job/123",
        "job_description": "",
    }
    row = _row(job, user_id="u1", ats_platform="greenhouse")
    assert row["strongest_label"] == "OutOfScope"
    assert row["apply_decision"] == "DO_NOT_APPLY"
    assert row["red_flags"] == ["Not classified"]


def test_row_with_real_classification_fields_is_passed_through():
    job = {
        "job_title": "DevOps Engineer",
        "company_name": "Acme Corp",
        "job_url": "https://example.com/job/456",
        "job_description": "",
        "apply_decision": "APPLY",
        "strongest_label": "DevOps Engineer",
        "confidence_score": 85,
        "red_flags": [],
        "rationale": "This job was dynamically classified as DevOps Engineer using rule-based keyword signals.",
    }
    row = _row(job, user_id="u1", ats_platform="greenhouse")
    assert row["strongest_label"] == "DevOps Engineer"
    assert row["apply_decision"] == "APPLY"
    assert row["confidence_score"] == 85
    assert row["red_flags"] == []
