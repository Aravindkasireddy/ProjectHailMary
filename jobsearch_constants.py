"""
Shared defaults for MAAS jobsearch (Python entrypoints).
Keep dashboard default target list aligned with GET /api/config/default-target-titles.
"""

# Sourcing titles: used as search query strings and discovery filters.
DEFAULT_TARGET_TITLES = [
    # Infrastructure / DevOps core
    "DevOps Engineer",
    "Cloud Automation Engineer",
    "Platform Engineering",
    "Cloud Infrastructure Engineer",
    "DevSecOps",
    "Site Reliability Engineer (SRE)",
    "Continuous Integration (CI/CD)",
    "System Engineer",
    # Security / Fraud / Detection (add-ons)
    "Fraud Data Scientist",
    "Fraud Analytics Data Scientist",
    "Risk Data Scientist",
    "AML Data Scientist",
    "Fraud Risk Data Scientist",
    "Detection Engineer",
    "Threat Detection Engineer",
    "Detection and Response Engineer",
    "Security Detection Engineer",
    "Cloud Security Engineer",
    "Cloud Security Analyst",
    "Cloud Security Architect",
    "DevSecOps Engineer",
    "Application Security Engineer",
]

ALLOWED_STRONGEST_LABELS = frozenset(
    {
        "DevOps Engineer",
        "Cloud Automation Engineer",
        "Platform Engineering",
        "Cloud Infrastructure Engineer",
        "DevSecOps",
        "Site Reliability Engineer (SRE)",
        "Continuous Integration (CI/CD)",
        "System Engineer",
        "Cloud Security Engineer",
        "Threat Detection Engineer",
        "Fraud Data Scientist",
        "Application Security Engineer",
        "OutOfScope",
    }
)
