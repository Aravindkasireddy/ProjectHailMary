"""Normalize free-text job locations to a consistent display string plus a
remote/hybrid/onsite classification.

"Austin TX" / "Austin, Texas" / "Austin, TX" -> "Austin, TX, USA"
"""
from __future__ import annotations

import re
from typing import Dict

_STATE_NAME_TO_ABBR = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "florida": "FL", "georgia": "GA",
    "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA",
    "kansas": "KS", "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT",
    "virginia": "VA", "washington": "WA", "west virginia": "WV", "wisconsin": "WI",
    "wyoming": "WY", "district of columbia": "DC",
}
_VALID_ABBRS = set(_STATE_NAME_TO_ABBR.values())

_REMOTE_HINTS = ("remote", "work from home", "wfh", "anywhere", "distributed")
_HYBRID_HINTS = ("hybrid",)


def _classify(text: str) -> Dict[str, bool]:
    t = text.lower()
    is_remote = any(h in t for h in _REMOTE_HINTS)
    is_hybrid = any(h in t for h in _HYBRID_HINTS)
    return {"is_remote": is_remote and not is_hybrid, "is_hybrid": is_hybrid}


def normalize_location(raw: str) -> Dict[str, object]:
    """Return {"display", "is_remote", "is_hybrid"}.

    display is "City, ST, USA" when a recognizable US city/state pair is
    found, "Remote" for fully-remote text, or the original cleaned text as a
    fallback for anything this can't confidently parse (non-US locations,
    multi-city lists, etc.) - this is deliberately conservative: a wrong
    normalization is worse than passing through the original text unchanged.
    """
    if not raw:
        return {"display": "Remote", "is_remote": True, "is_hybrid": False}

    flags = _classify(raw)
    cleaned = re.sub(r"[\(\)\[\]]", " ", raw).strip()
    # Strip a trailing parenthetical like "(Remote)" / "(Hybrid)" before
    # trying to parse a city/state out of what's left.
    cleaned = re.sub(
        r"\b(remote|hybrid|onsite|on-site|work from home|wfh)\b", "", cleaned, flags=re.I
    ).strip(" ,-")

    if not cleaned:
        if flags["is_remote"]:
            return {"display": "Remote", "is_remote": True, "is_hybrid": False}
        if flags["is_hybrid"]:
            return {"display": "Hybrid", "is_remote": False, "is_hybrid": True}
        return {"display": "Remote", "is_remote": True, "is_hybrid": False}

    parts = [p.strip() for p in cleaned.split(",") if p.strip()]
    city, state_abbr = None, None

    if len(parts) >= 2:
        city = parts[0]
        state_token = parts[1].lower()
        if state_token.upper() in _VALID_ABBRS:
            state_abbr = state_token.upper()
        elif state_token in _STATE_NAME_TO_ABBR:
            state_abbr = _STATE_NAME_TO_ABBR[state_token]
    else:
        # "Austin TX" with no comma - try splitting on the last token.
        tokens = cleaned.split()
        if len(tokens) >= 2 and tokens[-1].upper() in _VALID_ABBRS:
            city = " ".join(tokens[:-1])
            state_abbr = tokens[-1].upper()

    if city and state_abbr:
        display = f"{city}, {state_abbr}, USA"
    else:
        display = cleaned

    if flags["is_remote"]:
        display = f"{display} (Remote)" if display != "Remote" else display
    elif flags["is_hybrid"]:
        display = f"{display} (Hybrid)" if display != "Hybrid" else display

    return {"display": display, "is_remote": flags["is_remote"], "is_hybrid": flags["is_hybrid"]}
