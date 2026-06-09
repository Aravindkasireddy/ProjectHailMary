"""
Best-effort salary extraction from US-style job description text.
Fills min_salary, max_salary, is_hourly, salary_text when missing.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple


def _parse_money_range(text: str) -> Optional[Tuple[int, int, bool, str]]:
    """Return (min, max, is_hourly, matched_snippet) or None."""
    t = text.replace(",", "")
    # Hourly range
    hr = re.search(
        r"(\$\d{1,3}(?:\.\d+)?)\s*(?:-|–|to)\s*(\$\d{1,3}(?:\.\d+)?)\s*/?\s*(?:hr|hour)",
        t,
        re.I,
    )
    if hr:
        lo = int(float(hr.group(1).replace("$", "")))
        hi = int(float(hr.group(2).replace("$", "")))
        return (lo * 2080, hi * 2080, True, hr.group(0)[:120])
    hr1 = re.search(r"(\$\d{1,3}(?:\.\d+)?)\s*/?\s*(?:hr|hour)", t, re.I)
    if hr1:
        v = int(float(hr1.group(1).replace("$", "")))
        return (v * 2080, v * 2080, True, hr1.group(0)[:120])

    # $80k - $100k
    mk = re.search(
        r"(\$\d{2,3})\s*k\s*(?:-|–|to)\s*(\$\d{2,3})\s*k",
        t,
        re.I,
    )
    if mk:
        lo = int(mk.group(1).replace("$", "")) * 1000
        hi = int(mk.group(2).replace("$", "")) * 1000
        return (lo, hi, False, mk.group(0)[:120])

    # $80,000 - $100,000
    ma = re.search(
        r"(\$\d{2,3}(?:,\d{3})+)\s*(?:-|–|to)\s*(\$\d{2,3}(?:,\d{3})+)",
        t,
    )
    if ma:
        lo = int(ma.group(1).replace("$", "").replace(",", ""))
        hi = int(ma.group(2).replace("$", "").replace(",", ""))
        return (lo, hi, False, ma.group(0)[:120])

    return None


def extract_salary_fields(job: Dict[str, Any]) -> Dict[str, Any]:
    """Return fields to merge into job if not already set."""
    if job.get("min_salary") and job.get("max_salary"):
        return {}
    blob = " ".join(
        str(job.get(k) or "")
        for k in ("job_title", "job_description", "salary_text", "location_work_type")
    )
    parsed = _parse_money_range(blob)
    if not parsed:
        return {}
    lo, hi, hourly, snippet = parsed
    if lo > hi:
        lo, hi = hi, lo
    return {
        "min_salary": lo,
        "max_salary": hi,
        "is_hourly": hourly,
        "salary_text": snippet,
    }
