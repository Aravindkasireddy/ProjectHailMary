"""Regression tests for the 2026-06-27 is_target_job() fix: "Platform
Engineer" (the common real-world title form) must match the "Platform
Engineering" entry in config.json's target_titles. Before the fix, the
all-tokens substring check required "engineering" to literally appear in
the job title, which "Platform Engineer" never satisfies (different
suffix) - silently dropping these jobs at the discovery stage, before they
ever reached the classifier.
"""
import find_and_scrape_jobs as f

TARGET_TITLES = [
    "DevOps Engineer",
    "Cloud Automation Engineer",
    "Platform Engineering",
    "Cloud Infrastructure Engineer",
    "DevSecOps",
    "Site Reliability Engineer (SRE)",
    "Continuous Integration (CI/CD)",
    "System Engineer",
]


def test_platform_engineer_titles_now_match():
    for title in [
        "Platform Engineer",
        "Senior Platform Engineer",
        "Platform Engineer - Infrastructure",
        "DevOps Platform Engineer",
        "Platform Reliability Engineer",
        "Internal Developer Platform Engineer",
    ]:
        assert f.is_target_job(title, TARGET_TITLES), f"{title!r} should match Platform Engineering"


def test_platform_engineering_title_still_matches():
    assert f.is_target_job("Platform Engineering Lead", TARGET_TITLES)


def test_existing_target_titles_unaffected():
    for title in [
        "DevOps Engineer",
        "Site Reliability Engineer",
        "Cloud Infrastructure Engineer",
        "DevSecOps Engineer",
        "Cloud Automation Engineer",
        "System Engineer",
    ]:
        assert f.is_target_job(title, TARGET_TITLES), f"{title!r} should still match"


def test_unrelated_titles_still_rejected():
    for title in ["Marketing Coordinator", "Financial Analyst", "Database Engineer"]:
        assert not f.is_target_job(title, TARGET_TITLES), f"{title!r} should still be rejected"


def test_stem_engineering_only_affects_engineering_suffix():
    assert f._stem_engineering("platform engineering") == "platform engineer"
    assert f._stem_engineering("devops engineer") == "devops engineer"
    assert f._stem_engineering("software engineering manager") == "software engineer manager"


def test_ci_cd_slash_title_now_matches():
    # Real bug, 2026-06-30: "CI/CD Engineer" failed to match the target
    # title "Continuous Integration (CI/CD)" because the "/" split the
    # acronym into two separate \b[a-z]+\b tokens ("ci", "cd"), so the
    # fused acronym "cicd" never appeared in the word list the acronym
    # check searched.
    for title in ("CI/CD Engineer", "CI/CD Pipeline Engineer", "Senior CI/CD Engineer", "CICD Engineer"):
        assert f.is_target_job(title, TARGET_TITLES), title
