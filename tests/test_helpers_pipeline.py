"""Tests for job_identity, salary_parser, secrets_scrub (no network)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))


def test_stable_job_id_ignores_trailing_slash_and_case():
    from job_identity import stable_job_id

    a = stable_job_id("https://EXAMPLE.com/Jobs/abc/")
    b = stable_job_id("https://example.com/jobs/abc")
    assert a == b
    assert len(a) == 32


def test_enrich_job_record_sets_job_id_and_hash():
    from job_identity import enrich_job_record

    j = {"job_url": "https://greenhouse.io/x/123", "job_description": "Hello  World"}
    enrich_job_record(j)
    assert j.get("job_id")
    assert j.get("description_hash")


def test_extract_salary_fields_range():
    from salary_parser import extract_salary_fields

    j = {
        "job_title": "Engineer",
        "job_description": "We pay $90k - $110k annually for this remote role.",
    }
    out = extract_salary_fields(j)
    assert out.get("min_salary") == 90000
    assert out.get("max_salary") == 110000
    assert out.get("is_hourly") is False


def test_scrub_string_redacts_jwt_like(monkeypatch):
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    from secrets_scrub import scrub_string

    tokenish = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIn0."
        "dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
    )
    s = f"Bearer {tokenish} tail"
    out = scrub_string(s)
    assert "REDACTED_JWT" in out
    assert tokenish not in out
