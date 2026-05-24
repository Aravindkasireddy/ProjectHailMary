"""Webhook URL resolution: environment wins over config.json."""
from __future__ import annotations

import os
from typing import Any, Mapping


def effective_webhook_url(cfg: Mapping[str, Any] | None) -> str:
    env = os.environ.get("JOBSEARCH_WEBHOOK_URL", "").strip()
    if env:
        return env
    if not cfg:
        return ""
    return str(cfg.get("webhook_url") or "").strip()


def public_config_for_api(cfg: dict) -> dict:
    """
    Return a copy of config safe to send to the browser.
    If JOBSEARCH_WEBHOOK_URL is set, do not leak the on-disk webhook from config.json.
    """
    out = dict(cfg)
    if os.environ.get("JOBSEARCH_WEBHOOK_URL", "").strip():
        out["webhook_url"] = ""
        out["webhook_source"] = "environment"
    else:
        out["webhook_source"] = "config_file"
    return out
