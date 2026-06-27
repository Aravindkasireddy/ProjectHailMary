"""Analyze logs/pipeline_metrics.jsonl and report on pipeline performance.

Reads the "operation" events written by scripts/pipeline_metrics.py's
record_operation() (plus the legacy "pipeline_step"/"playwright_fetch"
events for backward compatibility) and produces:

  - Overall summary: P50/P90/P95/P99 operation latency
  - Breakdown by stage / ats_source / connector / company
  - Top 20 slowest operations by cumulative wall-clock time
  - Throughput: jobs/hour, jobs/sec, avg seconds/job
  - Error analysis: top failure reasons
  - Recommendations: bottlenecks ranked by cumulative wall-clock impact,
    with an estimated max theoretical speedup - but ONLY for items with a
    real, sufficiently-large sample size. This script does not speculate;
    see the 2026-06-27 incident where the top-ranked "optimization" from a
    code-reading-only audit (reuse one Playwright browser across threads)
    turned out to break 83.6% of calls once actually tested. Recommendations
    here are gated on having enough telemetry to trust, not just a plausible
    story.

Usage:
    python3 scripts/analyze_pipeline_metrics.py [--file PATH] [--min-samples N]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOG_PATH = ROOT / "logs" / "pipeline_metrics.jsonl"

# Below this many samples, a recommendation is not made - just reported as
# "insufficient data" - matching the rigor established in this session's
# manual analysis (a 49-sample Playwright timing set was explicitly flagged
# as too small to act on without more data).
MIN_SAMPLES_FOR_RECOMMENDATION = 20


def load_events(path: Path) -> list[dict]:
    events = []
    if not path.exists():
        return events
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except Exception:
                continue
    return events


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * (pct / 100.0)
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def overall_summary(ops: list[dict]) -> dict:
    durations = [o.get("duration_ms", 0) for o in ops]
    return {
        "count": len(ops),
        "p50_ms": round(percentile(durations, 50), 1),
        "p90_ms": round(percentile(durations, 90), 1),
        "p95_ms": round(percentile(durations, 95), 1),
        "p99_ms": round(percentile(durations, 99), 1),
        "total_s": round(sum(durations) / 1000.0, 1),
    }


def breakdown_by(ops: list[dict], key: str) -> list[tuple[str, dict]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for o in ops:
        v = o.get(key)
        if v:
            groups[v].append(o)
    result = []
    for name, items in groups.items():
        durations = [i.get("duration_ms", 0) for i in items]
        successes = sum(1 for i in items if i.get("success"))
        result.append((
            name,
            {
                "count": len(items),
                "total_s": round(sum(durations) / 1000.0, 1),
                "avg_ms": round(sum(durations) / len(items), 1) if items else 0,
                "success_rate": round(successes / len(items), 3) if items else None,
            },
        ))
    result.sort(key=lambda x: x[1]["total_s"], reverse=True)
    return result


def slowest_operations(ops: list[dict], n: int = 20) -> list[tuple[str, dict]]:
    return breakdown_by(ops, "operation_name")[:n]


# Sub-operations that live inside connector_extract's waterfall, per
# connector (ats_source). Order matters for display - roughly the order
# each step happens for a LinkedIn job, which is the worst case; other
# connectors only populate a subset of these (e.g. Greenhouse never does
# career_url_resolution/llm_fallback, since it's already a direct ATS URL).
_WATERFALL_SUBOPS = (
    "company_discovery",
    "ats_detection",
    "http_request",
    "browser_launch",
    "browser_context_create",
    "page_navigation",
    "wait_for_selector",
    "html_parsing",
    "json_parsing",
    "career_url_resolution",
    "yahoo_search",
    "duckduckgo_search",
    "llm_fallback",
    "llm_extraction",
    "live_url_validation",
    "connector_extract",
)


def connector_waterfall(ops: list[dict]) -> dict[str, list[dict]]:
    """For each connector (ats_source), break down cumulative time by
    sub-operation, in waterfall order - this is connector_extract's 60% of
    total time, subdivided into the steps that actually make it up.
    """
    by_connector: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for o in ops:
        connector = o.get("ats_source")
        if not connector:
            continue
        by_connector[connector][o.get("operation_name", "unknown")].append(o.get("duration_ms", 0))

    waterfalls: dict[str, list[dict]] = {}
    for connector, op_durations in by_connector.items():
        rows = []
        for op_name in _WATERFALL_SUBOPS:
            if op_name not in op_durations:
                continue
            durations = op_durations[op_name]
            rows.append({
                "operation": op_name,
                "count": len(durations),
                "total_ms": sum(durations),
                "avg_ms": round(sum(durations) / len(durations), 1),
                "p50_ms": round(percentile(durations, 50), 1),
                "p90_ms": round(percentile(durations, 90), 1),
                "p95_ms": round(percentile(durations, 95), 1),
                "p99_ms": round(percentile(durations, 99), 1),
            })
        # Anything not in the known waterfall order (future sub-ops) still
        # gets reported, just appended after the known ones.
        for op_name, durations in op_durations.items():
            if op_name in _WATERFALL_SUBOPS:
                continue
            rows.append({
                "operation": op_name,
                "count": len(durations),
                "total_ms": sum(durations),
                "avg_ms": round(sum(durations) / len(durations), 1),
                "p50_ms": round(percentile(durations, 50), 1),
                "p90_ms": round(percentile(durations, 90), 1),
                "p95_ms": round(percentile(durations, 95), 1),
                "p99_ms": round(percentile(durations, 99), 1),
            })
        waterfalls[connector] = rows
    return waterfalls


def throughput(ops: list[dict]) -> dict:
    total_jobs = sum(o.get("jobs_processed") or 0 for o in ops)
    total_s = sum(o.get("duration_ms", 0) for o in ops) / 1000.0
    if total_s <= 0 or total_jobs <= 0:
        return {"jobs_per_hour": 0, "jobs_per_sec": 0, "avg_seconds_per_job": None}
    return {
        "jobs_per_hour": round(total_jobs / total_s * 3600, 1),
        "jobs_per_sec": round(total_jobs / total_s, 4),
        "avg_seconds_per_job": round(total_s / total_jobs, 2),
    }


def aggregate_averages(ops: list[dict]) -> dict:
    """Cross-cutting averages requested explicitly: per-job time split by
    outcome, retries, cache hit rate, bytes downloaded, requests/job, cost/job,
    time per connector, time per company. Only computed from fields that are
    actually present on real events - returns None for any average where the
    underlying field was never recorded (no estimating).
    """
    connector_jobs = [o for o in ops if o.get("operation_name") == "connector_extract"]
    success_jobs = [o for o in connector_jobs if o.get("success")]
    failed_jobs = [o for o in connector_jobs if not o.get("success")]

    def _avg(items, key_fn):
        vals = [v for v in (key_fn(o) for o in items) if v is not None]
        return round(sum(vals) / len(vals), 3) if vals else None

    http_ops = [o for o in ops if o.get("operation_name") == "http_request"]
    llm_ops = [o for o in ops if (o.get("metadata") or {}).get("llm_used")]
    cache_ops = [o for o in ops if (o.get("metadata") or {}).get("cache_hit") is not None]

    return {
        "avg_time_per_successful_job_ms": _avg(success_jobs, lambda o: o.get("duration_ms")),
        "avg_time_per_rejected_job_ms": _avg(failed_jobs, lambda o: o.get("duration_ms")),
        "successful_job_count": len(success_jobs),
        "rejected_job_count": len(failed_jobs),
        "avg_retries": _avg(ops, lambda o: (o.get("metadata") or {}).get("retry_count")),
        "avg_cache_hit_rate": (
            round(sum(1 for o in cache_ops if (o.get("metadata") or {}).get("cache_hit")) / len(cache_ops), 3)
            if cache_ops else None
        ),
        "avg_bytes_downloaded": _avg(http_ops, lambda o: (o.get("metadata") or {}).get("bytes_downloaded")),
        "avg_requests_per_job": _avg(http_ops, lambda o: (o.get("metadata") or {}).get("request_count")),
        "avg_cost_usd_per_llm_call_at_list_price": _avg(llm_ops, lambda o: (o.get("metadata") or {}).get("estimated_cost_usd_at_list_price")),
        "total_cost_usd_at_list_price": round(
            sum((o.get("metadata") or {}).get("estimated_cost_usd_at_list_price") or 0 for o in llm_ops), 4
        ) if llm_ops else None,
        "llm_call_count": len(llm_ops),
        "http_request_count": len(http_ops),
    }


def career_url_cache_report(ops: list[dict]) -> dict:
    """Career URL Cache metrics (Optimization Sprint #1, 2026-06-27).

    Only reports quantities derivable directly from the cache's own emitted
    events (career_url_cache_lookup / career_url_cache_write /
    career_url_cache_invalidate) - never from speculative counterfactuals.

    Deliberately NOT computed here, and why:
    - "Average Saved Time": yahoo_search/duckduckgo_search are also called
      from the unrelated bulk-discovery search phase (search_and_scrape_for_
      keyword), not just from the career-resolution path this cache
      shortcuts - so a single-run composite of "search+LLM time avoided"
      would mix in unrelated traffic. The honest way to measure saved time
      is a direct before/after comparison of career_url_resolution latency
      with the cache cold vs warm, which is what the benchmark script
      (scripts/benchmark_career_url_cache.py) does instead.
    - "Estimated LLM Calls Avoided" / "Estimated DuckDuckGo Searches
      Avoided": both are reached only conditionally (LLM fallback only after
      search fails; DuckDuckGo only after Yahoo fails), so whether a given
      avoided lookup would have reached either is an unknowable
      counterfactual - reporting a number here would be exactly the kind of
      estimate this task explicitly forbids.
    - "Estimated Yahoo Searches Avoided" IS reported below, because Yahoo is
      unconditionally the first call inside search_for_job_url() - every
      cache hit deterministically avoids exactly one Yahoo search, by
      construction of the code, not by estimation.
    """
    lookups = [o for o in ops if o.get("operation_name") == "career_url_cache_lookup"]
    writes = [o for o in ops if o.get("operation_name") == "career_url_cache_write"]
    invalidations = [o for o in ops if o.get("operation_name") == "career_url_cache_invalidate"]

    hits = [o for o in lookups if (o.get("metadata") or {}).get("cache_hit") is True]
    misses = [o for o in lookups if (o.get("metadata") or {}).get("cache_hit") is False]

    def _avg(items, key_fn):
        vals = [v for v in (key_fn(o) for o in items) if v is not None]
        return round(sum(vals) / len(vals), 3) if vals else None

    def _top_companies(items, n=10):
        counts: dict[str, int] = defaultdict(int)
        for o in items:
            c = o.get("company")
            if c:
                counts[c] += 1
        return sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:n]

    total_lookups = len(lookups)
    invalidation_reasons: dict[str, int] = defaultdict(int)
    for o in invalidations:
        reason = (o.get("metadata") or {}).get("cache_invalidation_reason") or "unspecified"
        invalidation_reasons[reason] += 1

    return {
        "total_lookups": total_lookups,
        "hit_count": len(hits),
        "miss_count": len(misses),
        "hit_rate": round(len(hits) / total_lookups, 3) if total_lookups else None,
        "miss_rate": round(len(misses) / total_lookups, 3) if total_lookups else None,
        "avg_lookup_time_ms": _avg(lookups, lambda o: o.get("duration_ms")),
        "avg_write_time_ms": _avg(writes, lambda o: o.get("duration_ms")),
        "write_count": len(writes),
        "estimated_yahoo_searches_avoided": len(hits),  # deterministic, not an estimate - see docstring
        "avg_cache_age_s_on_hit": _avg(hits, lambda o: (o.get("metadata") or {}).get("cache_age_s")),
        "avg_ttl_remaining_s_on_hit": _avg(hits, lambda o: (o.get("metadata") or {}).get("ttl_remaining_s")),
        "invalidation_count": len(invalidations),
        "invalidation_reasons": dict(invalidation_reasons),
        "top_cached_companies": _top_companies(writes),
        "top_cache_miss_companies": _top_companies(misses),
    }


def error_analysis(ops: list[dict]) -> list[tuple[str, int]]:
    reasons: dict[str, int] = defaultdict(int)
    for o in ops:
        if not o.get("success") and o.get("exception"):
            # Use the exception type (before the first ":") as the bucket key.
            reason = str(o["exception"]).split(":")[0].strip()
            reasons[reason] += 1
        elif not o.get("success"):
            reasons[f"{o.get('operation_name', 'unknown')}_failure"] += 1
    return sorted(reasons.items(), key=lambda x: x[1], reverse=True)


def recommendations(ops: list[dict], min_samples: int) -> list[dict]:
    """Rank operations by cumulative wall-clock impact. Only recommend
    speedups for operations with >= min_samples observations - everything
    else is reported as "insufficient data", not guessed.
    """
    by_op = breakdown_by(ops, "operation_name")
    total_time_s = sum(d["total_s"] for _, d in by_op) or 1.0

    recs = []
    for name, d in by_op:
        share = d["total_s"] / total_time_s
        if d["count"] < min_samples:
            recs.append({
                "operation": name,
                "cumulative_wall_clock_s": d["total_s"],
                "share_of_measured_time": round(share, 3),
                "sample_size": d["count"],
                "recommendation": "INSUFFICIENT DATA - do not act on this yet",
                "max_theoretical_speedup": None,
            })
            continue

        # Max theoretical speedup: if this operation were instant (duration=0),
        # how much total measured time would disappear. This is a ceiling, not
        # a promise - it assumes perfect elimination, which is never realistic.
        max_speedup_pct = round(share * 100, 1)
        recs.append({
            "operation": name,
            "cumulative_wall_clock_s": d["total_s"],
            "share_of_measured_time": round(share, 3),
            "sample_size": d["count"],
            "avg_ms": d["avg_ms"],
            "success_rate": d["success_rate"],
            "max_theoretical_speedup_pct": max_speedup_pct,
            "recommendation": (
                f"Worth investigating - {max_speedup_pct}% of measured time, "
                f"{d['count']} samples is enough to act on."
                if max_speedup_pct >= 5
                else "Below 5% of measured time - low priority even with sufficient samples."
            ),
        })

    recs.sort(key=lambda r: r["cumulative_wall_clock_s"], reverse=True)
    return recs


def build_report(events: list[dict], min_samples: int) -> dict:
    ops = [e for e in events if e.get("event") == "operation"]
    legacy_steps = [e for e in events if e.get("event") == "pipeline_step"]
    legacy_pw = [e for e in events if e.get("event") == "playwright_fetch"]

    report: dict[str, Any] = {
        "total_operation_events": len(ops),
        "legacy_pipeline_step_events": len(legacy_steps),
        "legacy_playwright_fetch_events": len(legacy_pw),
        "overall_summary": overall_summary(ops),
        "breakdown_by_stage": breakdown_by(ops, "stage"),
        "breakdown_by_ats": breakdown_by(ops, "ats_source"),
        "breakdown_by_company": breakdown_by(ops, "company")[:20],
        "top_20_slowest_operations": slowest_operations(ops, 20),
        "connector_waterfall": connector_waterfall(ops),
        "throughput": throughput(ops),
        "aggregate_averages": aggregate_averages(ops),
        "career_url_cache_report": career_url_cache_report(ops),
        "error_analysis": error_analysis(ops),
        "recommendations": recommendations(ops, min_samples),
    }
    return report


def print_report(report: dict) -> None:
    print("=" * 70)
    print("PIPELINE PERFORMANCE ANALYSIS")
    print("=" * 70)
    print(f"\nTotal fine-grained 'operation' events: {report['total_operation_events']}")
    if report["legacy_pipeline_step_events"]:
        print(f"(plus {report['legacy_pipeline_step_events']} legacy stage-level events, not included in breakdowns below)")

    s = report["overall_summary"]
    print("\n--- Overall Latency (all operations) ---")
    print(f"  count={s['count']}  P50={s['p50_ms']}ms  P90={s['p90_ms']}ms  P95={s['p95_ms']}ms  P99={s['p99_ms']}ms  total={s['total_s']}s")

    print("\n--- Breakdown by Stage ---")
    for name, d in report["breakdown_by_stage"]:
        print(f"  {name:20} total={d['total_s']:>8}s  count={d['count']:>5}  avg={d['avg_ms']:>8}ms  success_rate={d['success_rate']}")

    print("\n--- Breakdown by ATS/Connector ---")
    for name, d in report["breakdown_by_ats"]:
        print(f"  {name:20} total={d['total_s']:>8}s  count={d['count']:>5}  avg={d['avg_ms']:>8}ms  success_rate={d['success_rate']}")

    if report["breakdown_by_company"]:
        print("\n--- Top Companies by Cumulative Time ---")
        for name, d in report["breakdown_by_company"]:
            print(f"  {name[:30]:30} total={d['total_s']:>8}s  count={d['count']:>5}")

    print("\n--- Top 20 Slowest Operations (cumulative wall-clock) ---")
    for name, d in report["top_20_slowest_operations"]:
        print(f"  {name:30} total={d['total_s']:>8}s  count={d['count']:>5}  avg={d['avg_ms']:>8}ms")

    print("\n--- Connector Waterfall (per-connector sub-operation breakdown) ---")
    for connector, rows in report["connector_waterfall"].items():
        print(f"\n  [{connector}]")
        for r in rows:
            print(
                f"    {r['operation']:25} avg={r['avg_ms']:>8}ms  "
                f"p50={r['p50_ms']:>8}ms  p90={r['p90_ms']:>8}ms  p95={r['p95_ms']:>8}ms  p99={r['p99_ms']:>8}ms  "
                f"count={r['count']:>4}  total={round(r['total_ms']/1000.0, 1):>7}s"
            )

    t = report["throughput"]
    print("\n--- Throughput ---")
    print(f"  jobs/hour={t['jobs_per_hour']}  jobs/sec={t['jobs_per_sec']}  avg_seconds/job={t['avg_seconds_per_job']}")

    a = report["aggregate_averages"]
    print("\n--- Aggregate Averages ---")
    print(f"  avg_time_per_successful_job_ms={a['avg_time_per_successful_job_ms']}  (n={a['successful_job_count']})")
    print(f"  avg_time_per_rejected_job_ms={a['avg_time_per_rejected_job_ms']}  (n={a['rejected_job_count']})")
    print(f"  avg_retries={a['avg_retries']}")
    print(f"  avg_cache_hit_rate={a['avg_cache_hit_rate']}")
    print(f"  avg_bytes_downloaded={a['avg_bytes_downloaded']}")
    print(f"  avg_requests_per_job={a['avg_requests_per_job']}  (http_request_count={a['http_request_count']})")
    print(f"  avg_cost_usd_per_llm_call_at_list_price={a['avg_cost_usd_per_llm_call_at_list_price']}  (llm_call_count={a['llm_call_count']})")
    print(f"  total_cost_usd_at_list_price={a['total_cost_usd_at_list_price']}")
    print("  (avg time per connector: see 'Breakdown by ATS/Connector' above; avg time per company: see 'Top Companies' above)")
    print("  Note: any 'None' above means that field has not yet been recorded by enough real events - not estimated.")

    c = report["career_url_cache_report"]
    print("\n--- Career URL Cache (Optimization Sprint #1) ---")
    print(f"  total_lookups={c['total_lookups']}  hits={c['hit_count']}  misses={c['miss_count']}")
    print(f"  hit_rate={c['hit_rate']}  miss_rate={c['miss_rate']}")
    print(f"  avg_lookup_time_ms={c['avg_lookup_time_ms']}  avg_write_time_ms={c['avg_write_time_ms']} (n={c['write_count']})")
    print(f"  estimated_yahoo_searches_avoided={c['estimated_yahoo_searches_avoided']}  (deterministic - see docstring, not a guess)")
    print(f"  avg_cache_age_s_on_hit={c['avg_cache_age_s_on_hit']}  avg_ttl_remaining_s_on_hit={c['avg_ttl_remaining_s_on_hit']}")
    print(f"  invalidation_count={c['invalidation_count']}  reasons={c['invalidation_reasons']}")
    if c["top_cached_companies"]:
        print("  Top cached companies:", ", ".join(f"{name}({n})" for name, n in c["top_cached_companies"]))
    if c["top_cache_miss_companies"]:
        print("  Top cache-miss companies:", ", ".join(f"{name}({n})" for name, n in c["top_cache_miss_companies"]))
    print("  Note: LLM-calls-avoided and DuckDuckGo-searches-avoided are intentionally omitted -")
    print("  both are reached conditionally, so the avoided count is an unknowable counterfactual, not a measurement.")

    print("\n--- Error Analysis (top failure reasons) ---")
    for reason, count in report["error_analysis"][:10]:
        print(f"  {reason[:50]:50} count={count}")

    print("\n--- Recommendations (ranked by cumulative wall-clock impact) ---")
    for r in report["recommendations"][:15]:
        print(f"\n  {r['operation']}")
        print(f"    cumulative_wall_clock_s={r['cumulative_wall_clock_s']}  sample_size={r['sample_size']}")
        print(f"    {r['recommendation']}")

    print("\n" + "=" * 70)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=str(DEFAULT_LOG_PATH))
    ap.add_argument("--min-samples", type=int, default=MIN_SAMPLES_FOR_RECOMMENDATION)
    ap.add_argument("--json", action="store_true", help="print the raw report as JSON instead of a formatted summary")
    args = ap.parse_args()

    path = Path(args.file)
    events = load_events(path)
    if not events:
        print(f"No telemetry events found at {path}.")
        sys.exit(1)

    report = build_report(events, args.min_samples)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print_report(report)


if __name__ == "__main__":
    main()
