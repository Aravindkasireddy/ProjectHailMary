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

    # Force reload of the server module to clean up module-level paths
    if "dashboard_server" in sys.modules:
        importlib.reload(sys.modules["dashboard_server"])
    else:
        import dashboard_server

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

def test_multi_tenant_config_isolation(clean_test_server, mock_auth):
    headers_a = mock_auth.headers("admina@example.com", role="admin")
    headers_b = mock_auth.headers("adminb@example.com", role="admin")

    # Save Config for User A
    config_payload_a = {
        "target_titles": ["DevOps Specialist"],
        "scheduler": {"enabled": True, "run_at_hour": 9, "run_at_minute": 30},
        "webhook_url": "https://hooks.slack.com/services/userA"
    }
    r = requests.post(f"{clean_test_server}/api/config", json=config_payload_a, headers=headers_a)
    assert r.status_code == 200
    assert r.json()["success"] is True

    # Save Config for User B
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

def test_multi_tenant_job_isolation(clean_test_server, mock_auth):
    headers_alice = mock_auth.headers("admin_alice@hailmary.ai", role="admin")
    headers_bob = mock_auth.headers("admin_bob@hailmary.ai", role="admin")

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

def test_non_admin_user_privilege_restriction(clean_test_server, mock_auth):
    headers = mock_auth.headers("standard_user@example.com", role="user")

    # GET endpoint (read action) should succeed
    r = requests.get(f"{clean_test_server}/api/config", headers=headers)
    assert r.status_code == 200

    # POST endpoint (mutating action) should be forbidden (403)
    r = requests.post(f"{clean_test_server}/api/config", json={"target_titles": ["Test"]}, headers=headers)
    assert r.status_code == 403
    assert r.json()["success"] is False
