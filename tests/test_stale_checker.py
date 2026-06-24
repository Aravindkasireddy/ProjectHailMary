"""Tests for stale_checker.stale_check_worker()'s Supabase write path.

Real incident (2026-06-24): stale_check_worker() only ever read/wrote the
local approved_jobs.json file. Supabase public.jobs is the sole job-data
store the dashboard UI reads from, so those writes never reached it -
confirmed live, 0 of 2777 Supabase rows had ever been flagged stale despite
the feature existing in code for a while. Fixed by also updating Supabase
per job when a user_id is passed in (same as the existing single-job
check-live endpoint), and by auto-triggering the worker after every scrape
run instead of leaving it manual-button-only.
"""
import json

import pytest

import stale_checker


class _FakeTable:
    def __init__(self, calls):
        self._calls = calls
        self._filters = {}

    def update(self, payload):
        self._payload = payload
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def execute(self):
        self._calls.append({"payload": self._payload, "filters": dict(self._filters)})
        return self


class _FakeSupabase:
    def __init__(self, calls):
        self._calls = calls

    def table(self, name):
        assert name == "jobs"
        return _FakeTable(self._calls)


@pytest.fixture
def approved_jobs_file(tmp_path, monkeypatch):
    import dashboard_server as ds

    approved_path = tmp_path / "approved_jobs.json"
    jobs = [
        {"job_url": "https://boards.greenhouse.io/acme/jobs/1", "job_title": "DevOps Engineer"},
        {"job_url": "https://boards.greenhouse.io/acme/jobs/2", "job_title": "SRE"},
    ]
    approved_path.write_text(json.dumps(jobs))
    monkeypatch.setattr(ds, "resolve_path", lambda base, email=None: str(approved_path))
    return approved_path


def test_stale_check_worker_writes_to_supabase_when_user_id_given(approved_jobs_file, monkeypatch):
    calls = []
    monkeypatch.setattr(stale_checker, "check_url_stale", lambda url: False)
    monkeypatch.setattr("time.sleep", lambda *_: None)

    import supabase_client

    monkeypatch.setattr(supabase_client, "get_supabase_client", lambda: _FakeSupabase(calls))

    stale_checker.stale_check_worker(email="user@example.com", user_id="u-123")

    assert len(calls) == 2
    for call in calls:
        assert call["payload"] == {"stale": False}
        assert call["filters"]["user_id"] == "u-123"

    updated = json.loads(approved_jobs_file.read_text())
    assert all(j["stale"] is False for j in updated)


def test_stale_check_worker_skips_supabase_without_user_id(approved_jobs_file, monkeypatch):
    monkeypatch.setattr(stale_checker, "check_url_stale", lambda url: False)
    monkeypatch.setattr("time.sleep", lambda *_: None)

    # No supabase_client patch needed - if the worker tried to call it without
    # a user_id, this would fail since get_supabase_client requires real env.
    stale_checker.stale_check_worker(email="user@example.com", user_id=None)

    updated = json.loads(approved_jobs_file.read_text())
    assert all(j["stale"] is False for j in updated)
