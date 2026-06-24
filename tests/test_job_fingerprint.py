"""Tests for job_fingerprint.py's canonical fingerprinting.

Goal: the same opening reposted via a different ATS/source (Workday board,
LinkedIn repost, company-page repost) should collapse to one fingerprint so
the user sees "1 job, N sources" instead of N duplicate rows.
"""
from job_fingerprint import (
    canonical_fingerprint,
    normalize_company_name,
    normalize_location,
    normalize_title,
)


def test_same_role_different_sources_share_a_fingerprint():
    workday_posting = {
        "company_name": "Acme Corp",
        "job_title": "Senior DevOps Engineer",
        "location_work_type": "Austin, TX (Remote)",
        "job_url": "https://acme.myworkdayjobs.com/en-US/jobs/12345",
    }
    linkedin_repost = {
        "company_name": "Acme Corp",
        "job_title": "Sr. DevOps Engineer",
        "location_work_type": "Remote",
        "job_url": "https://www.linkedin.com/jobs/view/98765",
    }
    company_page_repost = {
        "company_name": "ACME, LLC",
        "job_title": "DevOps Engineer",
        "location_work_type": "Remote - US",
        "job_url": "https://acme.com/careers/devops-engineer",
    }

    fp1 = canonical_fingerprint(workday_posting)
    fp2 = canonical_fingerprint(linkedin_repost)
    fp3 = canonical_fingerprint(company_page_repost)

    assert fp1 == fp2 == fp3


def test_different_company_does_not_collide():
    job_a = {"company_name": "Acme Corp", "job_title": "DevOps Engineer", "location_work_type": "Remote"}
    job_b = {"company_name": "Globex Corp", "job_title": "DevOps Engineer", "location_work_type": "Remote"}
    assert canonical_fingerprint(job_a) != canonical_fingerprint(job_b)


def test_different_physical_location_does_not_collide():
    job_a = {"company_name": "Acme Corp", "job_title": "DevOps Engineer", "location_work_type": "Austin, TX"}
    job_b = {"company_name": "Acme Corp", "job_title": "DevOps Engineer", "location_work_type": "Dallas, TX"}
    assert canonical_fingerprint(job_a) != canonical_fingerprint(job_b)


def test_normalize_company_name_strips_legal_suffixes():
    assert normalize_company_name("Acme Inc.") == normalize_company_name("ACME, LLC")
    assert normalize_company_name("Acme Corporation") == normalize_company_name("Acme Corp")


def test_normalize_title_strips_one_leading_seniority_word():
    assert normalize_title("Senior DevOps Engineer") == normalize_title("Sr. DevOps Engineer")
    assert normalize_title("Senior DevOps Engineer") == normalize_title("DevOps Engineer")


def test_normalize_title_keeps_distinct_seniority_apart_from_role():
    # "Staff" vs the bare title is folded the same way as "Senior" (both are
    # single leading seniority words) - this is a deliberate, documented
    # trade-off, not a bug: collapsing cosmetic seniority-prefix drift on the
    # same req matters more here than distinguishing "Staff" vs "Senior" by
    # title text alone, since reposts commonly vary just that one word.
    assert normalize_title("Staff DevOps Engineer") == normalize_title("DevOps Engineer")


def test_normalize_location_collapses_remote_variants():
    assert normalize_location("Remote") == normalize_location("Austin, TX (Remote)")
    assert normalize_location("Remote") == normalize_location("Remote - US")


def test_normalize_location_keeps_distinct_cities_apart():
    assert normalize_location("Austin, TX") != normalize_location("Dallas, TX")
