"""Append-only JSONL metrics for pipeline stages (scrape / filter / classify).

2026-06-27: extended with record_operation(), a fine-grained per-operation
timer (event="operation") that sits alongside the existing pipeline_step/
playwright_fetch events in the same logs/pipeline_metrics.jsonl file -
deliberately one file, not a new one, per the instruction to extend existing
telemetry rather than fragment it. This is pure observability: it never
swallows or alters an exception, never changes return values, never adds
retries/batching - it only times a block and writes one JSON line about it.
"""

from __future__ import annotations

import json
import os
import time
import traceback
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Mapping, Optional


def append_pipeline_metric(
    workspace_dir: str,
    event: str,
    fields: Mapping[str, Any] | None = None,
) -> None:
    """Write one JSON line to logs/pipeline_metrics.jsonl (best-effort)."""
    try:
        log_dir = os.path.join(workspace_dir, "logs")
        os.makedirs(log_dir, exist_ok=True)
        path = os.path.join(log_dir, "pipeline_metrics.jsonl")
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **(dict(fields) if fields else {}),
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, default=str) + "\n")
    except Exception:
        pass


@contextmanager
def record_operation(
    workspace_dir: str,
    operation_name: str,
    stage: str,
    company: Optional[str] = None,
    ats_source: Optional[str] = None,
    jobs_processed: Optional[int] = None,
    **metadata: Any,
):
    """Time one operation and record it as an event="operation" line.

    Usage:
        with record_operation(WORKSPACE, "yahoo_search", "discovery", company="Acme"):
            ...do the thing...

    Re-raises any exception from the wrapped block unchanged after recording
    it (success=False, exception=str) - this never changes control flow or
    swallows errors, it only observes. Writing the metric itself is
    best-effort (append_pipeline_metric never raises), so a logging failure
    can never break the operation being measured.
    """
    start = datetime.now(timezone.utc)
    t0 = time.perf_counter()
    success = True
    exc_str: Optional[str] = None
    try:
        yield
    except Exception as e:
        success = False
        exc_str = f"{type(e).__name__}: {e}"
        raise
    finally:
        duration_ms = int((time.perf_counter() - t0) * 1000)
        end = datetime.now(timezone.utc)
        append_pipeline_metric(
            workspace_dir,
            "operation",
            {
                "operation_name": operation_name,
                "stage": stage,
                "company": company,
                "ats_source": ats_source,
                "start_time": start.isoformat(),
                "end_time": end.isoformat(),
                "duration_ms": duration_ms,
                "success": success,
                "exception": exc_str,
                "jobs_processed": jobs_processed,
                "metadata": metadata or {},
            },
        )


def generate_run_summary(workspace_dir: str, since_iso: str) -> dict:
    """Build an end-of-run summary from all "operation" events with
    ts >= since_iso (i.e. emitted during this run). Called once at the end
    of each stage's main(), best-effort - never raises.
    """
    try:
        path = os.path.join(workspace_dir, "logs", "pipeline_metrics.jsonl")
        if not os.path.exists(path):
            return {}
        ops = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if rec.get("event") == "operation" and rec.get("ts", "") >= since_iso:
                    ops.append(rec)
        if not ops:
            return {}

        total_runtime_ms = sum(o.get("duration_ms", 0) for o in ops)

        by_stage: dict = {}
        by_operation: dict = {}
        by_company: dict = {}
        by_connector: dict = {}
        retries = 0
        successes = 0

        for o in ops:
            d = o.get("duration_ms", 0)
            by_stage[o.get("stage", "unknown")] = by_stage.get(o.get("stage", "unknown"), 0) + d
            by_operation[o.get("operation_name", "unknown")] = by_operation.get(o.get("operation_name", "unknown"), 0) + d
            if o.get("company"):
                by_company[o["company"]] = by_company.get(o["company"], 0) + d
            if o.get("ats_source"):
                by_connector[o["ats_source"]] = by_connector.get(o["ats_source"], 0) + d
            if o.get("success"):
                successes += 1
            meta = o.get("metadata") or {}
            if isinstance(meta, dict) and meta.get("retry"):
                retries += 1

        jobs_total = sum(o.get("jobs_processed") or 0 for o in ops)
        runtime_s = total_runtime_ms / 1000.0

        summary = {
            "total_runtime_s": round(runtime_s, 1),
            "runtime_by_stage_s": {k: round(v / 1000.0, 1) for k, v in by_stage.items()},
            "runtime_by_operation_s": {k: round(v / 1000.0, 1) for k, v in by_operation.items()},
            "top_20_slowest_operations": sorted(
                ({"operation_name": o.get("operation_name"), "duration_ms": o.get("duration_ms")} for o in ops),
                key=lambda x: x["duration_ms"],
                reverse=True,
            )[:20],
            "top_20_slowest_companies": sorted(by_company.items(), key=lambda x: x[1], reverse=True)[:20],
            "top_20_slowest_connectors": sorted(by_connector.items(), key=lambda x: x[1], reverse=True)[:20],
            "jobs_per_sec": round(jobs_total / runtime_s, 4) if runtime_s and jobs_total else 0,
            "seconds_per_job": round(runtime_s / jobs_total, 2) if jobs_total else None,
            "success_rate": round(successes / len(ops), 4) if ops else None,
            "retry_count": retries,
            "operation_count": len(ops),
        }

        append_pipeline_metric(workspace_dir, "run_summary", summary)
        return summary
    except Exception:
        return {}
