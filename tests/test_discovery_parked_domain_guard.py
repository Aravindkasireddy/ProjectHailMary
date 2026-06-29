"""Tests for company_scraper.discovery._is_genuine_careers_page() - the
2026-06-29 parked-domain guard.

Real incident: a live company-URL-discovery run accepted
"americanairlinesinc.com/careers" and "tsmcarizonacorporation.com/careers"
as "found" candidates purely because head_ok() returned 200. Both were
confirmed live (curl/host) to be parked-domain redirect stubs - same IP,
~114-byte body, a bare `window.location.href` redirect to "/lander" with
zero real content. find_careers_url()'s slug-guessing fallback had no way
to tell a parked domain from a genuine careers page.
"""
from company_scraper.discovery import _is_genuine_careers_page, find_careers_url


class _FakeResponse:
    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text


def test_rejects_parking_page_stub(monkeypatch):
    # Mirrors the real americanairlinesinc.com response found live.
    parked_html = '<!DOCTYPE html><html><head><script>window.onload=function(){window.location.href="/lander"}</script></head></html>'
    monkeypatch.setattr(
        "company_scraper.discovery.request_with_retry",
        lambda *a, **k: _FakeResponse(200, parked_html),
    )
    assert _is_genuine_careers_page("https://www.fakecompany.com/careers") is False


def test_rejects_explicit_domain_for_sale_page(monkeypatch):
    html = "<html><body>This domain is parked free, courtesy of Dan.com</body></html>" * 5
    monkeypatch.setattr(
        "company_scraper.discovery.request_with_retry",
        lambda *a, **k: _FakeResponse(200, html),
    )
    assert _is_genuine_careers_page("https://www.fakecompany.com/careers") is False


def test_accepts_genuine_careers_page_content(monkeypatch):
    html = (
        "<html><body><h1>Careers at Acme</h1><p>We are hiring for several open positions. "
        "Apply now to join our team and explore current job opportunities.</p></body></html>"
    ) * 3
    monkeypatch.setattr(
        "company_scraper.discovery.request_with_retry",
        lambda *a, **k: _FakeResponse(200, html),
    )
    assert _is_genuine_careers_page("https://careers.acme.com") is True


def test_rejects_error_status(monkeypatch):
    monkeypatch.setattr(
        "company_scraper.discovery.request_with_retry",
        lambda *a, **k: _FakeResponse(404, "not found"),
    )
    assert _is_genuine_careers_page("https://www.fakecompany.com/careers") is False


def test_rejects_network_failure(monkeypatch):
    def boom(*_a, **_k):
        raise OSError("connection reset")

    monkeypatch.setattr("company_scraper.discovery.request_with_retry", boom)
    assert _is_genuine_careers_page("https://www.fakecompany.com/careers") is False


def test_find_careers_url_skips_parked_raw_domain_candidate(monkeypatch):
    # Only the raw-domain guess (careers.{compact}.com) head_ok()'s True -
    # every ATS-subdomain candidate ahead of it in _candidate_urls() is
    # False, forcing find_careers_url() down to the raw guess that needs
    # the content-sanity check. That candidate is a parked-domain stub, so
    # it must be rejected; with no Yahoo fallback hits either, the overall
    # result must be None, not the parked URL.
    monkeypatch.setattr("company_registry.resolve_company_ats", lambda name: None)
    monkeypatch.setattr("company_scraper.discovery.head_ok", lambda url: "careers.somerandomcompany.com" in url)
    monkeypatch.setattr("company_scraper.discovery._yahoo_links", lambda q: [])
    parked_html = '<script>window.onload=function(){window.location.href="/lander"}</script>'
    monkeypatch.setattr(
        "company_scraper.discovery.request_with_retry",
        lambda *a, **k: _FakeResponse(200, parked_html),
    )

    url = find_careers_url("Some Random Company")
    assert url is None


def test_find_careers_url_trusts_recognized_ats_domain_without_content_check(monkeypatch):
    # A recognized ATS domain (boards.greenhouse.io) is trusted purely from
    # head_ok() - the content-sanity check should never even be called for it.
    monkeypatch.setattr("company_registry.resolve_company_ats", lambda name: None)
    monkeypatch.setattr("company_scraper.discovery.head_ok", lambda url: "boards.greenhouse.io" in url)
    monkeypatch.setattr("company_scraper.discovery._yahoo_links", lambda q: [])

    def boom(*_a, **_k):
        raise AssertionError("should not content-check a trusted ATS domain")

    monkeypatch.setattr("company_scraper.discovery._is_genuine_careers_page", boom)
    monkeypatch.setattr("company_registry.upsert_company", lambda name, **kwargs: None)

    url = find_careers_url("Acme")
    assert url == "https://boards.greenhouse.io/acme"


def test_rejects_real_careers_page_for_a_different_company(monkeypatch):
    # Real incident (2026-06-29): "UNITED WHOLESALE MORTGAGE LLC"'s
    # slug-guessed candidate careers.united.com resolved to a genuine,
    # fully real careers page - United Airlines', not United Wholesale
    # Mortgage's. The page itself is a real careers page (passes the
    # parked-domain/content checks), so this needs the separate
    # company-name verification, not the parking-page guard.
    html = (
        "<html><body><h1>Careers at United Airlines</h1>"
        "<p>We are hiring pilots, flight attendants, and ground crew. "
        "Apply now to join our team and explore current job opportunities at United Airlines.</p>"
        "</body></html>"
    ) * 2
    monkeypatch.setattr(
        "company_scraper.discovery.request_with_retry",
        lambda *a, **k: _FakeResponse(200, html),
    )
    assert _is_genuine_careers_page("https://careers.united.com", "UNITED WHOLESALE MORTGAGE LLC") is False


def test_accepts_genuine_match_even_with_generic_first_word(monkeypatch):
    # The generic-word guard should only kick in when NO distinctive token
    # is present - a page that genuinely mentions the company's distinctive
    # tokens (not just the generic first word) should still pass.
    html = (
        "<html><body><h1>Careers at United Wholesale Mortgage</h1>"
        "<p>We are hiring loan officers and mortgage processors. "
        "Apply now to join our team and explore current job opportunities at United Wholesale Mortgage.</p>"
        "</body></html>"
    ) * 2
    monkeypatch.setattr(
        "company_scraper.discovery.request_with_retry",
        lambda *a, **k: _FakeResponse(200, html),
    )
    assert _is_genuine_careers_page("https://careers.united.com", "UNITED WHOLESALE MORTGAGE LLC") is True


def test_no_company_name_skips_the_company_match_check(monkeypatch):
    # Backward-compatible default: callers that don't pass a company name
    # (company_name="") should only get the parked-domain/content checks.
    html = (
        "<html><body><h1>Careers</h1><p>We are hiring. Apply now to join our team "
        "and explore current job opportunities.</p></body></html>"
    ) * 3
    monkeypatch.setattr(
        "company_scraper.discovery.request_with_retry",
        lambda *a, **k: _FakeResponse(200, html),
    )
    assert _is_genuine_careers_page("https://careers.example.com") is True
