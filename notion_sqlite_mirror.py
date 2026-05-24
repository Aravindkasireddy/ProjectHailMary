"""
Local SQLite mirror of job rows synced to Notion (same fields as the Notion sync payload).

Safe to fail silently — never blocks Notion. DB path: <workspace>/data/notion_job_reports.db
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Union

from jobsearch_paths import workspace_root


def _workspace(ws: Union[str, Path, None]) -> Path:
    if ws is None:
        return workspace_root()
    return Path(ws)


def db_path(ws: Union[str, Path, None] = None) -> Path:
    root = _workspace(ws)
    data = root / "data"
    data.mkdir(parents=True, exist_ok=True)
    return data / "notion_job_reports.db"


def _init(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS notion_job_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_url TEXT NOT NULL UNIQUE,
            notion_page_id TEXT NOT NULL,
            notion_database_id TEXT,
            requirement_id TEXT,
            job_title TEXT,
            company_name TEXT,
            location_work_type TEXT,
            job_description TEXT,
            apply_decision TEXT,
            strongest_label TEXT,
            confidence_score REAL,
            rationale TEXT,
            apply_decision_payload_json TEXT,
            red_flags_json TEXT,
            date_added TEXT,
            synced_at TEXT NOT NULL,
            was_duplicate INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.commit()


def ensure_notion_mirror_schema(workspace: Union[str, Path, None] = None) -> None:
    """Create data/ and the SQLite file with tables (no rows). Safe to call at server startup."""
    path = db_path(workspace)
    with sqlite3.connect(path) as conn:
        _init(conn)


def _score_for_sqlite(job: Mapping[str, Any]) -> float:
    score = float(job.get("confidence_score") or 0)
    if score > 1.0:
        score = score / 100.0
    return score


def upsert_notion_job_report(
    job: Mapping[str, Any],
    notion_page_id: str,
    notion_database_id: str,
    *,
    was_duplicate: bool = False,
    workspace: Union[str, Path, None] = None,
) -> None:
    """Insert or replace one row keyed by job_url."""
    path = db_path(workspace)
    red = job.get("red_flags", [])
    if isinstance(red, str):
        red = [red] if red else []
    payload = job.get("apply_decision_payload", {})

    synced = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    date_added = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    with sqlite3.connect(path) as conn:
        _init(conn)
        conn.execute(
            """
            INSERT INTO notion_job_reports (
                job_url, notion_page_id, notion_database_id, requirement_id,
                job_title, company_name, location_work_type, job_description,
                apply_decision, strongest_label, confidence_score, rationale,
                apply_decision_payload_json, red_flags_json, date_added, synced_at, was_duplicate
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_url) DO UPDATE SET
                notion_page_id = excluded.notion_page_id,
                notion_database_id = excluded.notion_database_id,
                requirement_id = excluded.requirement_id,
                job_title = excluded.job_title,
                company_name = excluded.company_name,
                location_work_type = excluded.location_work_type,
                job_description = excluded.job_description,
                apply_decision = excluded.apply_decision,
                strongest_label = excluded.strongest_label,
                confidence_score = excluded.confidence_score,
                rationale = excluded.rationale,
                apply_decision_payload_json = excluded.apply_decision_payload_json,
                red_flags_json = excluded.red_flags_json,
                date_added = excluded.date_added,
                synced_at = excluded.synced_at,
                was_duplicate = excluded.was_duplicate
            """,
            (
                job.get("job_url") or "",
                notion_page_id,
                notion_database_id,
                job.get("requirement_id"),
                job.get("job_title"),
                job.get("company_name"),
                job.get("location_work_type"),
                job.get("job_description"),
                job.get("apply_decision"),
                job.get("strongest_label"),
                _score_for_sqlite(job),
                job.get("rationale"),
                json.dumps(payload, ensure_ascii=False) if payload else "{}",
                json.dumps(list(red), ensure_ascii=False),
                date_added,
                synced,
                1 if was_duplicate else 0,
            ),
        )
        conn.commit()
