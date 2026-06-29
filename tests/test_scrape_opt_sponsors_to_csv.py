"""Tests for scripts/scrape_opt_sponsors_to_csv.py - the 2026-06-28
ats_platform-aware dispatch update.

Covers: specialized-connector dispatch by known ats_platform, detect_ats()
fallback when ats_platform is null/empty, and fallback-to-generic when a
specialized connector raises (never crashes the run).
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import scrape_opt_sponsors_to_csv as m


def test_known_workday_ats_dispatches_to_workday_not_generic(monkeypatch):
    calls = {"workday": 0, "generic": 0}
    monkeypatch.setattr(m.workday, "fetch_jobs", lambda url, hint: (calls.__setitem__("workday", calls["workday"] + 1), [{"job_title": "DevOps Engineer", "job_url": "u"}])[1])
    monkeypatch.setattr(m.generic, "fetch_jobs", lambda url, hint: (calls.__setitem__("generic", calls["generic"] + 1), [])[1])
    monkeypatch.setattr(m, "detect_ats", lambda url: pytest.fail("detect_ats should not be called when ats_platform is known"))

    jobs, ats_used = m.scrape_employer("https://x.myworkdayjobs.com/careers", "Acme", "workday")

    assert calls["workday"] == 1
    assert calls["generic"] == 0
    assert ats_used == "workday"
    assert jobs[0]["job_title"] == "DevOps Engineer"


def test_known_icims_ats_dispatches_to_icims_not_generic(monkeypatch):
    calls = {"icims": 0, "generic": 0}
    monkeypatch.setattr(m.icims, "fetch_jobs", lambda url, hint: (calls.__setitem__("icims", calls["icims"] + 1), [])[1])
    monkeypatch.setattr(m.generic, "fetch_jobs", lambda url, hint: (calls.__setitem__("generic", calls["generic"] + 1), [])[1])

    jobs, ats_used = m.scrape_employer("https://acme.icims.com/jobs", "Acme", "icims")

    assert calls["icims"] == 1
    assert calls["generic"] == 0
    assert ats_used == "icims"


def test_known_greenhouse_ats_dispatches_to_greenhouse(monkeypatch):
    calls = {"greenhouse": 0, "generic": 0}
    monkeypatch.setattr(m.greenhouse, "fetch_jobs", lambda url, hint: (calls.__setitem__("greenhouse", calls["greenhouse"] + 1), [])[1])
    monkeypatch.setattr(m.generic, "fetch_jobs", lambda url, hint: (calls.__setitem__("generic", calls["generic"] + 1), [])[1])

    jobs, ats_used = m.scrape_employer("https://boards.greenhouse.io/acme", "Acme", "greenhouse")

    assert calls["greenhouse"] == 1
    assert calls["generic"] == 0
    assert ats_used == "greenhouse"


def test_known_lever_ats_dispatches_to_lever(monkeypatch):
    calls = {"lever": 0, "generic": 0}
    monkeypatch.setattr(m.lever, "fetch_jobs", lambda url, hint: (calls.__setitem__("lever", calls["lever"] + 1), [])[1])
    monkeypatch.setattr(m.generic, "fetch_jobs", lambda url, hint: (calls.__setitem__("generic", calls["generic"] + 1), [])[1])

    jobs, ats_used = m.scrape_employer("https://jobs.lever.co/acme", "Acme", "lever")

    assert calls["lever"] == 1
    assert calls["generic"] == 0
    assert ats_used == "lever"


def test_null_ats_platform_falls_back_to_detect_ats(monkeypatch):
    detect_calls = []
    monkeypatch.setattr(m, "detect_ats", lambda url: detect_calls.append(url) or "workday")
    monkeypatch.setattr(m.workday, "fetch_jobs", lambda url, hint: [])

    jobs, ats_used = m.scrape_employer("https://x.myworkdayjobs.com/careers", "Acme", None)

    assert detect_calls == ["https://x.myworkdayjobs.com/careers"]
    assert ats_used == "workday"


def test_empty_string_ats_platform_falls_back_to_detect_ats(monkeypatch):
    monkeypatch.setattr(m, "detect_ats", lambda url: "generic")
    monkeypatch.setattr(m.generic, "fetch_jobs", lambda url, hint: [])

    jobs, ats_used = m.scrape_employer("https://acme.com/careers", "Acme", "")

    assert ats_used == "generic"


def test_specialized_connector_failure_falls_back_to_generic(monkeypatch):
    monkeypatch.setattr(m.workday, "fetch_jobs", lambda url, hint: (_ for _ in ()).throw(RuntimeError("404 not found")))
    monkeypatch.setattr(m.generic, "fetch_jobs", lambda url, hint: [{"job_title": "Site Reliability Engineer", "job_url": "u"}])

    jobs, ats_used = m.scrape_employer("https://x.myworkdayjobs.com/careers", "Acme", "workday")

    assert ats_used == "generic"
    assert jobs[0]["job_title"] == "Site Reliability Engineer"


def test_generic_connector_failure_returns_empty_and_logs(monkeypatch, caplog):
    monkeypatch.setattr(m.generic, "fetch_jobs", lambda url, hint: (_ for _ in ()).throw(RuntimeError("timeout")))

    import logging
    with caplog.at_level(logging.WARNING):
        jobs, ats_used = m.scrape_employer("https://acme.com/careers", "Acme", "generic")

    assert jobs == []
    assert any("Generic connector failed" in r.message for r in caplog.records)


def test_unknown_ats_platform_value_falls_through_to_generic(monkeypatch):
    """A future/unrecognized ats_platform string (not in _SPECIALIZED_CONNECTORS)
    should still route to the generic connector rather than erroring out.
    """
    calls = {"generic": 0}
    monkeypatch.setattr(m.generic, "fetch_jobs", lambda url, hint: (calls.__setitem__("generic", calls["generic"] + 1), [])[1])

    jobs, ats_used = m.scrape_employer("https://acme.com/careers", "Acme", "smartrecruiters")

    assert calls["generic"] == 1
    assert ats_used == "smartrecruiters"


def test_load_filtered_employers_skips_confirmed_dead_links(tmp_path, monkeypatch):
    excel_path = tmp_path / "sponsors.xlsx"
    df = pd.DataFrame([
        {"Employer Name": "Alive Co", "career_portal": "https://alive.example.com/careers",
         "Sponsor Status": "Strong Active Sponsor", "Top State": "CA",
         "career_portal_verified": True},
        {"Employer Name": "Dead Co", "career_portal": "https://dead.example.com/careers",
         "Sponsor Status": "Strong Active Sponsor", "Top State": "TX",
         "career_portal_verified": False},
        {"Employer Name": "Unchecked Co", "career_portal": "https://unchecked.example.com/careers",
         "Sponsor Status": "Strong Active Sponsor", "Top State": "NY",
         "career_portal_verified": pd.NA},
    ])
    df.to_excel(excel_path, index=False)
    monkeypatch.setattr(m, "EXCEL_PATH", excel_path)

    with_skip = m.load_filtered_employers(["Strong Active Sponsor"], None, None, skip_dead_links=True)
    assert set(with_skip["Employer Name"]) == {"Alive Co", "Unchecked Co"}

    without_skip = m.load_filtered_employers(["Strong Active Sponsor"], None, None, skip_dead_links=False)
    assert set(without_skip["Employer Name"]) == {"Alive Co", "Dead Co", "Unchecked Co"}
