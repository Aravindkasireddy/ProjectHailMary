"""Tests for the Yahoo-reachability pre-check in find_and_scrape_jobs.py.

Added after a live incident: Yahoo persistently returned HTTP 500 to every
request from the production VM's IP, but the per-title concurrent search
workers each independently discovered this via their own 5-failure circuit
breaker before the shared SEARCH_STATE["aborted"] flag could stop the others.
_yahoo_reachable() does one cheap probe upfront so the whole Yahoo-search
phase can be skipped in a single check instead of N redundant rediscoveries.
"""

from __future__ import annotations

import find_and_scrape_jobs as f


class _FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


def test_yahoo_reachable_true_on_2xx(monkeypatch):
    monkeypatch.setattr(f.requests, "get", lambda *a, **k: _FakeResponse(200))
    assert f._yahoo_reachable() is True


def test_yahoo_reachable_false_on_5xx(monkeypatch):
    monkeypatch.setattr(f.requests, "get", lambda *a, **k: _FakeResponse(500))
    assert f._yahoo_reachable() is False


def test_yahoo_reachable_false_on_exception(monkeypatch):
    def raise_conn_error(*a, **k):
        raise f.requests.exceptions.ConnectionError("boom")

    monkeypatch.setattr(f.requests, "get", raise_conn_error)
    assert f._yahoo_reachable() is False


def test_yahoo_reachable_true_on_4xx(monkeypatch):
    # A 4xx (e.g. captcha/blocked-but-served page) is not what we're guarding
    # against here - only persistent 5xx server errors, which is what the real
    # incident showed. Treat 4xx as "reachable" (status_code < 500).
    monkeypatch.setattr(f.requests, "get", lambda *a, **k: _FakeResponse(403))
    assert f._yahoo_reachable() is True
