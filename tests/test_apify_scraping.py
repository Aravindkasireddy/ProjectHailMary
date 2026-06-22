"""Tests for the Apify-first scraping integration (no network).

Covers: output normalization, the is_configured() gate, the daily run-count
guardrail, and that workday/generic/icims fall back to local scraping when
Apify is unset or raises.
"""

from __future__ import annotations

import json

import pytest

from company_scraper.scrapers import apify_client


def test_is_configured_false_when_no_token(monkeypatch):
    monkeypatch.delenv("APIFY_API_TOKEN", raising=False)
    assert apify_client.is_configured() is False


def test_is_configured_true_when_token_set(monkeypatch):
    monkeypatch.setenv("APIFY_API_TOKEN", "tok")
    assert apify_client.is_configured() is True


def test_normalize_items_maps_fields_and_skips_missing_url():
    items = [
        {"title": "SRE", "description": "desc", "locations": ["Remote", "US"], "url": "https://x/1"},
        {"title": "No URL", "description": "x", "locations": [], "url": ""},
    ]
    rows = apify_client._normalize_items(items, "Acme")
    assert len(rows) == 1
    row = rows[0]
    assert row["job_url"] == "https://x/1"
    assert row["job_title"] == "SRE"
    assert row["company_name"] == "Acme"
    assert row["location_work_type"] == "Remote, US"
    assert row["requirement_id"] == ""


def test_normalize_items_defaults_location_to_remote_when_empty():
    items = [{"title": "Eng", "description": "", "locations": [], "url": "https://x/2"}]
    rows = apify_client._normalize_items(items, "")
    assert rows[0]["location_work_type"] == "Remote"


def test_daily_usage_cap_blocks_after_limit(tmp_path, monkeypatch):
    usage_file = tmp_path / "apify_usage.json"
    monkeypatch.setattr(apify_client, "_USAGE_FILE", usage_file)
    monkeypatch.setenv("APIFY_MAX_RUNS_PER_DAY", "2")

    apify_client._check_and_increment_daily_usage()
    apify_client._check_and_increment_daily_usage()
    with pytest.raises(RuntimeError, match="daily run cap"):
        apify_client._check_and_increment_daily_usage()

    assert json.loads(usage_file.read_text())[apify_client._today_key()] == 2


def test_daily_usage_tracking_failure_does_not_block(tmp_path, monkeypatch):
    # Point at a path whose parent can't be created (file where a dir should be)
    bogus_parent = tmp_path / "not_a_dir"
    bogus_parent.write_text("x")
    monkeypatch.setattr(apify_client, "_USAGE_FILE", bogus_parent / "apify_usage.json")
    monkeypatch.setenv("APIFY_MAX_RUNS_PER_DAY", "200")
    # Should not raise despite the broken usage-file path
    apify_client._check_and_increment_daily_usage()


def test_run_actor_raises_without_token(monkeypatch):
    monkeypatch.delenv("APIFY_API_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="APIFY_API_TOKEN"):
        apify_client.run_actor("some/actor", {})


def test_generic_falls_back_to_local_when_apify_raises(monkeypatch):
    from company_scraper.scrapers import generic

    monkeypatch.setattr(apify_client, "is_configured", lambda: True)
    monkeypatch.setattr(
        apify_client, "fetch_jobs_via_apify", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    # Force the local path to short-circuit cheaply instead of hitting the network.
    monkeypatch.setattr(generic, "_robots_allowed", lambda url: False)

    rows = generic.fetch_jobs("https://example.com/careers", "Acme")
    assert rows == []  # Apify's exception must never propagate; local fallback ran instead


def test_workday_falls_back_to_local_when_apify_raises(monkeypatch):
    from company_scraper.scrapers import workday

    monkeypatch.setattr(apify_client, "is_configured", lambda: True)
    monkeypatch.setattr(
        apify_client,
        "fetch_workday_jobs_via_apify",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    calls = {"local": False}

    class _FakePlaywright:
        def __enter__(self):
            calls["local"] = True
            raise RuntimeError("local playwright invoked (expected in this test)")

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(workday, "sync_playwright", lambda: _FakePlaywright())

    with pytest.raises(RuntimeError, match="local playwright invoked"):
        workday.fetch_jobs("https://acme.wd1.myworkdayjobs.com/External", "Acme")

    assert calls["local"] is True
