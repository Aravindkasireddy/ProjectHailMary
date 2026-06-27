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
        "throughput": throughput(ops),
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

    t = report["throughput"]
    print("\n--- Throughput ---")
    print(f"  jobs/hour={t['jobs_per_hour']}  jobs/sec={t['jobs_per_sec']}  avg_seconds/job={t['avg_seconds_per_job']}")

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
