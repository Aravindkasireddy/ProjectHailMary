"""Normalize extracted salary data to a fixed schema.

Note: salary_extractor.py and scripts/salary_parser.py are two pre-existing,
overlapping salary-extraction implementations with slightly different regex
coverage and output field names (min_salary/max_salary/is_hourly vs.
salary_min/salary_max/pay_period). This module does NOT add a third
extractor - it wraps the more thorough of the two (salary_extractor.py) and
maps its output to the canonical schema connectors.base.normalize_job()
expects. Consolidating the two existing extractors into one is flagged as
follow-up cleanup, out of scope for this change.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from salary_extractor import extract_salary


def normalize_salary(description: str, title: str = "") -> Dict[str, Any]:
    """Return {"salary_min", "salary_max", "currency", "pay_period"}.

    pay_period is "hour" or "year". All fields are None/"USD"/"year" when no
    salary signal is found in the text, never an exception.
    """
    parsed: Optional[Dict[str, Any]] = extract_salary(description, title)
    if not parsed:
        return {"salary_min": None, "salary_max": None, "currency": "USD", "pay_period": "year"}

    return {
        "salary_min": parsed.get("min_salary"),
        "salary_max": parsed.get("max_salary"),
        "currency": parsed.get("currency", "USD"),
        "pay_period": "hour" if parsed.get("is_hourly") else "year",
    }
