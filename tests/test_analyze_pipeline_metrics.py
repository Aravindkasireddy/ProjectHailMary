"""Tests for scripts/analyze_pipeline_metrics.py."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from analyze_pipeline_metrics import (
    breakdown_by,
    build_report,
    connector_waterfall,
    error_analysis,
    overall_summary,
    percentile,
    recommendations,
    throughput,
)


def _op(name, stage, duration_ms, success=True, company=None, ats_source=None, jobs_processed=None, exception=None):
    return {
        "event": "operation",
        "operation_name": name,
        "stage": stage,
        "duration_ms": duration_ms,
        "success": success,
        "company": company,
        "ats_source": ats_source,
        "jobs_processed": jobs_processed,
        "exception": exception,
    }


def test_percentile_basic():
    values = [10, 20, 30, 40, 50]
    assert percentile(values, 50) == 30
    assert percentile(values, 0) == 10
    assert percentile(values, 100) == 50


def test_percentile_empty_list():
    assert percentile([], 50) == 0.0


def test_overall_summary():
    ops = [_op("a", "discovery", 100), _op("a", "discovery", 200), _op("a", "discovery", 300)]
    s = overall_summary(ops)
    assert s["count"] == 3
    assert s["p50_ms"] == 200
    assert s["total_s"] == 0.6


def test_breakdown_by_groups_and_sorts_descending():
    ops = [
        _op("a", "discovery", 100, ats_source="greenhouse"),
        _op("b", "discovery", 5000, ats_source="linkedin"),
        _op("c", "discovery", 50, ats_source="greenhouse"),
    ]
    result = breakdown_by(ops, "ats_source")
    names = [name for name, _ in result]
    assert names[0] == "linkedin"  # highest cumulative time first
    gh = dict(result)["greenhouse"]
    assert gh["count"] == 2
    assert gh["total_s"] == pytest.approx(0.15, abs=0.05)


def test_breakdown_by_skips_missing_key():
    ops = [_op("a", "discovery", 100, ats_source=None), _op("b", "discovery", 100, ats_source="lever")]
    result = breakdown_by(ops, "ats_source")
    assert len(result) == 1
    assert result[0][0] == "lever"


def test_throughput_computes_jobs_per_sec():
    ops = [_op("a", "discovery", 1000, jobs_processed=2), _op("b", "discovery", 1000, jobs_processed=2)]
    t = throughput(ops)
    assert t["jobs_per_sec"] == 2.0
    assert t["avg_seconds_per_job"] == 0.5


def test_throughput_handles_no_jobs():
    ops = [_op("a", "discovery", 1000, jobs_processed=0)]
    t = throughput(ops)
    assert t["jobs_per_hour"] == 0


def test_error_analysis_buckets_by_exception_type():
    ops = [
        _op("a", "discovery", 100, success=False, exception="ValueError: bad input"),
        _op("b", "discovery", 100, success=False, exception="ValueError: also bad"),
        _op("c", "discovery", 100, success=False, exception="TimeoutError: too slow"),
    ]
    result = error_analysis(ops)
    assert result[0] == ("ValueError", 2)


def test_recommendations_flags_insufficient_data_below_threshold():
    ops = [_op("rare_op", "discovery", 50000)] * 5  # only 5 samples
    recs = recommendations(ops, min_samples=20)
    assert recs[0]["recommendation"] == "INSUFFICIENT DATA - do not act on this yet"
    assert recs[0]["sample_size"] == 5


def test_recommendations_flags_low_priority_below_5_percent_share():
    big_op = [_op("dominant", "discovery", 95000)] * 25
    small_op = [_op("tiny", "discovery", 100)] * 25
    recs = recommendations(big_op + small_op, min_samples=20)
    tiny_rec = next(r for r in recs if r["operation"] == "tiny")
    assert "low priority" in tiny_rec["recommendation"].lower()


def test_recommendations_flags_worth_investigating_above_threshold_with_enough_samples():
    ops = [_op("dominant", "discovery", 10000)] * 25
    recs = recommendations(ops, min_samples=20)
    assert "worth investigating" in recs[0]["recommendation"].lower()
    assert recs[0]["max_theoretical_speedup_pct"] == 100.0


def test_build_report_separates_legacy_events_from_operations():
    events = [
        {"event": "pipeline_step", "step": "find_and_scrape_jobs", "duration_ms": 1000},
        _op("a", "discovery", 100, jobs_processed=1),
    ]
    report = build_report(events, min_samples=20)
    assert report["total_operation_events"] == 1
    assert report["legacy_pipeline_step_events"] == 1


def test_connector_waterfall_groups_by_connector_in_waterfall_order():
    ops = [
        _op("career_url_resolution", "discovery", 2200, ats_source="linkedin"),
        _op("yahoo_search", "discovery", 900, ats_source="linkedin"),
        _op("llm_fallback", "discovery", 3200, ats_source="linkedin"),
        _op("html_parsing", "discovery", 120, ats_source="greenhouse"),
    ]
    waterfalls = connector_waterfall(ops)
    assert set(waterfalls.keys()) == {"linkedin", "greenhouse"}

    linkedin_ops = [r["operation"] for r in waterfalls["linkedin"]]
    # career_url_resolution comes before yahoo_search/llm_fallback in the
    # defined waterfall order, regardless of insertion order above.
    assert linkedin_ops.index("career_url_resolution") < linkedin_ops.index("yahoo_search")
    assert linkedin_ops.index("yahoo_search") < linkedin_ops.index("llm_fallback")

    gh_ops = {r["operation"]: r for r in waterfalls["greenhouse"]}
    assert gh_ops["html_parsing"]["count"] == 1
    assert gh_ops["html_parsing"]["avg_ms"] == 120


def test_connector_waterfall_includes_percentiles():
    ops = [_op("html_parsing", "discovery", d, ats_source="greenhouse") for d in (100, 200, 300, 400, 500)]
    waterfalls = connector_waterfall(ops)
    row = waterfalls["greenhouse"][0]
    assert row["p50_ms"] == 300
    assert row["count"] == 5


def test_connector_waterfall_skips_ops_with_no_connector():
    ops = [_op("json_load", "filter", 100, ats_source=None)]
    waterfalls = connector_waterfall(ops)
    assert waterfalls == {}


def test_connector_waterfall_includes_unknown_ops_after_known_ones():
    ops = [
        _op("html_parsing", "discovery", 100, ats_source="greenhouse"),
        _op("some_future_op", "discovery", 50, ats_source="greenhouse"),
    ]
    waterfalls = connector_waterfall(ops)
    names = [r["operation"] for r in waterfalls["greenhouse"]]
    assert names == ["html_parsing", "some_future_op"]
