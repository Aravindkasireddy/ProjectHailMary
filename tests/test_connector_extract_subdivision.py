"""Tests for _record_connector_substep() - the 2026-06-27 instrumentation
task that subdivides connector_extract (confirmed ~60% of total pipeline
time) into measurable sub-operations (career_url_resolution, llm_fallback,
live_url_validation, html_parsing, json_parsing, llm_extraction) without
changing any retry logic, concurrency, or Playwright usage.
"""
import find_and_scrape_jobs as f


def test_record_connector_substep_writes_expected_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(f, "WORKSPACE", tmp_path)

    f._record_connector_substep("html_parsing", 0.5, connector="greenhouse", company="Acme", success=True, source="raw_html")

    log_path = tmp_path / "logs" / "pipeline_metrics.jsonl"
    assert log_path.exists()
    import json

    rec = json.loads(log_path.read_text().strip().splitlines()[-1])
    assert rec["operation_name"] == "html_parsing"
    assert rec["stage"] == "discovery"
    assert rec["ats_source"] == "greenhouse"
    assert rec["company"] == "Acme"
    assert rec["success"] is True
    assert rec["duration_ms"] == 500
    assert rec["metadata"]["source"] == "raw_html"
    assert rec["metadata"]["status"] == "success"
    assert isinstance(rec["metadata"]["thread_id"], int)


def test_record_connector_substep_never_raises(monkeypatch):
    # Even if WORKSPACE/append_pipeline_metric is broken, this must not raise -
    # it's pure observability and must never affect the operation it measures.
    monkeypatch.setattr(f, "WORKSPACE", None)
    f._record_connector_substep("op", 1.0)  # should not raise


def test_scrape_linkedin_emits_html_parsing_and_career_resolution_events(tmp_path, monkeypatch):
    monkeypatch.setattr(f, "WORKSPACE", tmp_path)

    html = (
        "<html><body>"
        "<h1 class='topcard__title'>DevOps Engineer</h1>"
        "<a class='topcard__org-name-link'>Acme Corp</a>"
        "<div class='description__text'>Manage CI/CD pipelines.</div>"
        "</body></html>"
    )
    monkeypatch.setattr(f, "fetch_with_playwright", lambda url: html)
    monkeypatch.setattr(f, "resolve_career_link", lambda *a, **k: None)

    # Job is dropped when ATS URL can't be resolved — no LinkedIn URL fallback.
    result = f.scrape_linkedin("https://www.linkedin.com/jobs/view/12345")
    assert result is None

    import json

    log_path = tmp_path / "logs" / "pipeline_metrics.jsonl"
    recs = [json.loads(line) for line in log_path.read_text().strip().splitlines()]
    op_names = {r["operation_name"] for r in recs}
    assert "html_parsing" in op_names
    assert "career_url_resolution" in op_names
    # resolve_career_link returned None, so live_url_validation should NOT
    # have been called (existing behavior preserved - no validation needed
    # when there's nothing to validate).
    assert "live_url_validation" not in op_names


def test_scrape_linkedin_validates_resolved_url_when_present(tmp_path, monkeypatch):
    monkeypatch.setattr(f, "WORKSPACE", tmp_path)

    html = (
        "<html><body>"
        "<h1 class='topcard__title'>DevOps Engineer</h1>"
        "<a class='topcard__org-name-link'>Acme Corp</a>"
        "<div class='description__text'>Manage CI/CD pipelines.</div>"
        "</body></html>"
    )
    monkeypatch.setattr(f, "fetch_with_playwright", lambda url: html)
    monkeypatch.setattr(f, "resolve_career_link", lambda *a, **k: "https://boards.greenhouse.io/acme/jobs/1")
    monkeypatch.setattr(f, "_resolved_career_url_is_live", lambda url: True)

    result = f.scrape_linkedin("https://www.linkedin.com/jobs/view/12345")
    assert result is not None
    assert result["job_url"] == "https://boards.greenhouse.io/acme/jobs/1"

    import json

    log_path = tmp_path / "logs" / "pipeline_metrics.jsonl"
    recs = [json.loads(line) for line in log_path.read_text().strip().splitlines()]
    op_names = {r["operation_name"] for r in recs}
    assert "live_url_validation" in op_names
