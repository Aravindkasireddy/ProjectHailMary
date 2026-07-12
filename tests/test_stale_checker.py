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
import sys
import types

import pytest

import stale_checker


class _FakeQuery:
    def __init__(self, calls, select_rows=None):
        self._calls = calls
        self._filters = {}
        self._payload = None
        self._select_rows = select_rows
        self._is_select = False

    def select(self, *_args, **_kwargs):
        self._is_select = True
        return self

    def update(self, payload):
        self._payload = payload
        self._is_select = False
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def order(self, *_args, **_kwargs):
        return self

    def range(self, *_args, **_kwargs):
        return self

    def execute(self):
        if self._is_select:
            rows = self._select_rows if self._select_rows is not None else []
            return types.SimpleNamespace(data=list(rows))
        self._calls.append({"payload": self._payload, "filters": dict(self._filters)})
        return types.SimpleNamespace(data=[])


class _FakeSupabase:
    def __init__(self, calls, select_rows=None):
        self._calls = calls
        self._select_rows = select_rows

    def table(self, name):
        assert name == "jobs"
        return _FakeQuery(self._calls, select_rows=self._select_rows)


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
    monkeypatch.setattr(ds, "_invalidate_jobs_cache", lambda email=None: None)
    return approved_path


def _install_fake_supabase(monkeypatch, fake):
    mod = types.ModuleType("supabase_client")
    mod.get_supabase_client = lambda: fake
    monkeypatch.setitem(sys.modules, "supabase_client", mod)


def test_stale_check_worker_writes_to_supabase_when_user_id_given(approved_jobs_file, monkeypatch):
    calls = []
    monkeypatch.setattr(stale_checker, "check_url_stale", lambda url: False)
    monkeypatch.setattr("time.sleep", lambda *_: None)
    # Empty select → falls back to local JSON, then updates Supabase
    _install_fake_supabase(monkeypatch, _FakeSupabase(calls, select_rows=[]))

    stale_checker.stale_check_worker(email="user@example.com", user_id="u-123")

    assert len(calls) == 2
    for call in calls:
        assert call["payload"] == {"stale": False}
        assert call["filters"]["user_id"] == "u-123"

    updated = json.loads(approved_jobs_file.read_text())
    assert all(j["stale"] is False for j in updated)


def test_stale_check_worker_prefers_supabase_list_when_rows_exist(approved_jobs_file, monkeypatch):
    calls = []
    monkeypatch.setattr(stale_checker, "check_url_stale", lambda url: True)
    monkeypatch.setattr("time.sleep", lambda *_: None)
    rows = [
        {"id": "a1", "job_url": "https://boards.greenhouse.io/acme/jobs/99", "scraped_at": "2026-07-01T00:00:00Z"},
    ]
    _install_fake_supabase(monkeypatch, _FakeSupabase(calls, select_rows=rows))

    stale_checker.stale_check_worker(email="user@example.com", user_id="u-123")

    assert len(calls) == 1
    assert calls[0]["payload"]["stale"] is True
    assert calls[0]["filters"]["id"] == "a1"
    assert calls[0]["filters"]["user_id"] == "u-123"


def test_stale_check_worker_skips_supabase_without_user_id(approved_jobs_file, monkeypatch):
    monkeypatch.setattr(stale_checker, "check_url_stale", lambda url: False)
    monkeypatch.setattr("time.sleep", lambda *_: None)

    # No supabase_client patch needed - if the worker tried to call it without
    # a user_id, this would fail since get_supabase_client requires real env.
    stale_checker.stale_check_worker(email="user@example.com", user_id=None)

    updated = json.loads(approved_jobs_file.read_text())
    assert all(j["stale"] is False for j in updated)
