"""Tests for supabase_client._dedupe_by_canonical_fingerprint().

This is the write-time merge that fixes "1 canonical job, N sources" instead
of N duplicate rows for the same opening reposted across ATS/sources.
"""
from supabase_client import _dedupe_by_canonical_fingerprint


class _FakeTable:
    def __init__(self, rows, updates):
        self._rows = rows
        self._updates = updates
        self._filters = {}

    def select(self, *_a, **_k):
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def in_(self, col, vals):
        self._filters[col] = set(vals)
        return self

    def execute(self):
        if hasattr(self, "_update_payload"):
            self._updates.append({"payload": self._update_payload, "filters": dict(self._filters)})
            return self
        fps = self._filters.get("canonical_fingerprint")
        data = [r for r in self._rows if fps is None or r.get("canonical_fingerprint") in fps]
        return type("R", (), {"data": data})()

    def update(self, payload):
        self._update_payload = payload
        return self


class _FakeSupabase:
    def __init__(self, rows):
        self.rows = rows
        self.updates = []

    def table(self, name):
        assert name == "jobs"
        return _FakeTable(self.rows, self.updates)


def test_two_new_reposts_in_same_batch_merge_into_one_canonical_row():
    sb = _FakeSupabase(rows=[])
    records = [
        {
            "user_id": "u1",
            "job_url": "https://acme.myworkdayjobs.com/jobs/1",
            "company_name": "Acme Corp",
            "job_title": "DevOps Engineer",
            "location_work_type": "Remote",
        },
        {
            "user_id": "u1",
            "job_url": "https://www.linkedin.com/jobs/view/2",
            "company_name": "Acme Corp",
            "job_title": "Sr. DevOps Engineer",
            "location_work_type": "Remote",
        },
    ]

    result = _dedupe_by_canonical_fingerprint(sb, "u1", records)

    assert len(result) == 1
    assert len(result[0]["sources"]) == 2
    source_urls = {s["source_url"] for s in result[0]["sources"]}
    assert source_urls == {
        "https://acme.myworkdayjobs.com/jobs/1",
        "https://www.linkedin.com/jobs/view/2",
    }


def test_repost_of_an_already_stored_job_merges_into_existing_row_not_a_new_one():
    existing_fp = None
    from job_fingerprint import canonical_fingerprint

    existing_job = {
        "company_name": "Acme Corp",
        "job_title": "DevOps Engineer",
        "location_work_type": "Remote",
    }
    existing_fp = canonical_fingerprint(existing_job)

    sb = _FakeSupabase(
        rows=[
            {
                "job_url": "https://acme.myworkdayjobs.com/jobs/1",
                "canonical_fingerprint": existing_fp,
                "sources": [
                    {"ats_source": "workday", "source_url": "https://acme.myworkdayjobs.com/jobs/1", "scraped_at": ""}
                ],
            }
        ]
    )

    new_repost = {
        "user_id": "u1",
        "job_url": "https://www.linkedin.com/jobs/view/2",
        "company_name": "Acme Corp",
        "job_title": "DevOps Engineer",
        "location_work_type": "Remote",
    }

    result = _dedupe_by_canonical_fingerprint(sb, "u1", [new_repost])

    # The repost should NOT become a new row to upsert.
    assert result == []
    # It should instead show up as an update appending it as a source on the
    # existing canonical row.
    assert len(sb.updates) == 1
    new_urls = {s["source_url"] for s in sb.updates[0]["payload"]["sources"]}
    assert new_urls == {
        "https://acme.myworkdayjobs.com/jobs/1",
        "https://www.linkedin.com/jobs/view/2",
    }


def test_degrades_gracefully_when_schema_not_migrated():
    class _BrokenTable:
        def select(self, *_a, **_k):
            return self

        def eq(self, *_a, **_k):
            return self

        def in_(self, *_a, **_k):
            return self

        def execute(self):
            raise Exception("column canonical_fingerprint does not exist")

    class _BrokenSupabase:
        def table(self, _name):
            return _BrokenTable()

    records = [
        {
            "user_id": "u1",
            "job_url": "https://acme.myworkdayjobs.com/jobs/1",
            "company_name": "Acme Corp",
            "job_title": "DevOps Engineer",
            "location_work_type": "Remote",
        }
    ]
    result = _dedupe_by_canonical_fingerprint(_BrokenSupabase(), "u1", records)
    assert result == records
