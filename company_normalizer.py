"""Normalize company name variants to one canonical display name.

"Bank of America" / "BofA" / "Bank of America Corp" -> "Bank of America"

Note: h1b_sponsors.clean_company_name() and job_fingerprint.normalize_company_name()
already lowercase+strip company names, but only for *matching* (sponsor lookup,
fingerprint hashing) - their output isn't meant to be shown to a user ("bank
america", not "Bank of America"). This module produces a clean, properly-cased
*display* name instead, layering a small known-alias map on top of generic
legal-suffix stripping for the common abbreviation cases that pure suffix-
stripping can't fix (BofA, IBM has no abbreviation problem, but P&G/GE/etc. do).
"""
from __future__ import annotations

import re

_LEGAL_SUFFIX_RE = re.compile(
    r",?\s*\b(inc|llc|corp|corporation|incorporated|ltd|limited|co|company|"
    r"holdings|group|llp|plc)\b\.?\s*$",
    re.IGNORECASE,
)

# Known abbreviation/alt-name -> canonical display name. Add entries here as
# real collisions are found in scraped data rather than trying to guess every
# possible alias upfront.
_KNOWN_ALIASES = {
    "bofa": "Bank of America",
    "boa": "Bank of America",
    "bank of america corp": "Bank of America",
    "ge": "General Electric",
    "ibm corporation": "IBM",
    "p&g": "Procter & Gamble",
    "jpmc": "JPMorgan Chase",
    "jp morgan": "JPMorgan Chase",
    "jpmorgan chase and co": "JPMorgan Chase",
    "msft": "Microsoft",
    "amzn": "Amazon",
    "googl": "Google",
    "fb": "Meta",
    "facebook": "Meta",
}


def _strip_legal_suffix(name: str) -> str:
    prev = None
    s = name.strip()
    # Repeated strip in case of "X Corp, Inc." style double suffixes.
    while prev != s:
        prev = s
        s = _LEGAL_SUFFIX_RE.sub("", s).strip()
    return s


def normalize_company(raw: str) -> str:
    """Return a clean, canonical display name for a company.

    Falls back to legal-suffix-stripped title case when there's no known
    alias - this won't catch every abbreviation in the world, but it fixes
    the common, high-volume cases (legal-entity suffixes on every H1B filer
    name) without needing a hand-maintained list of every company on earth.
    """
    if not raw:
        return ""

    stripped = _strip_legal_suffix(raw)
    key = stripped.lower().strip()
    if key in _KNOWN_ALIASES:
        return _KNOWN_ALIASES[key]

    # Also check the raw (pre-strip) name in case the alias itself includes
    # what looks like a suffix-bearing legal name (e.g. "Bank of America Corp").
    raw_key = raw.lower().strip()
    if raw_key in _KNOWN_ALIASES:
        return _KNOWN_ALIASES[raw_key]

    return stripped if stripped else raw.strip()
