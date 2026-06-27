"""Tests for company_scraper.discovery.find_careers_url()'s registry-first lookup.

Goal: skip live discovery (slug-guessing + Yahoo fallback) entirely when the
company's ATS is already known from a previous discovery run.
"""
from company_scraper.discovery import find_careers_url


def test_registry_hit_skips_live_discovery_entirely(monkeypatch):
    monkeypatch.setattr(
        "company_registry.resolve_company_ats",
        lambda name: {"careers_url": "https://boards.greenhouse.io/acme", "ats_type": "greenhouse"},
    )

    def boom(*_a, **_k):
        raise AssertionError("should not attempt live discovery on a registry hit")

    monkeypatch.setattr("company_scraper.discovery.head_ok", boom)
    monkeypatch.setattr("company_scraper.discovery._yahoo_links", boom)

    url = find_careers_url("Acme Inc.")
    assert url == "https://boards.greenhouse.io/acme"


def test_registry_miss_falls_back_to_live_discovery_and_persists(monkeypatch):
    monkeypatch.setattr("company_registry.resolve_company_ats", lambda name: None)
    monkeypatch.setattr("company_scraper.discovery.head_ok", lambda url: "boards.greenhouse.io" in url)
    monkeypatch.setattr("company_scraper.discovery._yahoo_links", lambda q: [])

    persisted = []
    monkeypatch.setattr(
        "company_registry.upsert_company",
        lambda name, **kwargs: persisted.append((name, kwargs)),
    )

    url = find_careers_url("Acme")
    assert url == "https://boards.greenhouse.io/acme"
    assert len(persisted) == 1
    assert persisted[0][0] == "Acme"
    assert persisted[0][1]["verified"] is True
