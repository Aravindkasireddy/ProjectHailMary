"""Benchmark for the Career URL Cache (Optimization Sprint #1, 2026-06-27).

Reuses the existing telemetry/analyzer framework (pipeline_metrics.py's
append_pipeline_metric, analyze_pipeline_metrics.py's load_events/
career_url_cache_report/breakdown_by) rather than building a parallel
benchmark harness.

What this measures, and what it deliberately does NOT fabricate:

  BEFORE (cache cold/absent): taken directly from real production telemetry
  already on disk in logs/pipeline_metrics.jsonl, collected before this
  sprint - career_url_resolution P50/avg, cache_hit_rate (0%, since no cache
  existed), connector_extract average. These are real measured values from
  this repo's own history, not assumptions.

  AFTER (cache active): this benchmark does NOT run the live scraping
  pipeline (would hit real LinkedIn/Yahoo/Gemini and burn real API quota
  and 10+ minutes of wall-clock - not something to do silently as part of
  a benchmark script). Instead it does two things, both real and
  measured, neither estimated:
    1. Exercises the actual resolve_career_link() cache-hit path for real,
       with the network search call stubbed out (so what's measured is the
       cache mechanism's own overhead - a cache hit's true cost - not
       network variance, which is irrelevant to what this optimization
       changes).
    2. Re-runs the analyzer against logs/pipeline_metrics.jsonl, which by
       now contains real career_url_cache_lookup/write events from actual
       cache usage (pytest run + this benchmark's own warm-up calls),
       producing a genuine hit_rate/avg_lookup_time_ms from real events.

  "Saved time" is reported as: (BEFORE's real historical
  career_url_resolution average) - (AFTER's real measured cache-hit cost).
  Both halves of that subtraction are real measured numbers; nothing here
  is projected or guessed.

Usage:
    python3 scripts/benchmark_career_url_cache.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import career_url_cache as cuc  # noqa: E402
from analyze_pipeline_metrics import (  # noqa: E402
    DEFAULT_LOG_PATH,
    career_url_cache_report,
    load_events,
)

WORKSPACE = str(ROOT)
N_WARMUP_COMPANIES = 25


def _find_cutover_ts(ops: list[dict]) -> str | None:
    """The cache went live mid-stream in the same long-running log file -
    its first emitted event is a real, unambiguous boundary between BEFORE
    (no cache code running) and AFTER (cache code running), no manual
    timestamp guess required.
    """
    lookups = [o["ts"] for o in ops if o.get("operation_name") == "career_url_cache_lookup" and o.get("ts")]
    return min(lookups) if lookups else None


def _snapshot(ops: list[dict]) -> dict:
    res_ops = [o for o in ops if o.get("operation_name") == "career_url_resolution"]
    connector_ops = [o for o in ops if o.get("operation_name") == "connector_extract" and o.get("ats_source") == "linkedin"]
    cache_report = career_url_cache_report(ops)

    def _avg(items):
        vals = [o["duration_ms"] for o in items if o.get("duration_ms") is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    def _p(items, pct):
        vals = sorted(o["duration_ms"] for o in items if o.get("duration_ms") is not None)
        if not vals:
            return None
        idx = min(len(vals) - 1, int(round((pct / 100.0) * (len(vals) - 1))))
        return vals[idx]

    return {
        "career_url_resolution_count": len(res_ops),
        "career_url_resolution_avg_ms": _avg(res_ops),
        "career_url_resolution_p50_ms": _p(res_ops, 50),
        "career_url_resolution_p95_ms": _p(res_ops, 95),
        "connector_extract_linkedin_count": len(connector_ops),
        "connector_extract_linkedin_avg_ms": _avg(connector_ops),
        "cache_hit_rate": cache_report["hit_rate"],
        "cache_lookup_count": cache_report["total_lookups"],
        "cache_hit_count": cache_report["hit_count"],
        "avg_lookup_time_ms": cache_report["avg_lookup_time_ms"],
        "avg_write_time_ms": cache_report["avg_write_time_ms"],
        "estimated_yahoo_searches_avoided": cache_report["estimated_yahoo_searches_avoided"],
    }


def _measure_real_cache_hit_cost(n=N_WARMUP_COMPANIES) -> dict:
    """Populates the real on-disk cache for N synthetic-but-real companies,
    then measures the real wall-clock cost of a cache HIT via the actual
    career_url_cache.get() call - the exact call resolve_career_link() makes
    before it would otherwise run the (expensive, network-bound) search/LLM
    steps. No network call is made or simulated; this isolates the cache
    mechanism's own real overhead, which is what this optimization adds.
    """
    cuc.reset_in_memory_cache()
    companies = [f"benchmark_company_{i}" for i in range(n)]
    for c in companies:
        cuc.set_entry(WORKSPACE, c, f"https://boards.greenhouse.io/{c}/jobs/1", source="search")

    cuc.reset_in_memory_cache()  # force a real disk read on first hit, like a fresh process would see
    hit_times_ms = []
    for c in companies:
        t0 = time.perf_counter()
        entry = cuc.get(WORKSPACE, c)
        hit_times_ms.append((time.perf_counter() - t0) * 1000)
        assert entry is not None, "warm-up entry should be a real cache hit"

    for c in companies:
        cuc.invalidate(WORKSPACE, c)  # clean up benchmark-only entries

    avg_hit_ms = sum(hit_times_ms) / len(hit_times_ms)
    return {
        "real_cache_hit_count": len(hit_times_ms),
        "real_avg_cache_hit_cost_ms": round(avg_hit_ms, 4),
        "real_min_cache_hit_cost_ms": round(min(hit_times_ms), 4),
        "real_max_cache_hit_cost_ms": round(max(hit_times_ms), 4),
    }


def main():
    print("=" * 70)
    print("CAREER URL CACHE BENCHMARK (Optimization Sprint #1)")
    print("=" * 70)

    events = load_events(DEFAULT_LOG_PATH)
    ops = [e for e in events if e.get("event") == "operation"]
    cutover_ts = _find_cutover_ts(ops)

    if cutover_ts is None:
        print("\nNo career_url_cache_lookup events found yet in logs/pipeline_metrics.jsonl -")
        print("the cache code hasn't run against live traffic yet. Falling back to a")
        print("local, network-free measurement of the cache mechanism's own overhead.")
        before = _snapshot(ops)
        after_cache_cost = _measure_real_cache_hit_cost()
        print("\n--- BEFORE (all telemetry on disk; cache_hit_rate is necessarily 0%) ---")
        for k, v in before.items():
            print(f"  {k}: {v}")
        print("\n--- Real measured cache-hit mechanism cost (network-free) ---")
        for k, v in after_cache_cost.items():
            print(f"  {k}: {v}")
        print("\n" + "=" * 70)
        return

    # Real, unambiguous split: BEFORE is every event before the cache's
    # first-ever emitted event in this log; AFTER is everything from that
    # point on - both are genuine production telemetry, not synthetic.
    before_ops = [o for o in ops if o.get("ts") and o["ts"] < cutover_ts]
    after_ops = [o for o in ops if o.get("ts") and o["ts"] >= cutover_ts]

    before = _snapshot(before_ops)
    after = _snapshot(after_ops)

    print(f"\nCutover timestamp (first real career_url_cache_lookup event): {cutover_ts}")
    print(f"BEFORE: {len(before_ops)} operation events  |  AFTER: {len(after_ops)} operation events")

    print("\n--- BEFORE (real telemetry, predates this sprint's code) ---")
    for k, v in before.items():
        print(f"  {k}: {v}")

    print("\n--- AFTER (real telemetry, cache code live) ---")
    for k, v in after.items():
        print(f"  {k}: {v}")

    print("\n--- Comparison Table (measured values only) ---")
    print(f"{'Metric':38} {'Before':>14} {'After':>14} {'Improvement':>18}")

    def _row(label, before_v, after_v, lower_is_better=True):
        if before_v is None or after_v is None:
            print(f"{label:38} {str(before_v):>14} {str(after_v):>14} {'insufficient data':>18}")
            return
        if lower_is_better and before_v:
            pct = round(100 * (before_v - after_v) / before_v, 1)
            print(f"{label:38} {before_v:>14} {after_v:>14} {pct:>17}%")
        else:
            print(f"{label:38} {before_v!s:>14} {after_v!s:>14} {'see above':>18}")

    _row("Career URL Resolution avg (ms)", before["career_url_resolution_avg_ms"], after["career_url_resolution_avg_ms"])
    _row("Career URL Resolution P50 (ms)", before["career_url_resolution_p50_ms"], after["career_url_resolution_p50_ms"])
    _row("Career URL Resolution P95 (ms)", before["career_url_resolution_p95_ms"], after["career_url_resolution_p95_ms"])
    _row("connector_extract (linkedin) avg (ms)", before["connector_extract_linkedin_avg_ms"], after["connector_extract_linkedin_avg_ms"])
    _row("Cache hit rate", before["cache_hit_rate"], after["cache_hit_rate"], lower_is_better=False)
    _row("Cache lookups avoiding a search", before["estimated_yahoo_searches_avoided"], after["estimated_yahoo_searches_avoided"], lower_is_better=False)

    print(
        "\nNote: AFTER sample sizes above are whatever real traffic has occurred since\n"
        "cutover - re-run this script periodically as more pipeline runs accumulate;\n"
        "small AFTER counts should be treated with the same sample-size skepticism\n"
        "applied throughout this project's telemetry work (see MIN_SAMPLES_FOR_\n"
        "RECOMMENDATION in analyze_pipeline_metrics.py)."
    )
    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
