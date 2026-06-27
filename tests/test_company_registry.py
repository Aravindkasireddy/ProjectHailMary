"""Tests for company_registry.py.

Goal: persist ATS discovery results (company -> ats_type/careers_url) so
the same company doesn't need live re-discovery (slug-guessing + Yahoo
fallback) every time any code path needs to know its ATS.
"""
from datetime import datetime, timedelta, timezone

import company_registry as reg


def test_is_stale_true_when_never_verified():
    assert reg.is_stale({"verified": False}) is True


def test_is_stale_true_when_no_last_verified_at():
    assert reg.is_stale({"verified": True, "last_verified_at": None}) is True


def test_is_stale_false_for_recent_verification():
    row = {
        "verified": True,
        "last_verified_at": datetime.now(timezone.utc).isoformat(),
    }
    assert reg.is_stale(row, max_age_days=30) is False


def test_is_stale_true_for_old_verification():
    old = datetime.now(timezone.utc) - timedelta(days=60)
    row = {"verified": True, "last_verified_at": old.isoformat()}
    assert reg.is_stale(row, max_age_days=30) is True


def test_name_key_normalizes_legal_suffix_variants():
    assert reg._name_key("Acme Inc.") == reg._name_key("ACME, LLC")


class _FakeTable:
    def __init__(self, rows):
        self.rows = rows
        self.upserted = []
        self._filters = {}

    def select(self, *_a, **_k):
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def limit(self, *_a, **_k):
        return self

    def upsert(self, row, on_conflict=None):
        self.upserted.append(row)
        return self

    def execute(self):
        matching = [r for r in self.rows if all(r.get(k) == v for k, v in self._filters.items())]
        return type("R", (), {"data": matching})()


class _FakeSupabase:
    def __init__(self, rows):
        self.table_obj = _FakeTable(rows)

    def table(self, name):
        assert name == "companies"
        return self.table_obj


def test_lookup_company_returns_match_by_normalized_name(monkeypatch):
    rows = [{"name": "Acme Inc.", "name_normalized": reg._name_key("Acme Inc."), "ats_type": "greenhouse"}]
    fake = _FakeSupabase(rows)
    monkeypatch.setattr("supabase_client.get_supabase_client", lambda: fake)

    result = reg.lookup_company("ACME LLC")
    assert result is not None
    assert result["ats_type"] == "greenhouse"


def test_lookup_company_returns_none_when_not_found(monkeypatch):
    fake = _FakeSupabase([])
    monkeypatch.setattr("supabase_client.get_supabase_client", lambda: fake)
    assert reg.lookup_company("Totally Unknown Co") is None


def test_upsert_company_writes_normalized_key(monkeypatch):
    fake = _FakeSupabase([])
    monkeypatch.setattr("supabase_client.get_supabase_client", lambda: fake)

    reg.upsert_company("Acme Inc.", careers_url="https://boards.greenhouse.io/acme", ats_type="greenhouse", verified=True, source="test")

    assert len(fake.table_obj.upserted) == 1
    written = fake.table_obj.upserted[0]
    assert written["name_normalized"] == reg._name_key("Acme Inc.")
    assert written["ats_type"] == "greenhouse"
    assert written["last_verified_at"] is not None


def test_resolve_company_ats_skips_stale_rows(monkeypatch):
    old = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    rows = [{"name": "Acme Inc.", "name_normalized": reg._name_key("Acme Inc."), "verified": True, "last_verified_at": old}]
    fake = _FakeSupabase(rows)
    monkeypatch.setattr("supabase_client.get_supabase_client", lambda: fake)

    assert reg.resolve_company_ats("Acme Inc.") is None


def test_resolve_company_ats_returns_fresh_verified_row(monkeypatch):
    rows = [{
        "name": "Acme Inc.",
        "name_normalized": reg._name_key("Acme Inc."),
        "verified": True,
        "last_verified_at": datetime.now(timezone.utc).isoformat(),
        "careers_url": "https://boards.greenhouse.io/acme",
    }]
    fake = _FakeSupabase(rows)
    monkeypatch.setattr("supabase_client.get_supabase_client", lambda: fake)

    result = reg.resolve_company_ats("Acme Inc.")
    assert result is not None
    assert result["careers_url"] == "https://boards.greenhouse.io/acme"
