"""
Single source of truth for repository root. Override with JOBSEARCH_ROOT if needed.
"""
from __future__ import annotations

import os
from pathlib import Path


def workspace_root() -> Path:
    env = os.environ.get("JOBSEARCH_ROOT", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    # This module lives at the repository root next to dashboard_server.py and find_and_scrape_jobs.py.
    return Path(__file__).resolve().parent
