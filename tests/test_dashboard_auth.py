import os
import time
import threading
import socket
import pytest
import requests
from http.server import ThreadingHTTPServer
from dashboard_server import DashboardHandler, active_sessions

def get_free_port():
    s = socket.socket()
    s.bind(('', 0))
    port = s.getsockname()[1]
    s.close()
    return port

@pytest.fixture(scope="module")
def test_server():
    port = get_free_port()
    
    # Configure env for test
    os.environ["ADMIN_PASSWORD"] = "testadmin"
    os.environ["USER_PASSWORD"] = "testuser"
    
    # Update passwords in module import if needed
    import dashboard_server
    dashboard_server.ADMIN_PASSWORD = "testadmin"
    dashboard_server.USER_PASSWORD = "testuser"
    
    server = ThreadingHTTPServer(('127.0.0.1', port), DashboardHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    
    # Give it a second to start
    time.sleep(0.5)
    
    yield f"http://127.0.0.1:{port}"
    
    server.shutdown()
    server.server_close()

def test_login_success(test_server):
    # Test valid admin login
    r = requests.post(f"{test_server}/api/login", json={"password": "testadmin"})
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is True
    assert data["role"] == "admin"
    assert "token" in data
    
    # Test valid user login
    r = requests.post(f"{test_server}/api/login", json={"password": "testuser"})
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is True
    assert data["role"] == "user"
    assert "token" in data

def test_login_invalid(test_server):
    r = requests.post(f"{test_server}/api/login", json={"password": "wrongpassword"})
    assert r.status_code == 401
    assert r.json()["success"] is False

def test_endpoint_unauthorized(test_server):
    # Try querying jobs without token
    r = requests.get(f"{test_server}/api/jobs")
    assert r.status_code == 401
    
    # Try querying with invalid token
    headers = {"Authorization": "Bearer invalid_token"}
    r = requests.get(f"{test_server}/api/jobs", headers=headers)
    assert r.status_code == 401

def test_endpoint_read_only_access(test_server):
    # Get user token
    r = requests.post(f"{test_server}/api/login", json={"password": "testuser"})
    token = r.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    
    # GET endpoint should succeed (200)
    r = requests.get(f"{test_server}/api/jobs", headers=headers)
    assert r.status_code == 200
    
    # POST endpoint (modifying action) should be forbidden (403)
    r = requests.post(f"{test_server}/api/scrape", json={}, headers=headers)
    assert r.status_code == 403
    assert r.json()["success"] is False

def test_endpoint_admin_access(test_server):
    # Get admin token
    r = requests.post(f"{test_server}/api/login", json={"password": "testadmin"})
    token = r.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    
    # POST endpoint (modifying action) should succeed
    r = requests.post(f"{test_server}/api/scrape", json={}, headers=headers)
    assert r.status_code == 200


def test_company_scraper_status_auth(test_server):
    r = requests.get(f"{test_server}/api/scrape/company/status")
    assert r.status_code == 401

    r = requests.post(f"{test_server}/api/login", json={"password": "testuser"})
    token = r.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(f"{test_server}/api/scrape/company/status", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert data.get("status") == "idle"
    assert data.get("phase") == "Idle"


def test_company_scraper_post_requires_admin(test_server):
    r = requests.post(f"{test_server}/api/login", json={"password": "testuser"})
    token = r.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.post(
        f"{test_server}/api/scrape/company",
        json={"input": "ExampleCo"},
        headers=headers,
    )
    assert r.status_code == 403


def test_scrape_runs_status_endpoints_auth(test_server):
    r = requests.get(f"{test_server}/api/scrape/status")
    assert r.status_code == 401
    r = requests.get(f"{test_server}/api/scrape/active")
    assert r.status_code == 401
    r = requests.get(f"{test_server}/api/scrape/status/00000000-0000-0000-0000-000000000001")
    assert r.status_code == 401

    r = requests.post(f"{test_server}/api/login", json={"password": "testuser"})
    token = r.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(f"{test_server}/api/scrape/status", headers=headers)
    assert r.status_code == 200
    assert "runs" in r.json()
    r = requests.get(f"{test_server}/api/scrape/active", headers=headers)
    assert r.status_code == 200
    assert "runs" in r.json()
