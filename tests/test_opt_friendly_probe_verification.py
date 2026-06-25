"""Tests for scripts/probe_opt_friendly_ats.py's _verify_company_on_page().

Real incident (2026-06-25): scanning the full page body for 2+ keyword
matches still let through false positives where one "match" was generic
business-name vocabulary like "Systems"/"Solutions" rather than an actual
distinguishing word, or where the underlying clean_company_name() (designed
for loose fuzzy matching, not verification) stripped real distinguishing
words like "Systems" as if they were legal suffixes. Confirmed live across
the full 9985-company OPT-friendly probe run: "AIR FILTERS INC" verified
against boards.greenhouse.io/air (whose real <title> is "Jobs at Air", not
"Air Filters Inc") and "APEX SYSTEMS LLC" verified against
boards.greenhouse.io/apex (real <title> "Jobs at Apex Eye", not "Apex
Systems"). Fixed by checking only the <title> tag (no boilerplate UI text
there) with a lighter suffix-stripper that keeps real distinguishing words.
"""
from scripts.probe_opt_friendly_ats import _verify_company_on_page


class _FakeResponse:
    def __init__(self, text):
        self.text = text


def _titled(title):
    return f"<html><head><title>{title}</title></head><body></body></html>"


def test_rejects_generic_slug_collision(monkeypatch):
    monkeypatch.setattr(
        "scripts.probe_opt_friendly_ats.requests.get",
        lambda *a, **k: _FakeResponse(_titled("Jobs at Air")),
    )
    assert _verify_company_on_page("AIR FILTERS INC", "https://boards.greenhouse.io/air", "greenhouse") is False


def test_rejects_when_systems_suffix_collapses_to_generic_word(monkeypatch):
    monkeypatch.setattr(
        "scripts.probe_opt_friendly_ats.requests.get",
        lambda *a, **k: _FakeResponse(_titled("Jobs at Apex Eye")),
    )
    assert _verify_company_on_page("APEX SYSTEMS LLC", "https://boards.greenhouse.io/apex", "greenhouse") is False


def test_accepts_genuine_match(monkeypatch):
    monkeypatch.setattr(
        "scripts.probe_opt_friendly_ats.requests.get",
        lambda *a, **k: _FakeResponse(_titled("Stripe Jobs")),
    )
    assert _verify_company_on_page("STRIPE INC", "https://boards.greenhouse.io/stripe", "greenhouse") is True


def test_accepts_genuine_match_with_distinguishing_words(monkeypatch):
    monkeypatch.setattr(
        "scripts.probe_opt_friendly_ats.requests.get",
        lambda *a, **k: _FakeResponse(_titled("Jobs at Apex Systems LLC")),
    )
    assert _verify_company_on_page("APEX SYSTEMS LLC", "https://boards.greenhouse.io/apex", "greenhouse") is True


def test_no_title_tag_is_unverified(monkeypatch):
    monkeypatch.setattr(
        "scripts.probe_opt_friendly_ats.requests.get",
        lambda *a, **k: _FakeResponse("<html><body>no title here</body></html>"),
    )
    assert _verify_company_on_page("STRIPE INC", "https://boards.greenhouse.io/stripe", "greenhouse") is False
