"""Tests for scripts/pipeline_metrics.py's record_operation() and
generate_run_summary() - the core telemetry primitives added to make future
pipeline optimizations evidence-driven instead of estimated.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from pipeline_metrics import append_pipeline_metric, generate_run_summary, record_operation


def _read_lines(path):
    with open(path) as f:
        return [json.loads(line) for line in f]


def test_record_operation_writes_required_fields(tmp_path):
    with record_operation(str(tmp_path), "test_op", "discovery", company="Acme", ats_source="greenhouse", jobs_processed=3, foo="bar"):
        pass

    lines = _read_lines(tmp_path / "logs" / "pipeline_metrics.jsonl")
    assert len(lines) == 1
    rec = lines[0]
    assert rec["event"] == "operation"
    assert rec["operation_name"] == "test_op"
    assert rec["stage"] == "discovery"
    assert rec["company"] == "Acme"
    assert rec["ats_source"] == "greenhouse"
    assert rec["jobs_processed"] == 3
    assert rec["success"] is True
    assert rec["exception"] is None
    assert "start_time" in rec and "end_time" in rec
    assert isinstance(rec["duration_ms"], int)
    assert rec["metadata"] == {"foo": "bar"}


def test_record_operation_records_failure_and_reraises(tmp_path):
    with pytest.raises(ValueError):
        with record_operation(str(tmp_path), "failing_op", "discovery"):
            raise ValueError("boom")

    lines = _read_lines(tmp_path / "logs" / "pipeline_metrics.jsonl")
    rec = lines[0]
    assert rec["success"] is False
    assert "ValueError" in rec["exception"]
    assert "boom" in rec["exception"]


def test_record_operation_never_changes_return_value(tmp_path):
    results = []
    with record_operation(str(tmp_path), "op", "discovery"):
        results.append(42)
    assert results == [42]


def test_generate_run_summary_aggregates_correctly(tmp_path):
    workspace = str(tmp_path)
    import datetime as dt

    since = dt.datetime.now(dt.timezone.utc).isoformat()

    with record_operation(workspace, "op_a", "discovery", company="Acme", ats_source="greenhouse", jobs_processed=2):
        pass
    with record_operation(workspace, "op_b", "classify", company="Acme", ats_source="greenhouse", jobs_processed=1):
        pass
    try:
        with record_operation(workspace, "op_c", "discovery"):
            raise RuntimeError("fail")
    except RuntimeError:
        pass

    summary = generate_run_summary(workspace, since)

    assert summary["operation_count"] == 3
    assert "discovery" in summary["runtime_by_stage_s"]
    assert "classify" in summary["runtime_by_stage_s"]
    assert "op_a" in summary["runtime_by_operation_s"]
    assert summary["success_rate"] == pytest.approx(2 / 3, abs=1e-3)
    assert len(summary["top_20_slowest_operations"]) == 3
    assert any(c == "Acme" for c, _ in summary["top_20_slowest_companies"])
    assert any(c == "greenhouse" for c, _ in summary["top_20_slowest_connectors"])
    assert summary["jobs_per_sec"] >= 0


def test_generate_run_summary_excludes_events_before_since(tmp_path):
    workspace = str(tmp_path)
    import datetime as dt

    with record_operation(workspace, "old_op", "discovery"):
        pass

    since = dt.datetime.now(dt.timezone.utc).isoformat()

    with record_operation(workspace, "new_op", "discovery"):
        pass

    summary = generate_run_summary(workspace, since)
    assert summary["operation_count"] == 1
    assert "new_op" in summary["runtime_by_operation_s"]
    assert "old_op" not in summary["runtime_by_operation_s"]


def test_generate_run_summary_returns_empty_dict_when_no_events(tmp_path):
    import datetime as dt

    summary = generate_run_summary(str(tmp_path), dt.datetime.now(dt.timezone.utc).isoformat())
    assert summary == {}


def test_append_pipeline_metric_never_raises_on_bad_workspace():
    # Best-effort: an unwritable/invalid path should not raise.
    append_pipeline_metric("/this/path/does/not/exist/and/cannot/be/created\x00", "operation", {"x": 1})
