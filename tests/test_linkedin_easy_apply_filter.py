"""Tests for skipping LinkedIn "Easy Apply" postings during discovery.

User instruction (2026-06-24): don't consider LinkedIn Easy Apply jobs.
fetch_linkedin_guest_jobs() parses search-result <li> cards from LinkedIn's
guest job-search API; cards carrying an "Easy Apply" badge are now skipped
before they're added to the scrape queue, matched on visible card text
rather than a specific CSS class (LinkedIn's badge class names shift
between markup versions, but the visible label text does not).
"""
import find_and_scrape_jobs as f


class _FakeResponse:
    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text


def _card_html(title, with_easy_apply):
    badge = '<li class="job-result-card__benefits">Easy Apply</li>' if with_easy_apply else ""
    return f"""
    <li>
      <a href="https://www.linkedin.com/jobs/view/123456">
        <h3 class="base-search-card__title">{title}</h3>
      </a>
      {badge}
    </li>
    """


def test_easy_apply_card_is_skipped(monkeypatch):
    html = f"<ul>{_card_html('DevOps Engineer', with_easy_apply=True)}</ul>"
    monkeypatch.setattr(f, "http_get", lambda *a, **k: _FakeResponse(200, html))

    found_urls = set()
    urls = f.fetch_linkedin_guest_jobs(["DevOps Engineer"], {}, found_urls, dry_run=False, dry_urls=[])

    assert urls == []
    assert not found_urls


def test_non_easy_apply_card_is_kept(monkeypatch):
    # dry_run=True so this only collects the candidate URL instead of
    # actually scraping it over the network (a real network call is exactly
    # what we're not testing here).
    html = f"<ul>{_card_html('DevOps Engineer', with_easy_apply=False)}</ul>"
    monkeypatch.setattr(f, "http_get", lambda *a, **k: _FakeResponse(200, html))

    found_urls = set()
    dry_urls = []
    f.fetch_linkedin_guest_jobs(["DevOps Engineer"], {}, found_urls, dry_run=True, dry_urls=dry_urls)

    assert found_urls
    assert len(dry_urls) == 1
