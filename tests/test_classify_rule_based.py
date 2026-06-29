"""Tests for the rule-based fallback classifier (classify_job_dynamically).

Real incident (2026-06-23): when zero keyword signals matched any MAAS role
family, the function defaulted to strongest_label="DevOps Engineer" with
apply_decision=APPLY - auto-approving completely unrelated roles (Data
Scientist, Engineering Program Manager, Sustainability Analyst, ...) at high
confidence whenever Gemini/OpenAI classification failed and this fallback
ran. Confirmed live: 12+ "Data Scientist" postings in production had
strongest_label="DevOps Engineer", confidence_score=100.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from classify_and_save import classify_job_dynamically


def test_zero_signal_job_is_out_of_scope_not_devops():
    job = {
        "job_title": "Senior Staff Data Scientist, Guest & Host Marketplace AI",
        "job_description": "Build statistical models and analyze marketplace data using Python and SQL.",
        "red_flags": [],
    }
    result = classify_job_dynamically(job)
    assert result["strongest_label"] == "OutOfScope"
    assert result["apply_decision"] == "DO_NOT_APPLY"
    assert result["red_flags"]


def test_zero_signal_job_low_confidence():
    job = {"job_title": "Engineering Program Manager", "job_description": "", "red_flags": []}
    result = classify_job_dynamically(job)
    assert result["confidence_score"] < 50


def test_genuine_devops_title_still_classified_correctly():
    job = {
        "job_title": "DevOps Engineer",
        "job_description": "Manage CI/CD pipelines and Kubernetes infrastructure.",
        "red_flags": [],
    }
    result = classify_job_dynamically(job)
    assert result["strongest_label"] == "DevOps Engineer"
    assert result["apply_decision"] == "APPLY"


def test_cloud_network_and_security_titles_remain_out_of_scope():
    for title in ("Cloud Network Engineer", "Cloud Security Engineer"):
        job = {"job_title": title, "job_description": "", "red_flags": []}
        result = classify_job_dynamically(job)
        assert result["strongest_label"] == "OutOfScope", title
        assert result["apply_decision"] == "DO_NOT_APPLY", title


def test_database_engineer_titles_are_out_of_scope():
    # Real incident (2026-06-25): Database Engineer/Cloud Database Engineer/DBA
    # were documented as retired alongside Cloud Network/Security Engineer
    # (2026-06-22), but - unlike those two - never got an explicit override
    # check, so they remained scoreable/APPLY-eligible in label_scores.
    # Confirmed live: 14 jobs titled "Database Engineer", "DBA Engineer",
    # "Senior Database Engineer II", etc. were auto-approved this way.
    for title in (
        "Database Engineer",
        "DBA Engineer",
        "Senior Database Engineer",
        "Senior Database Engineer II",
        "Junior Database Engineer",
    ):
        job = {"job_title": title, "job_description": "", "red_flags": []}
        result = classify_job_dynamically(job)
        assert result["strongest_label"] == "OutOfScope", title
        assert result["apply_decision"] == "DO_NOT_APPLY", title


def test_retired_data_platform_mlops_aiops_titles_are_out_of_scope():
    # Retired 2026-06-24 alongside Database/Network/Security Engineer families.
    # Without the explicit retired-title check, a title like "AI Platform
    # Engineer (AIOps)" still matched the generic "platform" in title
    # heuristic and was misclassified as Platform Engineering / APPLY.
    for title in (
        "Data Platform Engineer",
        "MLOps Engineer",
        "AI Platform Engineer (AIOps)",
        "Machine Learning Engineer",
    ):
        job = {"job_title": title, "job_description": "", "red_flags": []}
        result = classify_job_dynamically(job)
        assert result["strongest_label"] == "OutOfScope", title
        assert result["apply_decision"] == "DO_NOT_APPLY", title


def test_genuine_platform_engineering_title_still_classified_correctly():
    job = {"job_title": "Platform Engineer", "job_description": "", "red_flags": []}
    result = classify_job_dynamically(job)
    assert result["strongest_label"] == "Platform Engineering"
    assert result["apply_decision"] == "APPLY"


def test_automotive_engineering_titles_from_company_scraper_are_out_of_scope():
    # Confirmed live 2026-06-23: company_scraper/publisher.py never called any
    # classifier at all before this fix, so these landed in the Approved feed
    # labeled "DevOps Engineer" purely from publisher.py's hardcoded default.
    for title in ("Perception Software Engineer - ADAS", "Sr. Process Engineer, Body in White"):
        job = {"job_title": title, "job_description": "", "red_flags": []}
        result = classify_job_dynamically(job)
        assert result["strongest_label"] == "OutOfScope", title
        assert result["apply_decision"] == "DO_NOT_APPLY", title


def test_platform_engineering_description_signals_beat_competing_devops_title():
    # MAAS definition aligned 2026-06-27: Platform Engineering = Kubernetes
    # cluster lifecycle ownership + IDP + self-service workflows, distinct
    # from the DevOps Engineer default. A title that doesn't say "platform"
    # at all should still be pushed to Platform Engineering when the JD
    # clearly describes that scope.
    job = {
        "job_title": "Senior Engineer",
        "job_description": (
            "Own our Kubernetes cluster lifecycle including node pool autoscaling "
            "and multi-tenant kubernetes design. Build and maintain our Backstage-based "
            "internal developer platform with golden path templates for self-service deployments."
        ),
        "red_flags": [],
    }
    result = classify_job_dynamically(job)
    assert result["strongest_label"] == "Platform Engineering"
    assert result["apply_decision"] == "APPLY"


def test_devops_with_incidental_kubernetes_mention_stays_devops():
    # Bare "kubernetes" usage (deploying one app, no cluster-lifecycle/IDP
    # language) should not be enough to override a clear DevOps title.
    job = {
        "job_title": "DevOps Engineer",
        "job_description": (
            "Own CI/CD pipelines using Jenkins and GitHub Actions, deploy our app to "
            "Kubernetes using kubectl, manage Terraform infra, and monitor production with Datadog."
        ),
        "red_flags": [],
    }
    result = classify_job_dynamically(job)
    assert result["strongest_label"] == "DevOps Engineer"
    assert result["apply_decision"] == "APPLY"


def test_named_idp_products_recognized_in_description():
    for tool in ("morpheus", "harness idp"):
        job = {
            "job_title": "Engineer",
            "job_description": f"You will build and operate our internal developer platform using {tool}.",
            "red_flags": [],
        }
        result = classify_job_dynamically(job)
        assert result["strongest_label"] == "Platform Engineering", tool


def test_automotive_manufacturing_titles_are_out_of_scope():
    # Real incident (2026-06-29): a watched-company scrape of Lucid Motors
    # (an automotive manufacturer) auto-approved 17 manufacturing/automotive
    # engineering roles as MAAS DevOps/Cloud/SRE labels purely because
    # generic words in the titles ("automation", "integration", "system")
    # happened to match this classifier's keyword rules, with zero domain
    # context. None of these are genuine MAAS-relevant roles.
    for title in (
        "Sr. Automation Engineer, Powertrain",
        "Sr. Maintenance Engineer, Stamping Automation",
        "Sr. ADAS Systems Integration Engineer",
        "Sr. Plant Floor Systems Engineer",
        "Staff System Engineer – ADAS/AD Safety",
        "Sr. Automation Engineer, Paint",
        "Staff Engineer – Reliability & Test Methods, Drive Unit",
    ):
        job = {"job_title": title, "job_description": "", "red_flags": []}
        result = classify_job_dynamically(job)
        assert result["strongest_label"] == "OutOfScope", title
        assert result["apply_decision"] == "DO_NOT_APPLY", title


def test_automotive_keyword_does_not_block_role_with_real_cloud_evidence():
    # The automotive/manufacturing block only fires when there's NO cloud/
    # software evidence - a genuinely dual-domain role (e.g. cloud infra
    # for a vehicle's software stack, naming real tooling) should still
    # classify normally.
    job = {
        "job_title": "Cloud Infrastructure Engineer - ADAS Platform",
        "job_description": "Own AWS and Kubernetes infrastructure for our ADAS software stack, using Terraform and CI/CD pipelines.",
        "red_flags": [],
    }
    result = classify_job_dynamically(job)
    assert result["strongest_label"] != "OutOfScope"
    assert result["apply_decision"] == "APPLY"


def test_genuine_maas_titles_unaffected_by_automotive_check():
    for title in (
        "DevOps Engineer", "Senior Platform Engineer", "Site Reliability Engineer",
        "Cloud Automation Engineer", "CI/CD Pipeline Engineer", "System Engineer",
    ):
        job = {"job_title": title, "job_description": "", "red_flags": []}
        result = classify_job_dynamically(job)
        assert result["strongest_label"] != "OutOfScope", title
        assert result["apply_decision"] == "APPLY", title
