"""
Thin Redis-backed cache for load_all_jobs().

Falls back to an in-memory dict transparently when Redis is unreachable or
REDIS_URL is not set, so local dev without a Redis container still works.

TTL: REDIS_CACHE_TTL_SECONDS env var (default 10s — same as the old
     wall-clock-bucket approach).
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, List, Optional

# In-memory fallback used when Redis is unavailable
_mem_data: dict[str, Any] = {}
_mem_expiry: dict[str, float] = {}

_redis_client = None
_redis_ok = False  # tracks whether last Redis op succeeded

TTL = int(os.environ.get("REDIS_CACHE_TTL_SECONDS", "10"))
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")


def _client():
    global _redis_client, _redis_ok
    if _redis_client is not None:
        return _redis_client
    try:
        import redis as _redis
        _redis_client = _redis.from_url(REDIS_URL, socket_connect_timeout=1, socket_timeout=1, decode_responses=True)
        _redis_client.ping()
        _redis_ok = True
        print(f"[redis_cache] Connected to {REDIS_URL}")
    except Exception as e:
        print(f"[redis_cache] Redis unavailable ({e}) — using in-memory fallback")
        _redis_client = None
        _redis_ok = False
    return _redis_client


def _key(email: str) -> str:
    return f"jobs_cache:{email}"


def get(email: str) -> Optional[List]:
    """Return cached job list for email, or None on miss/expiry."""
    r = _client()
    if r is not None:
        try:
            raw = r.get(_key(email))
            return json.loads(raw) if raw else None
        except Exception as e:
            print(f"[redis_cache] get error: {e}")

    # In-memory fallback
    expiry = _mem_expiry.get(email)
    if expiry and time.time() < expiry:
        return _mem_data.get(email)
    return None


def set(email: str, jobs: list, ttl: int = TTL) -> None:
    """Store job list for email with TTL seconds."""
    r = _client()
    if r is not None:
        try:
            r.setex(_key(email), ttl, json.dumps(jobs, default=str))
            return
        except Exception as e:
            print(f"[redis_cache] set error: {e}")

    # In-memory fallback
    _mem_data[email] = jobs
    _mem_expiry[email] = time.time() + ttl


def invalidate(email: str) -> None:
    """Delete cached entry for email (called after writes/overrides)."""
    r = _client()
    if r is not None:
        try:
            r.delete(_key(email))
        except Exception as e:
            print(f"[redis_cache] invalidate error: {e}")

    _mem_data.pop(email, None)
    _mem_expiry.pop(email, None)
