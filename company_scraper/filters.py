"""IT-oriented keyword filter for company scraper."""

from __future__ import annotations

INCLUDE_KEYWORDS = [
    "engineer",
    "developer",
    "devops",
    "cloud",
    "architect",
    "dba",
    "database",
    "infrastructure",
    "platform",
    "sre",
    "security",
    "network",
    "systems",
    "software",
    "backend",
    "frontend",
    "full stack",
    "fullstack",
    "qa",
    "quality assurance",
    "automation",
    "data",
    "ml",
    "machine learning",
    "ai",
    "analyst",
    "it ",
    "tech",
    "cyber",
    "api",
    "typescript",
    "javascript",
    "python",
    "java ",
    "site reliability",
    "production engineer",
    "web developer",
    "mobile",
    "ios",
    "android",
    "aws",
    "azure",
    "gcp",
    "devsecops",
]

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


def is_it_job(title: str, department: str = "") -> bool:
    text = f"{title or ''} {department or ''}".lower()
    if any(ex in text for ex in EXCLUDE_KEYWORDS):
        return False
    return any(kw in text for kw in INCLUDE_KEYWORDS)
