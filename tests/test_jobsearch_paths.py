import os
from pathlib import Path

import pytest

# Repo root on sys.path
import jobsearch_paths


def test_workspace_root_default_points_at_repo():
    os.environ.pop("JOBSEARCH_ROOT", None)
    root = jobsearch_paths.workspace_root()
    assert (root / "dashboard_server.py").is_file()
    assert (root / "find_and_scrape_jobs.py").is_file()


def test_workspace_root_respects_env(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSEARCH_ROOT", str(tmp_path))
    assert jobsearch_paths.workspace_root() == tmp_path.resolve()


def test_effective_webhook_prefers_env(monkeypatch):
    from jobsearch_webhook import effective_webhook_url

    monkeypatch.setenv("JOBSEARCH_WEBHOOK_URL", "https://example.com/hook")
    assert effective_webhook_url({"webhook_url": "https://ignored"}) == "https://example.com/hook"


def test_normalize_job_url_roundtrip():
    from find_and_scrape_jobs import normalize_job_url

    u = "HTTPS://Boards.Greenhouse.io/Acme/Jobs/12345/"
    assert "greenhouse.io" in normalize_job_url(u)
