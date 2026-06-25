"""Tests for watched_companies_scheduler._fire_instant_alerts_for_opt_friendly_company().

Part of wiring fast-poll + instant alerts for the 307 verified OPT-friendly
companies (scripts/probe_opt_friendly_ats.py): a new job from one of these
companies should trigger an immediate per-job webhook alert instead of
waiting for the next daily digest.
"""
from datetime import datetime, timezone

import watched_companies_scheduler as wcs


class _FakeTable:
    def __init__(self, jobs):
        self._jobs = jobs
        self._filters = {}

    def select(self, *_a, **_k):
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def gte(self, *_a, **_k):
        return self

    def execute(self):
        matching = [
            j for j in self._jobs
            if all(j.get(k) == v for k, v in self._filters.items())
        ]
        return type("R", (), {"data": matching})()


class _FakeSupabase:
    def __init__(self, jobs):
        self._jobs = jobs

    def table(self, name):
        assert name == "jobs"
        return _FakeTable(self._jobs)


def test_fires_one_alert_per_new_job(monkeypatch):
    jobs = [
        {"job_url": "https://x.com/1", "company_name": "Acme Corp", "user_id": "u1", "apply_decision": "APPLY"},
        {"job_url": "https://x.com/2", "company_name": "Acme Corp", "user_id": "u1", "apply_decision": "APPLY"},
    ]
    monkeypatch.setattr("supabase_client.get_supabase_client", lambda: _FakeSupabase(jobs))

    sent = []
    import dashboard_server as ds
    monkeypatch.setattr(ds, "send_webhook_alert", lambda job, email=None: sent.append(job["job_url"]))

    row = {"company_name": "Acme Corp"}
    wcs._fire_instant_alerts_for_opt_friendly_company(row, "u1", "user@example.com", datetime.now(timezone.utc))

    assert sorted(sent) == ["https://x.com/1", "https://x.com/2"]


def test_no_jobs_found_sends_nothing(monkeypatch):
    monkeypatch.setattr("supabase_client.get_supabase_client", lambda: _FakeSupabase([]))

    sent = []
    import dashboard_server as ds
    monkeypatch.setattr(ds, "send_webhook_alert", lambda job, email=None: sent.append(job))

    row = {"company_name": "Acme Corp"}
    wcs._fire_instant_alerts_for_opt_friendly_company(row, "u1", "user@example.com", datetime.now(timezone.utc))

    assert sent == []


def test_supabase_failure_does_not_raise(monkeypatch):
    def boom():
        raise Exception("connection error")

    monkeypatch.setattr("supabase_client.get_supabase_client", boom)
    row = {"company_name": "Acme Corp"}
    # Should not raise.
    wcs._fire_instant_alerts_for_opt_friendly_company(row, "u1", "user@example.com", datetime.now(timezone.utc))
