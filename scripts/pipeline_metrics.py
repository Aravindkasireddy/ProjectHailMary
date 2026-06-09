"""Append-only JSONL metrics for pipeline stages (scrape / filter / classify)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Mapping


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
