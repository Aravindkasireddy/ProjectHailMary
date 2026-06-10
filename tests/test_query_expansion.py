import pytest
from unittest.mock import patch, MagicMock
from find_and_scrape_jobs import expand_target_titles_with_gemini, search_and_scrape_for_keyword

def test_expand_titles_fallback_no_api_key():
    with patch("find_and_scrape_jobs.get_active_gemini_key", return_value=None):
        titles = ["DevOps Engineer", "Site Reliability Engineer"]
        expanded = expand_target_titles_with_gemini(titles)
        
        assert "DevOps Engineer" in expanded
        assert "Site Reliability Engineer" in expanded
        assert "SRE" in expanded["Site Reliability Engineer"]
        assert "DevOps" in expanded["DevOps Engineer"]


def test_expand_titles_fallback_on_exception():
    with patch("google.generativeai.GenerativeModel") as mock_model:
        mock_instance = MagicMock()
        mock_instance.generate_content.side_effect = Exception("Quota Exceeded")
        mock_model.return_value = mock_instance
        
        titles = ["DevOps Engineer"]
        expanded = expand_target_titles_with_gemini(titles, api_key="invalid_key_to_trigger_mock")
        
        assert "DevOps Engineer" in expanded
        assert "DevOps" in expanded["DevOps Engineer"]

@patch("find_and_scrape_jobs.time.sleep")
@patch("find_and_scrape_jobs.search_yahoo")
def test_search_and_scrape_for_keyword_uses_mocked_yahoo(mock_search, mock_sleep):
    mock_search.return_value = ["https://boards.greenhouse.io/testco/jobs/123"]
    
    search_cfg = {
        "country_phrase": "United States",
        "include_remote_primary_boards": True
    }
    
    found_urls = set()
    dry_urls = []
    
    jobs, urls_found = search_and_scrape_for_keyword(
        keyword="DevOps Engineer",
        search_cfg=search_cfg,
        found_urls=found_urls,
        dry_run=True,
        dry_urls=dry_urls
    )
    
    assert len(jobs) == 0
    assert urls_found == 1
    assert len(dry_urls) == 1
    assert dry_urls[0]["job_url"] == "https://boards.greenhouse.io/testco/jobs/123"

@patch("requests.post")
@patch("dashboard_server.effective_webhook_url")
@patch("dashboard_server.load_config")
def test_send_daily_digest_alert_formats_payload(mock_load_config, mock_effective_url, mock_post):
    from dashboard_server import send_daily_digest_alert
    
    mock_load_config.return_value = {
        "search": {
            "send_digest_only": True,
            "max_digest_items": 10
        }
    }
    mock_effective_url.return_value = "https://discord.com/api/webhooks/123"
    mock_post.return_value.status_code = 204
    
    jobs = [
        ({
            "job_url": "https://example.com/job1",
            "job_title": "SRE",
            "company_name": "Acme",
            "strongest_label": "Site Reliability Engineer (SRE)",
            "location_work_type": "Remote",
            "confidence_score": 0.95,
            "rationale": "Strong background matches"
        }, "page_id_1")
    ]
    
    success = send_daily_digest_alert(jobs, 1)
    assert success
    
    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    assert "json" in kwargs
    json_payload = kwargs["json"]
    assert "embeds" in json_payload
    embed = json_payload["embeds"][0]
    assert embed["title"] == "💼 MAAS Job Sourcing Run Digest"
    assert "1" in embed["description"]
    assert len(embed["fields"]) == 1
    assert "Acme" in embed["fields"][0]["name"]
