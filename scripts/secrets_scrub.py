"""Remove obvious secret material from nested structures before persistence or logs."""

from __future__ import annotations

import copy
import os
import re
from typing import Any, Dict, List, Union

_JSON_SCALAR = Union[str, int, float, bool, None]


def _patterns_from_env() -> List[re.Pattern]:
    keys = []
    for k, v in os.environ.items():
        if any(
            x in k.upper()
            for x in (
                "KEY",
                "TOKEN",
                "SECRET",
                "PASSWORD",
                "API_KEY",
                "SERVICE_ROLE",
                "WEBHOOK",
                "NOTION",
                "SUPABASE",
            )
        ):
            if v and len(v) > 8:
                keys.append(re.escape(v))
    # de-dup long literals
    uniq = []
    seen = set()
    for p in keys:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return [re.compile(p) for p in uniq[:40]]


_PATTERNS = _patterns_from_env()


def scrub_string(s: str) -> str:
    out = s
    for rx in _PATTERNS:
        out = rx.sub("[REDACTED]", out)
    # generic long base64-ish
    out = re.sub(r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}", "[REDACTED_JWT]", out)
    return out


def scrub_payload(obj: Any) -> Any:
    if isinstance(obj, str):
        return scrub_string(obj)
    if isinstance(obj, list):
        return [scrub_payload(x) for x in obj]
    if isinstance(obj, dict):
        return {k: scrub_payload(v) for k, v in obj.items()}
    return obj


def scrub_job_payload_for_storage(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Deep copy + scrub strings in classification payload."""
    return scrub_payload(copy.deepcopy(payload))  # type: ignore[return-value]
