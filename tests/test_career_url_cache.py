"""Tests for career_url_cache.py - Optimization Sprint #1 (2026-06-27).

Covers the cache module in isolation (hit, miss, TTL expiration,
invalidation, overwrite, disabled bypass, concurrency safety) plus its
wiring into find_and_scrape_jobs.resolve_career_link() (cache hit returns
the same URL the original implementation would have found via search/LLM;
cache miss falls through to the existing unmodified code path; a failed
live-URL validation invalidates the cache entry).
"""
import json
import threading
import time

import pytest

import career_url_cache as cuc
import find_and_scrape_jobs as f


@pytest.fixture(autouse=True)
def _reset_cache_state(monkeypatch):
    cuc.reset_in_memory_cache()
    monkeypatch.delenv("CAREER_URL_CACHE_DISABLE", raising=False)
    monkeypatch.delenv("CAREER_URL_CACHE_TTL_SECONDS", raising=False)
    yield
    cuc.reset_in_memory_cache()


def test_cache_miss_returns_none(tmp_path):
    assert cuc.get(str(tmp_path), "acme") is None


def test_cache_set_then_hit_returns_same_url(tmp_path):
    cuc.set_entry(str(tmp_path), "acme", "https://boards.greenhouse.io/acme/jobs/1", source="search")
    entry = cuc.get(str(tmp_path), "acme")
    assert entry is not None
    assert entry["career_url"] == "https://boards.greenhouse.io/acme/jobs/1"
    assert entry["source"] == "search"
    assert entry["ats_type"] == "greenhouse"


def test_cache_entry_persists_to_disk(tmp_path):
    cuc.set_entry(str(tmp_path), "acme", "https://boards.greenhouse.io/acme/jobs/1")
    path = tmp_path / "logs" / "career_url_cache.json"
    assert path.exists()
    on_disk = json.loads(path.read_text())
    assert on_disk["acme"]["career_url"] == "https://boards.greenhouse.io/acme/jobs/1"


def test_ttl_expiration_returns_none(tmp_path, monkeypatch):
    monkeypatch.setenv("CAREER_URL_CACHE_TTL_SECONDS", "1")
    cuc.set_entry(str(tmp_path), "acme", "https://boards.greenhouse.io/acme/jobs/1")
    assert cuc.get(str(tmp_path), "acme") is not None
    time.sleep(1.1)
    assert cuc.get(str(tmp_path), "acme") is None


def test_explicit_invalidation_removes_entry(tmp_path):
    cuc.set_entry(str(tmp_path), "acme", "https://boards.greenhouse.io/acme/jobs/1")
    assert cuc.get(str(tmp_path), "acme") is not None
    removed = cuc.invalidate(str(tmp_path), "acme")
    assert removed is True
    assert cuc.get(str(tmp_path), "acme") is None


def test_invalidating_missing_key_returns_false(tmp_path):
    assert cuc.invalidate(str(tmp_path), "nope") is False


def test_overwrite_replaces_existing_entry(tmp_path):
    cuc.set_entry(str(tmp_path), "acme", "https://old.example.com/acme")
    cuc.set_entry(str(tmp_path), "acme", "https://boards.lever.co/acme")
    entry = cuc.get(str(tmp_path), "acme")
    assert entry["career_url"] == "https://boards.lever.co/acme"
    assert entry["ats_type"] == "lever"


def test_disabled_cache_never_hits(tmp_path, monkeypatch):
    cuc.set_entry(str(tmp_path), "acme", "https://boards.greenhouse.io/acme/jobs/1")
    monkeypatch.setenv("CAREER_URL_CACHE_DISABLE", "1")
    assert cuc.get(str(tmp_path), "acme") is None


def test_disabled_cache_never_writes(tmp_path, monkeypatch):
    monkeypatch.setenv("CAREER_URL_CACHE_DISABLE", "1")
    cuc.set_entry(str(tmp_path), "acme", "https://boards.greenhouse.io/acme/jobs/1")
    monkeypatch.delenv("CAREER_URL_CACHE_DISABLE")
    assert cuc.get(str(tmp_path), "acme") is None


def test_concurrent_writes_do_not_corrupt_cache(tmp_path):
    def writer(i):
        cuc.set_entry(str(tmp_path), f"company{i}", f"https://boards.greenhouse.io/company{i}/jobs/1")

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    for i in range(20):
        entry = cuc.get(str(tmp_path), f"company{i}")
        assert entry is not None
        assert entry["career_url"] == f"https://boards.greenhouse.io/company{i}/jobs/1"


def test_infer_ats_type_handles_unknown_domain():
    assert cuc.infer_ats_type("https://example.com/careers") is None
    assert cuc.infer_ats_type(None) is None


# --- Wiring into resolve_career_link() ---

def test_resolve_career_link_cache_hit_skips_search_and_llm(tmp_path, monkeypatch):
    monkeypatch.setattr(f, "WORKSPACE", tmp_path)
    cuc.set_entry(str(tmp_path), "acme", "https://boards.greenhouse.io/acme/jobs/1", source="search")

    def _should_not_be_called(*a, **k):
        raise AssertionError("search/LLM must not run on a cache hit")

    monkeypatch.setattr(f, "extract_ats_links", lambda jd, html: [])
    monkeypatch.setattr(f, "search_for_job_url", _should_not_be_called)
    monkeypatch.setattr(f, "resolve_career_link_with_llm", _should_not_be_called)

    result = f.resolve_career_link("DevOps Engineer", "Acme", "some jd text", html=None)
    assert result == "https://boards.greenhouse.io/acme/jobs/1"


def test_resolve_career_link_cache_miss_runs_existing_search_path_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(f, "WORKSPACE", tmp_path)
    monkeypatch.setattr(f, "extract_ats_links", lambda jd, html: [])
    monkeypatch.setattr(f, "search_for_job_url", lambda query: ["https://boards.greenhouse.io/acme/jobs/2"])

    result = f.resolve_career_link("DevOps Engineer", "Acme", "some jd text", html=None)
    assert result == "https://boards.greenhouse.io/acme/jobs/2"

    # The freshly-resolved URL should now be cached for next time.
    entry = cuc.get(str(tmp_path), "acme")
    assert entry is not None
    assert entry["career_url"] == "https://boards.greenhouse.io/acme/jobs/2"
    assert entry["source"] == "search"


def test_resolve_career_link_disabled_cache_behaves_like_pre_cache_implementation(tmp_path, monkeypatch):
    monkeypatch.setattr(f, "WORKSPACE", tmp_path)
    monkeypatch.setenv("CAREER_URL_CACHE_DISABLE", "1")
    cuc.set_entry(str(tmp_path), "acme", "https://stale.example.com/acme")
    monkeypatch.setattr(f, "extract_ats_links", lambda jd, html: [])
    monkeypatch.setattr(f, "search_for_job_url", lambda query: ["https://boards.greenhouse.io/acme/jobs/3"])

    result = f.resolve_career_link("DevOps Engineer", "Acme", "some jd text", html=None)
    assert result == "https://boards.greenhouse.io/acme/jobs/3"


def test_resolve_career_link_step1_direct_link_bypasses_cache_entirely(tmp_path, monkeypatch):
    monkeypatch.setattr(f, "WORKSPACE", tmp_path)
    monkeypatch.setattr(f, "extract_ats_links", lambda jd, html: ["https://boards.greenhouse.io/acme/jobs/direct"])

    result = f.resolve_career_link("DevOps Engineer", "Acme", "some jd text", html="<html></html>")
    assert result == "https://boards.greenhouse.io/acme/jobs/direct"
    # Step 1 hits return before the cache is even consulted - no entry written.
    assert cuc.get(str(tmp_path), "acme") is None


# --- Telemetry emission ---

def test_cache_hit_emits_lookup_event_with_cache_hit_true(tmp_path, monkeypatch):
    monkeypatch.setattr(f, "WORKSPACE", tmp_path)
    cuc.set_entry(str(tmp_path), "acme", "https://boards.greenhouse.io/acme/jobs/1")
    monkeypatch.setattr(f, "extract_ats_links", lambda jd, html: [])

    f.resolve_career_link("DevOps Engineer", "Acme", "some jd text", html=None)

    log_path = tmp_path / "logs" / "pipeline_metrics.jsonl"
    recs = [json.loads(line) for line in log_path.read_text().strip().splitlines()]
    lookup_events = [r for r in recs if r["operation_name"] == "career_url_cache_lookup"]
    assert len(lookup_events) == 1
    assert lookup_events[0]["metadata"]["cache_hit"] is True
    assert "cache_age_s" in lookup_events[0]["metadata"]
    assert "ttl_remaining_s" in lookup_events[0]["metadata"]


def test_cache_miss_emits_lookup_event_with_cache_hit_false(tmp_path, monkeypatch):
    monkeypatch.setattr(f, "WORKSPACE", tmp_path)
    monkeypatch.setattr(f, "extract_ats_links", lambda jd, html: [])
    monkeypatch.setattr(f, "search_for_job_url", lambda query: [])
    monkeypatch.setattr(f, "resolve_career_link_with_llm", lambda *a, **k: None)

    f.resolve_career_link("DevOps Engineer", "Acme", "some jd text", html=None)

    log_path = tmp_path / "logs" / "pipeline_metrics.jsonl"
    recs = [json.loads(line) for line in log_path.read_text().strip().splitlines()]
    lookup_events = [r for r in recs if r["operation_name"] == "career_url_cache_lookup"]
    assert len(lookup_events) == 1
    assert lookup_events[0]["metadata"]["cache_hit"] is False


def test_cache_write_emits_event_on_fresh_resolution(tmp_path, monkeypatch):
    monkeypatch.setattr(f, "WORKSPACE", tmp_path)
    monkeypatch.setattr(f, "extract_ats_links", lambda jd, html: [])
    monkeypatch.setattr(f, "search_for_job_url", lambda query: ["https://boards.greenhouse.io/acme/jobs/4"])

    f.resolve_career_link("DevOps Engineer", "Acme", "some jd text", html=None)

    log_path = tmp_path / "logs" / "pipeline_metrics.jsonl"
    recs = [json.loads(line) for line in log_path.read_text().strip().splitlines()]
    write_events = [r for r in recs if r["operation_name"] == "career_url_cache_write"]
    assert len(write_events) == 1
    assert write_events[0]["metadata"]["cache_source"] == "search"


def test_failed_liveness_check_invalidates_cache_and_emits_event(tmp_path, monkeypatch):
    monkeypatch.setattr(f, "WORKSPACE", tmp_path)
    cuc.set_entry(str(tmp_path), "acme", "https://boards.greenhouse.io/acme/jobs/1")

    html = (
        "<html><body>"
        "<h1 class='topcard__title'>DevOps Engineer</h1>"
        "<a class='topcard__org-name-link'>Acme Corp</a>"
        "<div class='description__text'>Manage CI/CD pipelines.</div>"
        "</body></html>"
    )
    monkeypatch.setattr(f, "fetch_with_playwright", lambda url: html)
    monkeypatch.setattr(f, "resolve_career_link", lambda *a, **k: "https://boards.greenhouse.io/acme/jobs/1")
    monkeypatch.setattr(f, "_resolved_career_url_is_live", lambda url: False)

    result = f.scrape_linkedin("https://www.linkedin.com/jobs/view/12345")
    # Job is dropped entirely — no LinkedIn URL fallback; direct ATS URL required.
    assert result is None

    assert cuc.get(str(tmp_path), "acme") is None

    log_path = tmp_path / "logs" / "pipeline_metrics.jsonl"
    recs = [json.loads(line) for line in log_path.read_text().strip().splitlines()]
    invalidate_events = [r for r in recs if r["operation_name"] == "career_url_cache_invalidate"]
    assert len(invalidate_events) == 1
    assert invalidate_events[0]["metadata"]["cache_invalidation_reason"] == "failed_liveness_check"
