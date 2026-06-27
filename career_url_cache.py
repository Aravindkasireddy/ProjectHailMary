"""Career URL Cache (Optimization Sprint #1, 2026-06-27).

Caches resolve_career_link()'s expensive Step 2 (search) / Step 3 (LLM)
career-board URL resolution by company. Measured telemetry showed
career_url_resolution averaging 1532ms/call on LinkedIn with heavy
per-company repetition (e.g. Netflix n=69, Hyperproof n=67, Tessera Labs
n=78 connector_extract calls in one audit window) and zero caching -
every job re-discovered the same company's board URL from scratch.

Design notes
------------
- Primary key is the normalized company name ONLY (no job-title key is
  actually used to look anything up - see below). Step 2/3 of
  resolve_career_link() resolve a company's official careers/ATS-board URL
  (e.g. boards.greenhouse.io/acme), which is the same regardless of which
  job title triggered the lookup - that's exactly the redundant work the
  telemetry identified.
- A secondary (company + job_title) key is intentionally NOT used for cache
  lookups. The only place a job title could legitimately need a different
  URL is Step 1 of resolve_career_link() (direct ATS links scraped from that
  specific job's JD/HTML text) - and Step 1 is local regex/string matching
  with no network or LLM call, so it was never measured as slow and isn't
  cached here. Caching at title granularity would fragment the cache and
  reduce the hit rate for exactly the case telemetry says is expensive, with
  no measured benefit - so this module always prefers the simpler
  company-level cache, per the brief.
- Storage is a single JSON file (logs/career_url_cache.json), matching this
  repo's existing convention for small, infrequently-written state
  (config.json, policy_config.json, logs/apify_usage.json). No new
  infrastructure (SQLite/Redis) is justified for what is, at current scale,
  a few hundred company entries updated a handful of times per pipeline run.
"""
import json
import os
import threading
import time
from pathlib import Path

_LOCK = threading.Lock()
_CACHE = None  # in-memory mirror of the JSON file, lazy-loaded
_CACHE_PATH = None  # tracks which workspace path _CACHE was loaded for

DEFAULT_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days

_ATS_DOMAIN_HINTS = (
    ("greenhouse.io", "greenhouse"),
    ("lever.co", "lever"),
    ("ashbyhq.com", "ashby"),
    ("myworkdayjobs.com", "workday"),
    ("workdayjobs.com", "workday"),
    ("smartrecruiters.com", "smartrecruiters"),
    ("workable.com", "workable"),
)


def ttl_seconds():
    """Configurable via the CAREER_URL_CACHE_TTL_SECONDS env var. Default is
    7 days: company ATS-board URLs change rarely (companies don't migrate
    Greenhouse -> Lever weekly), but config.json's target_companies slugs
    are already known to go dead over weeks/months (CLAUDE.md, 2026-06-22
    audit: 16 dead slugs found). A week-long TTL bounds staleness to roughly
    that timescale without re-resolving on every single run.
    """
    env_val = os.environ.get("CAREER_URL_CACHE_TTL_SECONDS")
    if env_val:
        try:
            return int(env_val)
        except ValueError:
            pass
    return DEFAULT_TTL_SECONDS


def is_disabled():
    """Cache bypass for debugging: CAREER_URL_CACHE_DISABLE=1."""
    return os.environ.get("CAREER_URL_CACHE_DISABLE", "").strip().lower() in ("1", "true", "yes")


def infer_ats_type(url):
    if not url:
        return None
    low = url.lower()
    for domain, ats in _ATS_DOMAIN_HINTS:
        if domain in low:
            return ats
    return None


def _cache_path(workspace_dir):
    return Path(workspace_dir) / "logs" / "career_url_cache.json"


def _load(workspace_dir):
    global _CACHE, _CACHE_PATH
    path = _cache_path(workspace_dir)
    if _CACHE is not None and _CACHE_PATH == path:
        return _CACHE
    cache = {}
    try:
        if path.exists():
            cache = json.loads(path.read_text())
    except Exception:
        cache = {}
    _CACHE = cache
    _CACHE_PATH = path
    return _CACHE


def _save(workspace_dir):
    path = _cache_path(workspace_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_CACHE, indent=2, sort_keys=True))
    except Exception:
        pass  # cache writes are best-effort; never break the pipeline


def get(workspace_dir, normalized_company_key):
    """Returns the cache entry dict on a live (non-expired, non-bypassed)
    hit, else None. Never raises - any failure here must fall through to
    the existing (pre-cache) resolution path unchanged.
    """
    if not normalized_company_key or is_disabled():
        return None
    try:
        with _LOCK:
            cache = _load(workspace_dir)
            entry = cache.get(normalized_company_key)
            if not entry:
                return None
            if time.time() >= entry.get("expiration_time", 0):
                return None
            return entry
    except Exception:
        return None


def set_entry(workspace_dir, normalized_company_key, career_url, source="search", validation_status="unverified"):
    """Writes/overwrites the cache entry for a company. Called whenever
    Step 2 (search) or Step 3 (LLM) freshly resolves a URL - this is the
    "automatic overwrite when a new URL is discovered" behavior.
    """
    if not normalized_company_key or not career_url or is_disabled():
        return
    try:
        now = time.time()
        entry = {
            "career_url": career_url,
            "ats_type": infer_ats_type(career_url),
            "timestamp": now,
            "expiration_time": now + ttl_seconds(),
            "validation_status": validation_status,
            "source": source,
        }
        with _LOCK:
            cache = _load(workspace_dir)
            cache[normalized_company_key] = entry
            _save(workspace_dir)
    except Exception:
        pass


def invalidate(workspace_dir, normalized_company_key):
    """Explicit invalidation. Used when a cached or freshly-resolved URL
    fails the existing downstream live-URL validation check, so a known-bad
    entry is never served again. Never raises.
    """
    if not normalized_company_key:
        return False
    try:
        with _LOCK:
            cache = _load(workspace_dir)
            if normalized_company_key in cache:
                del cache[normalized_company_key]
                _save(workspace_dir)
                return True
            return False
    except Exception:
        return False


def reset_in_memory_cache():
    """Test helper: forces the next get/set/invalidate to reload from disk
    instead of reusing a previous process's in-memory mirror.
    """
    global _CACHE, _CACHE_PATH
    _CACHE = None
    _CACHE_PATH = None
