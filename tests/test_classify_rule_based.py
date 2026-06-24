"""Tests for the rule-based fallback classifier (classify_job_dynamically).

Real incident (2026-06-23): when zero keyword signals matched any MAAS role
family, the function defaulted to strongest_label="DevOps Engineer" with
apply_decision=APPLY - auto-approving completely unrelated roles (Data
Scientist, Engineering Program Manager, Sustainability Analyst, ...) at high
confidence whenever Gemini/OpenAI classification failed and this fallback
ran. Confirmed live: 12+ "Data Scientist" postings in production had
strongest_label="DevOps Engineer", confidence_score=100.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from classify_and_save import classify_job_dynamically


def test_zero_signal_job_is_out_of_scope_not_devops():
    job = {
        "job_title": "Senior Staff Data Scientist, Guest & Host Marketplace AI",
        "job_description": "Build statistical models and analyze marketplace data using Python and SQL.",
        "red_flags": [],
    }
    result = classify_job_dynamically(job)
    assert result["strongest_label"] == "OutOfScope"
    assert result["apply_decision"] == "DO_NOT_APPLY"
    assert result["red_flags"]


def test_zero_signal_job_low_confidence():
    job = {"job_title": "Engineering Program Manager", "job_description": "", "red_flags": []}
    result = classify_job_dynamically(job)
    assert result["confidence_score"] < 50


def test_genuine_devops_title_still_classified_correctly():
    job = {
        "job_title": "DevOps Engineer",
        "job_description": "Manage CI/CD pipelines and Kubernetes infrastructure.",
        "red_flags": [],
    }
    result = classify_job_dynamically(job)
    assert result["strongest_label"] == "DevOps Engineer"
    assert result["apply_decision"] == "APPLY"


def test_cloud_network_and_security_titles_remain_out_of_scope():
    for title in ("Cloud Network Engineer", "Cloud Security Engineer"):
        job = {"job_title": title, "job_description": "", "red_flags": []}
        result = classify_job_dynamically(job)
        assert result["strongest_label"] == "OutOfScope", title
        assert result["apply_decision"] == "DO_NOT_APPLY", title


def test_database_engineer_titles_are_out_of_scope():
    # Real incident (2026-06-25): Database Engineer/Cloud Database Engineer/DBA
    # were documented as retired alongside Cloud Network/Security Engineer
    # (2026-06-22), but - unlike those two - never got an explicit override
    # check, so they remained scoreable/APPLY-eligible in label_scores.
    # Confirmed live: 14 jobs titled "Database Engineer", "DBA Engineer",
    # "Senior Database Engineer II", etc. were auto-approved this way.
    for title in (
        "Database Engineer",
        "DBA Engineer",
        "Senior Database Engineer",
        "Senior Database Engineer II",
        "Junior Database Engineer",
    ):
        job = {"job_title": title, "job_description": "", "red_flags": []}
        result = classify_job_dynamically(job)
        assert result["strongest_label"] == "OutOfScope", title
        assert result["apply_decision"] == "DO_NOT_APPLY", title


def test_retired_data_platform_mlops_aiops_titles_are_out_of_scope():
    # Retired 2026-06-24 alongside Database/Network/Security Engineer families.
    # Without the explicit retired-title check, a title like "AI Platform
    # Engineer (AIOps)" still matched the generic "platform" in title
    # heuristic and was misclassified as Platform Engineering / APPLY.
    for title in (
        "Data Platform Engineer",
        "MLOps Engineer",
        "AI Platform Engineer (AIOps)",
        "Machine Learning Engineer",
    ):
        job = {"job_title": title, "job_description": "", "red_flags": []}
        result = classify_job_dynamically(job)
        assert result["strongest_label"] == "OutOfScope", title
        assert result["apply_decision"] == "DO_NOT_APPLY", title


def test_genuine_platform_engineering_title_still_classified_correctly():
    job = {"job_title": "Platform Engineer", "job_description": "", "red_flags": []}
    result = classify_job_dynamically(job)
    assert result["strongest_label"] == "Platform Engineering"
    assert result["apply_decision"] == "APPLY"


def test_automotive_engineering_titles_from_company_scraper_are_out_of_scope():
    # Confirmed live 2026-06-23: company_scraper/publisher.py never called any
    # classifier at all before this fix, so these landed in the Approved feed
    # labeled "DevOps Engineer" purely from publisher.py's hardcoded default.
    for title in ("Perception Software Engineer - ADAS", "Sr. Process Engineer, Body in White"):
        job = {"job_title": title, "job_description": "", "red_flags": []}
        result = classify_job_dynamically(job)
        assert result["strongest_label"] == "OutOfScope", title
        assert result["apply_decision"] == "DO_NOT_APPLY", title
