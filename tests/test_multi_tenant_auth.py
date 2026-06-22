import os
import sys
import time
import threading
import socket
import pytest
import requests
import importlib
from http.server import ThreadingHTTPServer

def get_free_port():
    s = socket.socket()
    s.bind(('', 0))
    port = s.getsockname()[1]
    s.close()
    return port

@pytest.fixture
def clean_test_server(tmp_path):
    # Configure env for test to use clean temp workspace root
    os.environ["JOBSEARCH_ROOT"] = str(tmp_path)
    os.environ["ADMIN_PASSWORD"] = "testadmin"
    os.environ["USER_PASSWORD"] = "testuser"
    
    # Force reload of server and users-db modules to clean up module-level paths/db schemas
    if "dashboard_server" in sys.modules:
        importlib.reload(sys.modules["dashboard_server"])
    else:
        import dashboard_server

    if "user_auth_db" in sys.modules:
        importlib.reload(sys.modules["user_auth_db"])

    import dashboard_server
    
    port = get_free_port()
    server = ThreadingHTTPServer(('127.0.0.1', port), dashboard_server.DashboardHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    
    # Give it a second to start
    time.sleep(0.5)
    
    yield f"http://127.0.0.1:{port}"
    
    server.shutdown()
    server.server_close()

def test_multi_tenant_registration_and_login(clean_test_server):
    # Register User A (Admin)
    r = requests.post(f"{clean_test_server}/api/register", json={
        "email": "admina@example.com",
        "password": "passwordA"
    })
    assert r.status_code == 200
    assert r.json()["success"] is True

    # Register User B (Admin)
    r = requests.post(f"{clean_test_server}/api/register", json={
        "email": "adminb@example.com",
        "password": "passwordB"
    })
    assert r.status_code == 200
    assert r.json()["success"] is True

    # Try duplicate registration
    r = requests.post(f"{clean_test_server}/api/register", json={
        "email": "admina@example.com",
        "password": "newpassword"
    })
    assert r.status_code == 400
    assert r.json()["success"] is False

    # Login User A
    r = requests.post(f"{clean_test_server}/api/login", json={
        "email": "admina@example.com",
        "password": "passwordA"
    })
    assert r.status_code == 200
    data_a = r.json()
    assert data_a["success"] is True
    assert data_a["email"] == "admina@example.com"
    token_a = data_a["token"]

    # Login User B
    r = requests.post(f"{clean_test_server}/api/login", json={
        "email": "adminb@example.com",
        "password": "passwordB"
    })
    assert r.status_code == 200
    data_b = r.json()
    assert data_b["success"] is True
    assert data_b["email"] == "adminb@example.com"
    token_b = data_b["token"]

    # Save Config for User A
    headers_a = {"Authorization": f"Bearer {token_a}"}
    config_payload_a = {
        "target_titles": ["DevOps Specialist"],
        "scheduler": {"enabled": True, "run_at_hour": 9, "run_at_minute": 30},
        "webhook_url": "https://hooks.slack.com/services/userA"
    }
    r = requests.post(f"{clean_test_server}/api/config", json=config_payload_a, headers=headers_a)
    assert r.status_code == 200
    assert r.json()["success"] is True

    # Save Config for User B
    headers_b = {"Authorization": f"Bearer {token_b}"}
    config_payload_b = {
        "target_titles": ["SRE Manager"],
        "scheduler": {"enabled": False, "run_at_hour": 18, "run_at_minute": 0},
        "webhook_url": "https://hooks.slack.com/services/userB"
    }
    r = requests.post(f"{clean_test_server}/api/config", json=config_payload_b, headers=headers_b)
    assert r.status_code == 200
    assert r.json()["success"] is True

    # Get Config for User A and verify
    r = requests.get(f"{clean_test_server}/api/config", headers=headers_a)
    assert r.status_code == 200
    cfg_a = r.json()
    assert cfg_a["target_titles"] == ["DevOps Specialist"]
    assert cfg_a["webhook_url"] == "https://hooks.slack.com/services/userA"

    # Get Config for User B and verify
    r = requests.get(f"{clean_test_server}/api/config", headers=headers_b)
    assert r.status_code == 200
    cfg_b = r.json()
    assert cfg_b["target_titles"] == ["SRE Manager"]
    assert cfg_b["webhook_url"] == "https://hooks.slack.com/services/userB"

def test_multi_tenant_job_isolation(clean_test_server):
    # Register and login two test users (admins to allow write operations)
    r = requests.post(f"{clean_test_server}/api/register", json={"email": "admin_alice@hailmary.ai", "password": "alicepassword"})
    r = requests.post(f"{clean_test_server}/api/login", json={"email": "admin_alice@hailmary.ai", "password": "alicepassword"})
    token_alice = r.json()["token"]
    headers_alice = {"Authorization": f"Bearer {token_alice}"}

    r = requests.post(f"{clean_test_server}/api/register", json={"email": "admin_bob@hailmary.ai", "password": "bobpassword"})
    r = requests.post(f"{clean_test_server}/api/login", json={"email": "admin_bob@hailmary.ai", "password": "bobpassword"})
    token_bob = r.json()["token"]
    headers_bob = {"Authorization": f"Bearer {token_bob}"}

    # Override/Create a job decision for Alice
    job_payload_alice = {
        "job_url": "https://example.com/alice-exclusive-job",
        "job_title": "Alice Lead SRE",
        "company_name": "Alice Corp",
        "requirement_id": "ALICE-REQ-01",
        "apply_decision": "APPLY",
        "strongest_label": "DevOps Engineer",
        "confidence_score": 98,
        "rationale": "Matches SRE filters perfectly."
    }
    r = requests.post(f"{clean_test_server}/api/override", json=job_payload_alice, headers=headers_alice)
    assert r.status_code == 200
    assert r.json()["success"] is True

    # Alice fetches her jobs
    r = requests.get(f"{clean_test_server}/api/jobs", headers=headers_alice)
    assert r.status_code == 200
    jobs_alice = r.json()
    assert len(jobs_alice) == 1
    assert jobs_alice[0]["job_url"] == "https://example.com/alice-exclusive-job"

    # Bob fetches his jobs (should be empty, entirely isolated!)
    r = requests.get(f"{clean_test_server}/api/jobs", headers=headers_bob)
    assert r.status_code == 200
    jobs_bob = r.json()
    assert len(jobs_bob) == 0

    # Bob creates his own decision for the SAME job URL
    job_payload_bob = {
        "job_url": "https://example.com/alice-exclusive-job",
        "job_title": "Bob Lead SRE",
        "company_name": "Bob Corp",
        "requirement_id": "ALICE-REQ-01",
        "apply_decision": "APPLY",
        "strongest_label": "Site Reliability Engineer (SRE)",
        "confidence_score": 92,
        "rationale": "Bob also likes SRE roles."
    }
    r = requests.post(f"{clean_test_server}/api/override", json=job_payload_bob, headers=headers_bob)
    assert r.status_code == 200
    assert r.json()["success"] is True

    # Alice fetches her jobs again (her title remains original)
    r = requests.get(f"{clean_test_server}/api/jobs", headers=headers_alice)
    assert r.status_code == 200
    jobs_alice = r.json()
    assert len(jobs_alice) == 1
    assert jobs_alice[0]["job_title"] == "Alice Lead SRE"

    # Bob fetches his jobs again (his title matches Bob's config)
    r = requests.get(f"{clean_test_server}/api/jobs", headers=headers_bob)
    assert r.status_code == 200
    jobs_bob = r.json()
    assert len(jobs_bob) == 1
    assert jobs_bob[0]["job_title"] == "Bob Lead SRE"

def test_non_admin_user_privilege_restriction(clean_test_server):
    # Register standard read-only user
    r = requests.post(f"{clean_test_server}/api/register", json={"email": "standard_user@example.com", "password": "userpass"})
    assert r.status_code == 200
    
    r = requests.post(f"{clean_test_server}/api/login", json={"email": "standard_user@example.com", "password": "userpass"})
    token = r.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    
    # GET endpoint (read action) should succeed
    r = requests.get(f"{clean_test_server}/api/config", headers=headers)
    assert r.status_code == 200
    
    # POST endpoint (mutating action) should be forbidden (403)
    r = requests.post(f"{clean_test_server}/api/config", json={"target_titles": ["Test"]}, headers=headers)
    assert r.status_code == 403
    assert r.json()["success"] is False
