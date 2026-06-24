"""
Shared defaults for MAAS jobsearch (Python entrypoints).
Keep dashboard default target list aligned with GET /api/config/default-target-titles.
"""

# Sourcing titles: same strings as ## ROLE LABELS in Job_classifier_prompt.txt (excluding OutOfScope).
DEFAULT_TARGET_TITLES = [
    "DevOps Engineer",
    "Cloud Automation Engineer",
    "Platform Engineering",
    "Cloud Infrastructure Engineer",
    "DevSecOps",
    "Site Reliability Engineer (SRE)",
    "Continuous Integration (CI/CD)",
    "System Engineer",
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
        "OutOfScope",
    }
)
