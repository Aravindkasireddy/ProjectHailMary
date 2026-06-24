"""Tests for sponsorship_classifier.classify_sponsorship().

Goal (per user): detect H1B Sponsor / OPT Friendly / Future Sponsorship
Available / US Citizen Only / Green Card Only / Clearance Required, with a
confidence score, so international students can filter on this directly
instead of reading every JD by hand.
"""
from sponsorship_classifier import (
    STATUS_CLEARANCE_REQUIRED,
    STATUS_FUTURE_SPONSORSHIP_AVAILABLE,
    STATUS_GREEN_CARD_ONLY,
    STATUS_H1B_SPONSOR,
    STATUS_OPT_FRIENDLY,
    STATUS_REQUIRES_SPONSORSHIP,
    STATUS_US_CITIZEN_ONLY,
    STATUS_UNKNOWN,
    classify_sponsorship,
)


def test_clearance_required_outranks_everything():
    job = {
        "job_title": "DevOps Engineer",
        "job_description": "Active security clearance (TS/SCI) required. We are OPT friendly otherwise.",
    }
    result = classify_sponsorship(job)
    assert result["sponsorship_status"] == STATUS_CLEARANCE_REQUIRED
    assert result["confidence_score"] >= 80


def test_us_citizen_only():
    job = {"job_title": "DevOps Engineer", "job_description": "Must be a US citizen due to federal contract."}
    result = classify_sponsorship(job)
    assert result["sponsorship_status"] == STATUS_US_CITIZEN_ONLY


def test_green_card_only():
    job = {"job_title": "DevOps Engineer", "job_description": "Green card holders only need apply."}
    result = classify_sponsorship(job)
    assert result["sponsorship_status"] == STATUS_GREEN_CARD_ONLY


def test_no_sponsorship_language():
    job = {"job_title": "DevOps Engineer", "job_description": "We are unable to sponsor visas now or in the future."}
    result = classify_sponsorship(job)
    assert result["sponsorship_status"] == STATUS_REQUIRES_SPONSORSHIP


def test_future_sponsorship_available():
    job = {"job_title": "DevOps Engineer", "job_description": "We are open to sponsoring a visa after one year."}
    result = classify_sponsorship(job)
    assert result["sponsorship_status"] == STATUS_FUTURE_SPONSORSHIP_AVAILABLE


def test_opt_friendly_text_signal():
    job = {"job_title": "DevOps Engineer", "job_description": "This role is OPT friendly, F-1 visa welcome."}
    result = classify_sponsorship(job)
    assert result["sponsorship_status"] == STATUS_OPT_FRIENDLY
    assert result["confidence_score"] >= 80


def test_known_h1b_sponsor_company_with_no_text_signal():
    job = {"job_title": "DevOps Engineer", "job_description": "Build CI/CD pipelines.", "company_name": "Acme Corp"}
    sponsors_cleaned = {"acme": {"opt_friendly_score": 70}}
    result = classify_sponsorship(job, sponsors_cleaned)
    # opt_friendly_score >= 60 -> classified opt_friendly, not just h1b_sponsor
    assert result["sponsorship_status"] == STATUS_OPT_FRIENDLY


def test_known_h1b_sponsor_low_opt_score_falls_back_to_h1b_sponsor():
    job = {"job_title": "DevOps Engineer", "job_description": "Build CI/CD pipelines.", "company_name": "Acme Corp"}
    sponsors_cleaned = {"acme": {"opt_friendly_score": 20}}
    result = classify_sponsorship(job, sponsors_cleaned)
    assert result["sponsorship_status"] == STATUS_H1B_SPONSOR


def test_unknown_company_no_signal():
    job = {"job_title": "DevOps Engineer", "job_description": "Build CI/CD pipelines.", "company_name": "Unknown Startup LLC"}
    result = classify_sponsorship(job, sponsors_cleaned={})
    assert result["sponsorship_status"] == STATUS_UNKNOWN
    assert result["confidence_score"] < 50
