"""Tests for scrape_linkedin()'s rejection of LinkedIn block/error pages.

Real incident (2026-06-24): LinkedIn's rate-limit/block page renders a bare
<h1>Error</h1> heading with no org-name element. scrape_linkedin() only
rejected titles of "Sign Up"/"Unknown Title", so this page parsed as a
"real" job with job_title="Error", company_name="Unknown" and proceeded into
the expensive resolve_career_link() search pipeline, wasting 3 Yahoo + 3
DuckDuckGo search attempts on garbage data. Fixed by rejecting known
error-page title strings and any job with no resolvable company name.
"""

import find_and_scrape_jobs as f


def test_linkedin_error_page_is_rejected(monkeypatch):
    html = "<html><body><h1>Error</h1></body></html>"
    monkeypatch.setattr(f, "fetch_with_playwright", lambda url: html)
    assert f.scrape_linkedin("https://www.linkedin.com/jobs/view/12345") is None


def test_linkedin_job_with_no_company_elem_is_rejected(monkeypatch):
    # A parsed, non-blocklisted title but with no org-name element anywhere
    # on the page is also a sign we're not looking at a genuine job posting.
    html = "<html><body><h1>Some Random Heading</h1></body></html>"
    monkeypatch.setattr(f, "fetch_with_playwright", lambda url: html)
    assert f.scrape_linkedin("https://www.linkedin.com/jobs/view/12345") is None


def test_linkedin_genuine_job_is_accepted(monkeypatch):
    html = (
        "<html><body>"
        "<h1 class='topcard__title'>DevOps Engineer</h1>"
        "<a class='topcard__org-name-link'>Acme Corp</a>"
        "<div class='description__text'>Manage CI/CD pipelines.</div>"
        "</body></html>"
    )
    monkeypatch.setattr(f, "fetch_with_playwright", lambda url: html)
    monkeypatch.setattr(f, "resolve_career_link", lambda *a, **k: None)
    result = f.scrape_linkedin("https://www.linkedin.com/jobs/view/12345")
    assert result is not None
    assert result["job_title"] == "DevOps Engineer"
    assert result["company_name"] == "Acme Corp"
