"""IT-oriented filter for company scraper: tiered score + per-user prefs."""

from __future__ import annotations

from typing import Any, Dict, List

# Hard excludes (non-IT or noisy) — instant reject
EXCLUDE_KEYWORDS = [
    "financial analyst",
    "hr ",
    "human resources",
    "marketing",
    "recruiter",
    "recruiting",
    "accountant",
    "legal",
    "paralegal",
    "operations manager",
    "sales representative",
    "administrative",
]

# Strong signals (software / infra / security engineering)
_STRONG: List[str] = [
    "software engineer",
    "software developer",
    "engineer",
    "developer",
    "devops",
    "sre",
    "site reliability",
    "cloud engineer",
    "platform engineer",
    "infrastructure",
    "backend",
    "frontend",
    "full stack",
    "fullstack",
    "web developer",
    "mobile developer",
    "android",
    "ios",
    "kubernetes",
    "docker",
    "aws",
    "azure",
    "gcp",
    "security engineer",
    "application security",
    "devsecops",
    "ml engineer",
    "machine learning engineer",
    "ai engineer",
    "data engineer",
    "database",
    "dba",
    "architect",
    "production engineer",
    "typescript",
    "javascript",
    "python",
    "java ",
    "api",
    "cyber",
    "network engineer",
    "systems engineer",
]

# Medium — tech-adjacent (can be tightened away with strict mode)
_MEDIUM: List[str] = [
    "qa",
    "quality assurance",
    "test automation",
    "automation engineer",
    "data scientist",
    "data analyst",
    "business analyst",
    "technical analyst",
    "it analyst",
    "analyst",
    "tech lead",
    "platform",
    "cloud",
    "automation",
]

_WEAK: List[str] = [
    "tech",
    "it ",
    "digital",
    "systems",
    "software",
]

DEFAULT_IT_PREFS: Dict[str, Any] = {
    "min_it_score": 0.28,
    "strict_engineering_only": False,
    "include_data_roles": True,
    "include_analyst_roles": True,
}


def merge_it_prefs(raw: Any) -> Dict[str, Any]:
    out = dict(DEFAULT_IT_PREFS)
    if isinstance(raw, dict):
        for k, v in raw.items():
            if k in out:
                out[k] = v
    try:
        out["min_it_score"] = float(out["min_it_score"])
    except (TypeError, ValueError):
        out["min_it_score"] = DEFAULT_IT_PREFS["min_it_score"]
    out["min_it_score"] = max(0.0, min(1.0, out["min_it_score"]))
    for b in ("strict_engineering_only", "include_data_roles", "include_analyst_roles"):
        out[b] = bool(out.get(b, DEFAULT_IT_PREFS[b]))
    return out


def it_job_score(title: str, department: str = "") -> float:
    """0 = not IT / excluded; higher = stronger tech signal."""
    text = f"{title or ''} {department or ''}".lower()
    if any(ex in text for ex in EXCLUDE_KEYWORDS):
        return 0.0
    if any(k in text for k in _STRONG):
        return 1.0
    if any(k in text for k in _MEDIUM):
        return 0.52
    if any(k in text for k in _WEAK):
        return 0.22
    return 0.0


def passes_it_job(title: str, department: str = "", prefs: Dict[str, Any] | None = None) -> bool:
    """Tiered IT gate with optional user prefs (from user_configs.company_scraper_it)."""
    p = merge_it_prefs(prefs)
    text = f"{title or ''} {department or ''}".lower()
    if any(ex in text for ex in EXCLUDE_KEYWORDS):
        return False

    if not p.get("include_data_roles", True):
        if any(x in text for x in ("data scientist", "data analyst")) and not any(
            k in text for k in _STRONG
        ):
            return False
    if not p.get("include_analyst_roles", True):
        if "analyst" in text and "engineer" not in text and "developer" not in text:
            return False

    score = 0.0
    if any(k in text for k in _STRONG):
        score = 1.0
    elif any(k in text for k in _MEDIUM):
        score = 0.52
    elif any(k in text for k in _WEAK):
        score = 0.22

    if p.get("strict_engineering_only") and score < 1.0:
        return False
    return score >= p["min_it_score"]


def is_it_job(title: str, department: str = "") -> bool:
    """Backward-compatible default prefs."""
    return passes_it_job(title, department, None)
