"""Tests for company_scraper.discovery._yahoo_links() and detector.detect_ats().

Real bug (2026-06-24), found while probing OPT-friendly companies for fast
ATS boards to watch: _yahoo_links()'s RU= redirect-param branch appended its
decoded URL with no domain filter, unlike the plain-href branch right next
to it. Yahoo's search-results page embeds internal links (e.g. a
shopping.yahoo.com widget) behind that RU= param, and those were coming back
as if they were genuine external "careers URL" results. find_careers_url()
then accepted one of these Yahoo search pages as a company's careers URL,
and detect_ats() misclassified it as "greenhouse" purely because the
substring "greenhouse.io" appeared in the URL's own query string (the
original "site:greenhouse.io" search query baked into the link) - not
because it was ever a real Greenhouse board.
"""
from company_scraper.detector import detect_ats
from company_scraper.discovery import _yahoo_links


class _FakeResponse:
    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text


def test_yahoo_links_filters_ru_redirect_to_yahoo_domain(monkeypatch):
    # Mirrors the real shopping.yahoo.com link found behind an RU= param.
    bad_href = (
        "/RU=https%3a%2f%2fshopping.yahoo.com%2fsearch%3fp%3d%2522cognizant%2522"
        "%2bjobs%2bcareers%2b%2528site%253Agreenhouse.io%2529/"
    )
    good_href = "/RU=https%3a%2f%2fboards.greenhouse.io%2facme/"
    html = f'<a href="{bad_href}">bad</a><a href="{good_href}">good</a>'

    monkeypatch.setattr(
        "company_scraper.discovery.request_with_retry",
        lambda *a, **k: _FakeResponse(200, html),
    )

    links = _yahoo_links('"cognizant" jobs careers')
    assert not any("yahoo.com" in link for link in links)
    assert any("boards.greenhouse.io/acme" in link for link in links)


def test_detect_ats_ignores_query_string_substring():
    # A Yahoo search-results URL whose query string contains the literal text
    # "greenhouse.io" (from the embedded search query) must not be detected
    # as a real Greenhouse board - only the host counts.
    url = (
        "https://shopping.yahoo.com/search?p=%22cognizant%22+jobs+careers+"
        "%28site%3Agreenhouse.io+OR+site%3Alever.co%29"
    )
    assert detect_ats(url) != "greenhouse"
    assert detect_ats(url) != "lever"


def test_detect_ats_still_detects_real_hosts():
    assert detect_ats("https://boards.greenhouse.io/acme") == "greenhouse"
    assert detect_ats("https://jobs.lever.co/acme") == "lever"
    assert detect_ats("https://acme.myworkdayjobs.com/en-US/careers") == "workday"
    assert detect_ats("https://careers-acme.icims.com/jobs") == "icims"
