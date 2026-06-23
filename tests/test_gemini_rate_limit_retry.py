"""Tests for the single-Gemini-key rate-limit retry path in classify_and_save.py.

Real incident (2026-06-23): production only has one GEMINI_API_KEY configured.
On a 429/quota error, the old code immediately tried rotate_gemini_key(), which
always fails instantly with one key, and the whole classification attempt gave
up with zero backoff - even though the existing exponential-backoff retry loop
was sitting right there, just unreachable from the quota-error branch. Fixed
so a failed rotation now backs off and retries the same key like any other
transient error, instead of skipping straight to keyword-only fallback.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))


@pytest.fixture
def single_key_env(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "single-test-key")
    monkeypatch.delenv("GEMINI_API_KEY_2", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY_3", raising=False)

    import classify_and_save as c

    # Reset module-level rotation state left over from other tests/processes.
    monkeypatch.setattr(c, "current_key_index", 0)

    # classify_job_with_gemini reads the classifier prompt from disk first;
    # point WORKSPACE at a tmp dir with a minimal real prompt file so it
    # doesn't bail out before ever reaching the Gemini call.
    prompt_file = tmp_path / "Job_classifier_prompt.txt"
    prompt_file.write_text("Return JSON only.")
    monkeypatch.setattr(c, "WORKSPACE", tmp_path)

    monkeypatch.setattr(c.time, "sleep", lambda *_a, **_k: None)  # don't actually wait in tests
    return c


def test_single_key_quota_error_backs_off_and_retries_same_key(single_key_env, monkeypatch):
    c = single_key_env
    call_count = {"n": 0}

    class _FakeModel:
        def generate_content(self, *_a, **_k):
            call_count["n"] += 1
            raise RuntimeError("429 Resource has been exhausted (quota)")

    monkeypatch.setattr(c.genai, "configure", lambda **_k: None)
    monkeypatch.setattr(c.genai, "GenerativeModel", lambda *_a, **_k: _FakeModel())

    job = {"job_title": "DevOps Engineer", "job_description": "Manage CI/CD pipelines."}
    result = c.classify_job_with_gemini(job)

    # Every attempt fails, so classification ultimately gives up (returns None / falls
    # back) - but the key assertion is that it actually RETRIED the same key 3 times
    # with backoff instead of bailing out after a single failed rotation attempt.
    assert call_count["n"] == 3
    assert result is None


def test_single_key_non_quota_error_still_retries_as_before(single_key_env, monkeypatch):
    c = single_key_env
    call_count = {"n": 0}

    class _FakeModel:
        def generate_content(self, *_a, **_k):
            call_count["n"] += 1
            raise RuntimeError("transient network hiccup")

    monkeypatch.setattr(c.genai, "configure", lambda **_k: None)
    monkeypatch.setattr(c.genai, "GenerativeModel", lambda *_a, **_k: _FakeModel())

    job = {"job_title": "DevOps Engineer", "job_description": "Manage CI/CD pipelines."}
    c.classify_job_with_gemini(job)

    assert call_count["n"] == 3  # unchanged pre-existing behavior for non-quota errors
