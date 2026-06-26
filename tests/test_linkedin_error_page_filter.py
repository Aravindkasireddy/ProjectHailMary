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


def test_linkedin_easy_apply_job_is_rejected(monkeypatch):
    # Real incident (2026-06-26): the earlier Easy Apply fix only covered
    # fetch_linkedin_guest_jobs()'s search-result card loop. scrape_linkedin()
    # is also called directly on any LinkedIn URL surfaced via the bulk
    # Yahoo-search discovery path, which never goes through that card loop -
    # Easy Apply postings reached this way were never filtered.
    html = (
        "<html><body>"
        "<h1 class='topcard__title'>Senior CI/CD Engineer</h1>"
        "<a class='topcard__org-name-link'>Acme Corp</a>"
        "<button class='jobs-apply-button top-card-layout__cta'><span>Easy Apply</span></button>"
        "<div class='description__text'>Manage CI/CD pipelines.</div>"
        "</body></html>"
    )
    monkeypatch.setattr(f, "fetch_with_playwright", lambda url: html)
    assert f.scrape_linkedin("https://www.linkedin.com/jobs/view/12345") is None


def test_linkedin_seo_aggregator_page_is_rejected(monkeypatch):
    # Real incident (2026-06-26): LinkedIn's own SEO/search-aggregator landing
    # pages ("54,000+ Migration Specialist Jobs in United States") were being
    # scraped and stored as if they were real individual postings.
    html = "<html><body><h1>54,000+ Migration Specialist Jobs in United States</h1></body></html>"
    monkeypatch.setattr(f, "fetch_with_playwright", lambda url: html)
    assert f.scrape_linkedin("https://www.linkedin.com/jobs/migration-specialist-jobs") is None


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
