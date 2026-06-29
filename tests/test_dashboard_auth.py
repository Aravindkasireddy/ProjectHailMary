import time
import threading
import socket
import pytest
import requests
from http.server import ThreadingHTTPServer
from dashboard_server import DashboardHandler

def get_free_port():
    s = socket.socket()
    s.bind(('', 0))
    port = s.getsockname()[1]
    s.close()
    return port

@pytest.fixture(scope="module")
def test_server():
    port = get_free_port()

    server = ThreadingHTTPServer(('127.0.0.1', port), DashboardHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    # Give it a second to start
    time.sleep(0.5)

    yield f"http://127.0.0.1:{port}"

    server.shutdown()
    server.server_close()

def test_endpoint_unauthorized(test_server):
    # Try querying jobs without token
    r = requests.get(f"{test_server}/api/jobs")
    assert r.status_code == 401

    # Try querying with invalid token
    headers = {"Authorization": "Bearer invalid_token"}
    r = requests.get(f"{test_server}/api/jobs", headers=headers)
    assert r.status_code == 401

def test_endpoint_read_only_access(test_server, mock_auth):
    headers = mock_auth.headers("user@hailmary.ai", role="user")

    # GET endpoint should succeed (200)
    r = requests.get(f"{test_server}/api/jobs", headers=headers)
    assert r.status_code == 200

    # POST endpoint (modifying action) should be forbidden (403)
    r = requests.post(f"{test_server}/api/scrape", json={}, headers=headers)
    assert r.status_code == 403
    assert r.json()["success"] is False

def test_endpoint_admin_access(test_server, mock_auth):
    headers = mock_auth.headers("admin@hailmary.ai", role="admin")

    # POST endpoint (modifying action) should succeed
    r = requests.post(f"{test_server}/api/scrape", json={}, headers=headers)
    assert r.status_code == 200


def test_company_scraper_status_auth(test_server, mock_auth):
    r = requests.get(f"{test_server}/api/scrape/company/status")
    assert r.status_code == 401

    headers = mock_auth.headers("user@hailmary.ai", role="user")
    r = requests.get(f"{test_server}/api/scrape/company/status", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert data.get("status") == "idle"
    assert data.get("phase") == "Idle"


def test_company_scraper_post_requires_admin(test_server, mock_auth):
    headers = mock_auth.headers("user@hailmary.ai", role="user")
    r = requests.post(
        f"{test_server}/api/scrape/company",
        json={"input": "ExampleCo"},
        headers=headers,
    )
    assert r.status_code == 403


def test_health_endpoints_no_auth_required(test_server):
    # /api/health and /api/config/default-target-titles are deliberately
    # public (used by load balancers / unauthenticated UI bootstrapping).
    r = requests.get(f"{test_server}/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

    r = requests.get(f"{test_server}/api/config/default-target-titles")
    assert r.status_code == 200
    assert isinstance(r.json().get("target_titles"), list)


def test_config_policy_analytics_require_auth_and_return_json(test_server, mock_auth):
    for path in ("/api/config", "/api/policy", "/api/analytics"):
        r = requests.get(f"{test_server}{path}")
        assert r.status_code == 401, path

    headers = mock_auth.headers("user@hailmary.ai", role="user")

    r = requests.get(f"{test_server}/api/config", headers=headers)
    assert r.status_code == 200
    assert isinstance(r.json(), dict)

    r = requests.get(f"{test_server}/api/policy", headers=headers)
    assert r.status_code == 200
    assert isinstance(r.json(), dict)

    r = requests.get(f"{test_server}/api/analytics", headers=headers)
    assert r.status_code == 200
    assert isinstance(r.json(), dict)


def test_apify_usage_endpoint(test_server, mock_auth):
    r = requests.get(f"{test_server}/api/apify-usage")
    assert r.status_code == 401

    headers = mock_auth.headers("user@hailmary.ai", role="user")
    r = requests.get(f"{test_server}/api/apify-usage", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert "configured" in data
    assert "runs_today" in data
    assert "max_runs_per_day" in data


def test_scrape_runs_status_endpoints_auth(test_server, mock_auth):
    r = requests.get(f"{test_server}/api/scrape/status")
    assert r.status_code == 401
    r = requests.get(f"{test_server}/api/scrape/active")
    assert r.status_code == 401
    r = requests.get(f"{test_server}/api/scrape/status/00000000-0000-0000-0000-000000000001")
    assert r.status_code == 401

    headers = mock_auth.headers("user@hailmary.ai", role="user")
    r = requests.get(f"{test_server}/api/scrape/status", headers=headers)
    assert r.status_code == 200
    assert "runs" in r.json()
    r = requests.get(f"{test_server}/api/scrape/active", headers=headers)
    assert r.status_code == 200
    assert "runs" in r.json()


def test_new_jobs_endpoint_auth(test_server, mock_auth):
    r = requests.get(f"{test_server}/api/new-jobs")
    assert r.status_code == 401

    headers = mock_auth.headers("user@hailmary.ai", role="user")
    r = requests.get(f"{test_server}/api/new-jobs", headers=headers)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_scraper_status_endpoint_auth(test_server, mock_auth):
    r = requests.get(f"{test_server}/api/scraper-status")
    assert r.status_code == 401

    headers = mock_auth.headers("user@hailmary.ai", role="user")
    r = requests.get(f"{test_server}/api/scraper-status", headers=headers)
    assert r.status_code == 200
    assert isinstance(r.json(), dict)


def test_watched_companies_get_requires_auth(test_server, mock_auth):
    r = requests.get(f"{test_server}/api/watched-companies")
    assert r.status_code == 401

    headers = mock_auth.headers("user@hailmary.ai", role="user")
    r = requests.get(f"{test_server}/api/watched-companies", headers=headers)
    assert r.status_code == 200
    assert "companies" in r.json()


def test_stale_status_endpoint_auth(test_server, mock_auth):
    r = requests.get(f"{test_server}/api/stale-status")
    assert r.status_code == 401

    headers = mock_auth.headers("user@hailmary.ai", role="user")
    r = requests.get(f"{test_server}/api/stale-status", headers=headers)
    assert r.status_code == 200
    assert isinstance(r.json(), dict)


def test_logs_endpoint_auth(test_server, mock_auth):
    r = requests.get(f"{test_server}/api/logs")
    assert r.status_code == 401

    headers = mock_auth.headers("user@hailmary.ai", role="user")
    r = requests.get(f"{test_server}/api/logs", headers=headers)
    assert r.status_code == 200
    assert isinstance(r.json(), dict)


def test_salary_insights_endpoint_auth(test_server, mock_auth):
    r = requests.get(f"{test_server}/api/salary-insights")
    assert r.status_code == 401

    headers = mock_auth.headers("user@hailmary.ai", role="user")
    r = requests.get(f"{test_server}/api/salary-insights", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert "yearly_count" in data
    assert "hourly_count" in data


def test_resume_get_endpoint_auth(test_server, mock_auth):
    r = requests.get(f"{test_server}/api/resume")
    assert r.status_code == 401

    headers = mock_auth.headers("user@hailmary.ai", role="user")
    r = requests.get(f"{test_server}/api/resume", headers=headers)
    assert r.status_code == 200


def test_config_reset_target_titles_allows_any_authenticated_role(test_server, mock_auth):
    # In _user_authed_post_paths (do_POST) - any authenticated role, not
    # admin-only, since it only resets the caller's own scoped config.
    r = requests.post(f"{test_server}/api/config/reset-target-titles", json={})
    assert r.status_code == 401

    user_headers = mock_auth.headers("user@hailmary.ai", role="user")
    r = requests.post(f"{test_server}/api/config/reset-target-titles", json={}, headers=user_headers)
    assert r.status_code == 200

    admin_headers = mock_auth.headers("admin@hailmary.ai", role="admin")
    r = requests.post(f"{test_server}/api/config/reset-target-titles", json={}, headers=admin_headers)
    assert r.status_code == 200


def test_test_webhook_requires_admin(test_server, mock_auth):
    user_headers = mock_auth.headers("user@hailmary.ai", role="user")
    r = requests.post(f"{test_server}/api/test-webhook", json={}, headers=user_headers)
    assert r.status_code == 403


def test_update_pipeline_stage_requires_admin(test_server, mock_auth):
    user_headers = mock_auth.headers("user@hailmary.ai", role="user")
    r = requests.post(
        f"{test_server}/api/update-pipeline-stage",
        json={"job_url": "https://example.com/job/1", "pipeline_stage": "Applied"},
        headers=user_headers,
    )
    assert r.status_code == 403


def test_delete_requires_admin(test_server, mock_auth):
    user_headers = mock_auth.headers("user@hailmary.ai", role="user")
    r = requests.post(
        f"{test_server}/api/delete",
        json={"job_url": "https://example.com/job/1"},
        headers=user_headers,
    )
    assert r.status_code == 403


def test_check_stale_requires_admin(test_server, mock_auth):
    user_headers = mock_auth.headers("user@hailmary.ai", role="user")
    r = requests.post(f"{test_server}/api/check-stale", json={}, headers=user_headers)
    assert r.status_code == 403


def test_watched_companies_post_allows_any_authenticated_role(test_server, mock_auth):
    # Also in _user_authed_post_paths (do_POST) - any authenticated role,
    # not admin-only. Sending no "input" field hits the handler's own
    # validation (400) rather than the network-calling happy path, so this
    # proves the auth gate passed without making a live discovery request.
    r = requests.post(f"{test_server}/api/watched-companies", json={})
    assert r.status_code == 401

    user_headers = mock_auth.headers("user@hailmary.ai", role="user")
    r = requests.post(f"{test_server}/api/watched-companies", json={}, headers=user_headers)
    assert r.status_code == 400
    assert "input" in r.json().get("message", "")


def test_classifier_feedback_endpoint_is_reachable(test_server, mock_auth):
    # Real bug, found 2026-06-30: this route (and reset-target-titles above)
    # was chained as `elif` of the auth-gate `if path.startswith("/api/")`,
    # which is always True for any /api/ path - so it was dead code and
    # always 404'd regardless of auth, until fixed in dashboard_server.py.
    r = requests.post(f"{test_server}/api/classifier-feedback", json={})
    assert r.status_code == 401

    headers = mock_auth.headers("user@hailmary.ai", role="user")
    r = requests.post(f"{test_server}/api/classifier-feedback", json={}, headers=headers)
    assert r.status_code != 404
