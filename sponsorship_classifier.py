"""Deterministic sponsorship/work-authorization classification.

Produces a single sponsorship_status + confidence_score per job, combining:
  1. Hard-block text signals (citizen-only, clearance, no-sponsorship) - these
     mirror the "### Work authorization restriction" red-flag patterns already
     in Job_classifier_prompt.txt, kept in sync deliberately since both are
     describing the same real-world phrases.
  2. Positive OPT/CPT/international-student-friendly text signals.
  3. The h1b_sponsors table (h1b_sponsors.py) - is this company a known H1B
     filer, and does it carry an OPT-friendly score from the ingested Excel
     dataset (scripts/ingest_opt_friendly.py)?

This is intentionally a deterministic, regex+lookup classifier, not an LLM
call - sponsorship language is highly formulaic ("does not sponsor visas",
"must be a US citizen") and a fast, free, always-available classifier beats
an LLM call that can fail/rate-limit, for exactly the same reason the
rule-based fallback classifier exists for role labels.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

SponsorshipStatus = str  # one of the _STATUS_* constants below

STATUS_CLEARANCE_REQUIRED = "clearance_required"
STATUS_US_CITIZEN_ONLY = "us_citizen_only"
STATUS_GREEN_CARD_ONLY = "green_card_only"
STATUS_REQUIRES_SPONSORSHIP = "requires_sponsorship"  # i.e. employer will NOT sponsor
STATUS_FUTURE_SPONSORSHIP_AVAILABLE = "future_sponsorship_available"
STATUS_OPT_FRIENDLY = "opt_friendly"
STATUS_H1B_SPONSOR = "h1b_sponsor"
STATUS_UNKNOWN = "unknown"

_CLEARANCE_RE = re.compile(
    r"\b(active\s+security\s+clearance|government\s+clearance|secret\s+clearance|"
    r"top\s+secret\s+clearance|ts/sci|itar|export[\s-]control(?:led)?)\b",
    re.IGNORECASE,
)
_US_CITIZEN_ONLY_RE = re.compile(
    r"\b(u\.?s\.?\s+citizens?\s+only|must\s+be\s+a?\s*u\.?s\.?\s+citizen|"
    r"u\.?s\.?\s+person(?:s)?\s+only|8\s+u\.?s\.?c\.?\s+1324b)\b",
    re.IGNORECASE,
)
_GREEN_CARD_ONLY_RE = re.compile(
    r"\b(green\s+card\s+holders?\s+only|permanent\s+resident(?:s)?\s+only|"
    r"u\.?s\.?\s+citizen(?:s)?\s+or\s+green\s+card)\b",
    re.IGNORECASE,
)
_NO_SPONSORSHIP_RE = re.compile(
    r"\b(no\s+visa\s+sponsorship|not\s+eligible\s+for\s+sponsorship|"
    r"unable\s+to\s+sponsor\s+visas?|does\s+not\s+sponsor\s+work\s+authorization|"
    r"cannot\s+sponsor\s+h-?1b|cannot\s+provide\s+visa\s+sponsorship|"
    r"not\s+eligible\s+for\s+immigration\s+sponsorship|"
    r"authorized\s+to\s+work\s+in\s+the\s+u\.?s\.?\s+without\s+sponsorship|"
    r"permanent\s+work\s+authorization|"
    r"no\s+future\s+sponsorship|without\s+sponsorship\s+now\s+or\s+in\s+the\s+future|"
    r"work\s+authorization\s+required\s+without\s+sponsorship|"
    r"no\s+current\s+or\s+future\s+sponsorship)\b",
    re.IGNORECASE,
)
_FUTURE_SPONSORSHIP_RE = re.compile(
    r"\b(will\s+sponsor|open\s+to\s+sponsor(?:ing)?|future\s+sponsorship\s+(?:is\s+)?available|"
    r"sponsorship\s+available\s+in\s+the\s+future|may\s+sponsor\s+in\s+the\s+future|"
    r"willing\s+to\s+sponsor)\b",
    re.IGNORECASE,
)
_OPT_FRIENDLY_RE = re.compile(
    r"\b(opt\s+friendly|cpt\s+friendly|opt/cpt|f-?1\s+(?:visa\s+)?(?:welcome|eligible|friendly)|"
    r"international\s+students?\s+(?:welcome|encouraged)|"
    r"will\s+sponsor\s+h-?1b|h-?1b\s+sponsorship\s+(?:available|provided))\b",
    re.IGNORECASE,
)


def classify_sponsorship(
    job: Dict[str, Any], sponsors_cleaned: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Return {"sponsorship_status", "confidence_score", "signals"}.

    Checked in priority order: hard blockers (clearance/citizen-only/green-card-only/
    no-sponsorship) outrank positive signals, since a hard requirement in the JD
    means the company-level sponsor match or a generic "OPT friendly" phrase
    elsewhere in boilerplate text doesn't actually apply to this specific posting.
    """
    text = " ".join(
        str(job.get(k) or "") for k in ("job_title", "job_description")
    )

    if _CLEARANCE_RE.search(text):
        return {"sponsorship_status": STATUS_CLEARANCE_REQUIRED, "confidence_score": 90.0, "signals": ["clearance language"]}
    if _US_CITIZEN_ONLY_RE.search(text):
        return {"sponsorship_status": STATUS_US_CITIZEN_ONLY, "confidence_score": 90.0, "signals": ["US citizen only language"]}
    if _GREEN_CARD_ONLY_RE.search(text):
        return {"sponsorship_status": STATUS_GREEN_CARD_ONLY, "confidence_score": 85.0, "signals": ["green card only language"]}
    if _NO_SPONSORSHIP_RE.search(text):
        return {"sponsorship_status": STATUS_REQUIRES_SPONSORSHIP, "confidence_score": 85.0, "signals": ["no-sponsorship language"]}

    signals = []
    future_hit = bool(_FUTURE_SPONSORSHIP_RE.search(text))
    opt_hit = bool(_OPT_FRIENDLY_RE.search(text))
    if future_hit:
        signals.append("future sponsorship language")
    if opt_hit:
        signals.append("OPT/CPT-friendly language")

    # Company-level signal from the h1b_sponsors table.
    company_match = None
    opt_score = None
    if sponsors_cleaned:
        from h1b_sponsors import is_sponsor_match

        company_match = is_sponsor_match(job.get("company_name", ""), sponsors_cleaned)
        if company_match:
            opt_score = company_match.get("opt_friendly_score")
            signals.append(f"known H1B sponsor ({job.get('company_name', '')})")

    if opt_hit or (opt_score is not None and opt_score >= 60):
        confidence = 85.0 if opt_hit else min(80.0, 50.0 + (opt_score or 0) / 2)
        return {"sponsorship_status": STATUS_OPT_FRIENDLY, "confidence_score": confidence, "signals": signals}

    if future_hit:
        return {"sponsorship_status": STATUS_FUTURE_SPONSORSHIP_AVAILABLE, "confidence_score": 75.0, "signals": signals}

    if company_match:
        confidence = 50.0 + min(30.0, (opt_score or 0) / 3)
        return {"sponsorship_status": STATUS_H1B_SPONSOR, "confidence_score": confidence, "signals": signals}

    return {"sponsorship_status": STATUS_UNKNOWN, "confidence_score": 30.0, "signals": []}
