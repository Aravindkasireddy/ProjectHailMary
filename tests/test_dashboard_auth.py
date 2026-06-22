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
