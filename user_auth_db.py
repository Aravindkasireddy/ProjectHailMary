"""Local SQLite store for dashboard login users.

This used to live inside notion_sqlite_mirror.py, sharing a database file with
the (now-removed) Notion job-report mirror. Notion support has been dropped --
Supabase's public.jobs table is the sole job-data store -- but the `users`
table here is unrelated to Notion (just local admin/user login credentials),
so it's kept, just re-homed to its own module.

New installs get their users table at <workspace>/data/app_users.db. Existing
installs that only have users rows in the old notion_job_reports.db file get
those rows migrated into app_users.db automatically on first use.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Union


def _workspace(ws: Union[str, Path, None]) -> Path:
    if ws is None:
        from jobsearch_paths import workspace_root
        return workspace_root()
    return Path(ws)


def db_path(ws: Union[str, Path, None] = None) -> Path:
    root = _workspace(ws)
    data = root / "data"
    data.mkdir(parents=True, exist_ok=True)
    return data / "app_users.db"


def _legacy_db_path(ws: Union[str, Path, None] = None) -> Path:
    root = _workspace(ws)
    return root / "data" / "notion_job_reports.db"


def _init(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT DEFAULT 'user',
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def _migrate_legacy_users(conn: sqlite3.Connection, workspace: Union[str, Path, None]) -> None:
    """One-time copy of any users rows from the old Notion-mirror DB file, if present."""
    legacy_path = _legacy_db_path(workspace)
    if not legacy_path.exists():
        return
    try:
        legacy_conn = sqlite3.connect(str(legacy_path))
        legacy_conn.row_factory = sqlite3.Row
        cursor = legacy_conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
        if not cursor.fetchone():
            legacy_conn.close()
            return
        rows = cursor.execute("SELECT email, password_hash, role, created_at FROM users").fetchall()
        legacy_conn.close()
        for row in rows:
            conn.execute(
                "INSERT OR IGNORE INTO users (email, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
                (row["email"], row["password_hash"], row["role"], row["created_at"]),
            )
        conn.commit()
    except Exception as e:
        print(f"Warning: legacy users migration skipped: {e}")


def ensure_users_schema(workspace: Union[str, Path, None] = None) -> None:
    """Create data/ and the SQLite users table (no rows). Safe to call at server startup."""
    path = db_path(workspace)
    with sqlite3.connect(path) as conn:
        _init(conn)
        _migrate_legacy_users(conn, workspace)
