"""Regression test for the "Unreviewed defaults to APPLY" bug (2026-06-25).

Real incident: classify_and_save.py only ever writes the approved subset of
jobs back out (to approved_jobs.json) - a job it rejects is silently
dropped, never written anywhere, and active_candidate_jobs.json (Stage 2's
raw output) is never updated in place. upload_user_jobs() used to default
those never-finally-classified records to apply_decision="APPLY" and
strongest_label="DevOps Engineer" when uploading to Supabase - confirmed
live, 18 jobs in production had pipeline_stage="Unreviewed",
apply_decision="APPLY", strongest_label="DevOps Engineer" with titles like
"Cloud Security Engineer" and "Senior Database Engineer" (both retired role
families that should be OutOfScope/DO_NOT_APPLY). This put real rejects
into the live Approved feed. Fixed: unclassified active-candidate records
now default to DO_NOT_APPLY/OutOfScope/"Rejected" instead.
"""
import json

import pytest

import supabase_client


class _FakeTable:
    def __init__(self, upserted):
        self._upserted = upserted

    def upsert(self, batch, on_conflict=None):
        self._upserted.extend(batch)
        return self

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def not_(self):
        return self

    def is_(self, *_a, **_k):
        return self

    def in_(self, *_a, **_k):
        return self

    def execute(self):
        return type("R", (), {"data": []})()


class _FakeSupabase:
    def __init__(self):
        self.upserted = []

    def table(self, name):
        assert name == "jobs"
        return _FakeTable(self.upserted)


@pytest.fixture
def fake_pipeline_files(tmp_path, monkeypatch):
    suffix = "test_example.com"
    active_path = tmp_path / f"active_candidate_jobs_{suffix}.json"
    active_path.write_text(json.dumps([
        {
            "job_url": "https://boards.greenhouse.io/acme/jobs/1",
            "job_title": "Cloud Security Engineer",
            "company_name": "Acme Corp",
            "job_description": "",
            "location_work_type": "Remote",
            # No apply_decision/strongest_label - classify_and_save.py never
            # finished classifying this one (it rejected it and dropped it).
        }
    ]))

    monkeypatch.setattr(supabase_client, "workspace_root", lambda: tmp_path)
    monkeypatch.setattr(
        supabase_client, "get_supabase_client", lambda: _FakeSupabase()
    )
    monkeypatch.setattr(
        "embeddings.get_embeddings_batch", lambda descs: [None] * len(descs)
    )
    return suffix


def test_unclassified_active_candidate_defaults_to_rejected(fake_pipeline_files, monkeypatch):
    fake_sb = _FakeSupabase()
    monkeypatch.setattr(supabase_client, "get_supabase_client", lambda: fake_sb)

    supabase_client.upload_user_jobs("u1", "test@example.com")

    assert len(fake_sb.upserted) == 1
    row = fake_sb.upserted[0]
    assert row["apply_decision"] == "DO_NOT_APPLY"
    assert row["strongest_label"] == "OutOfScope"
    assert row["pipeline_stage"] == "Rejected"
