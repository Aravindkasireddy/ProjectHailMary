"""Tests for the connectors/ ATS connector framework.

Verifies the standard discover_jobs/extract_job/normalize_job contract,
using GreenhouseConnector as the representative case (LeverConnector and
WorkdayConnector share the exact same BaseConnector wiring, just pointing at
a different company_scraper.scrapers module).
"""
from connectors.greenhouse import GreenhouseConnector
from connectors.registry import get_connector


def test_connector_discover_extract_normalize_pipeline(monkeypatch):
    raw_jobs = [
        {
            "job_url": "https://boards.greenhouse.io/acme/jobs/1",
            "job_title": "Senior DevOps Engineer",
            "company_name": "Acme Inc.",
            "job_description": "Own CI/CD. Pay: $140,000 - $170,000 / year.",
            "location_work_type": "Austin, TX",
            "requirement_id": "1",
        }
    ]
    monkeypatch.setattr(
        "connectors.greenhouse.fetch_jobs", lambda url, hint="": raw_jobs
    )

    conn = GreenhouseConnector()
    urls = conn.discover_jobs("https://boards.greenhouse.io/acme")
    assert urls == ["https://boards.greenhouse.io/acme/jobs/1"]

    raw = conn.extract_job(urls[0])
    assert raw["job_title"] == "Senior DevOps Engineer"

    normalized = conn.normalize_job(raw)
    assert normalized["company_name"] == "Acme"
    assert normalized["location_work_type"] == "Austin, TX, USA"
    assert normalized["ats_source"] == "greenhouse"
    assert normalized["salary_min"] == 140000.0
    assert normalized["salary_max"] == 170000.0
    assert "canonical_fingerprint" in normalized and normalized["canonical_fingerprint"]


def test_extract_job_before_discover_raises():
    conn = GreenhouseConnector()
    try:
        conn.extract_job("https://boards.greenhouse.io/acme/jobs/1")
        assert False, "expected KeyError"
    except KeyError:
        pass


def test_registry_returns_correct_connector_by_ats_kind():
    assert get_connector("greenhouse").ats_source == "greenhouse"
    assert get_connector("lever").ats_source == "lever"
    assert get_connector("workday").ats_source == "workday"
    assert get_connector("icims") is None


def test_fetch_all_normalized_runs_full_pipeline(monkeypatch):
    raw_jobs = [
        {
            "job_url": "https://jobs.lever.co/acme/1",
            "job_title": "SRE",
            "company_name": "Acme LLC",
            "job_description": "On-call rotation.",
            "location_work_type": "Remote",
            "requirement_id": "1",
        }
    ]
    monkeypatch.setattr("connectors.lever.fetch_jobs", lambda url, hint="": raw_jobs)

    from connectors.lever import LeverConnector

    conn = LeverConnector()
    results = conn.fetch_all_normalized("https://jobs.lever.co/acme")
    assert len(results) == 1
    assert results[0]["company_name"] == "Acme"
    assert results[0]["location_work_type"] == "Remote"
    assert results[0]["is_remote"] is True
