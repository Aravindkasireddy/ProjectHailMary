import json
import os
import sys
import time
import hashlib
from pathlib import Path
from urllib.parse import urlparse
from dotenv import load_dotenv
import google.generativeai as genai

def compute_description_hash(description):
    if not description:
        return ""
    normalized = "".join(description.lower().split())
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()

def load_known_hashes(workspace_path):
    approved_hashes = {}
    failed_hashes = {}
    
    approved_path = workspace_path / "approved_jobs.json"
    if approved_path.exists():
        try:
            jobs = json.loads(approved_path.read_text(encoding="utf-8"))
            for j in jobs:
                h = j.get("description_hash")
                if not h and j.get("job_description"):
                    h = compute_description_hash(j["job_description"])
                if h:
                    approved_hashes[h] = j
        except Exception as e:
            print(f"Error loading approved hashes: {e}")
            
    failed_path = workspace_path / "failed_candidate_jobs.json"
    if failed_path.exists():
        try:
            jobs = json.loads(failed_path.read_text(encoding="utf-8"))
            for j in jobs:
                h = j.get("description_hash")
                if not h and j.get("job_description"):
                    h = compute_description_hash(j["job_description"])
                if h:
                    failed_hashes[h] = j
        except Exception as e:
            print(f"Error loading failed hashes: {e}")
            
    return approved_hashes, failed_hashes


_scripts_dir = Path(__file__).resolve().parent
_repo_root = _scripts_dir.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))
from jobsearch_paths import workspace_root

WORKSPACE = workspace_root()
load_dotenv(dotenv_path=str(WORKSPACE / ".env"))
api_key = os.getenv("GEMINI_API_KEY")
if api_key:
    genai.configure(api_key=api_key)

def get_job_classifications():
    classifications = {}
    
    # Candidate 1: Actian - AI Engineer Intern
    classifications[1] = {
        "apply_decision": "DO_NOT_APPLY",
        "strongest_label": "OutOfScope",
        "confidence_score": 100,
        "red_flags": ["Salary rule"],
        "rationale": "The role is an internship offering $20-$30 per hour, which violates the hourly salary minimum of > $50/hr. It is also an AI/RAG intern role, which is out of scope for MAAS engineering.",
        "payload": {
            "all_labels": ["OutOfScope"],
            "strongest_label": "OutOfScope",
            "other_labels": [],
            "apply_decision": "DO_NOT_APPLY",
            "red_flags": ["Salary rule"],
            "filters": {"domain_specialization": False},
            "confidence_score": 100,
            "cloud": {"is_cloud_role": False, "primary_cloud": "", "cloud_providers": []},
            "domain_scores": {k: 0 for k in ["database", "cloud_database", "network", "infrastructure", "platform", "automation", "devops", "cicd", "sre", "security", "devsecops", "system", "data", "mlops", "aiops"]},
            "dominant_domains": [],
            "dominant_signals": {k: [] for k in ["database", "network", "infrastructure", "platform", "automation", "devops", "sre"]},
            "decision_trace": {"top_score": 0, "runner_up_score": 0, "tie_break_applied": False, "priority_rule_used": "", "strong_signal_override": False},
            "rationale": "The role is an internship offering $20-$30 per hour, which violates the hourly salary minimum of > $50/hr. It is also an AI/RAG intern role, which is out of scope for MAAS engineering.",
            "rationale_formatted": ["Internship paying hourly below $50/hr threshold ($20-$30/hr)", "Role is primarily focused on AI/RAG applications rather than DevOps/infrastructure engineering"]
        }
    }
    
    # Candidate 2: Cambiumlearning - Senior Database Engineer II
    classifications[2] = {
        "apply_decision": "APPLY",
        "strongest_label": "Cloud Database Engineer",
        "confidence_score": 95,
        "red_flags": [],
        "req_id_override": "REQ-4234",
        "rationale": "The role focuses on SQL Server development and administration in AWS (RDS, EC2) with 5+ years of experience. Responsibilities include schema design, performance tuning, and optimizing data access from microservices in AWS.",
        "payload": {
            "all_labels": ["Cloud Database Engineer", "Database Engineer"],
            "strongest_label": "Cloud Database Engineer",
            "other_labels": ["Database Engineer"],
            "apply_decision": "APPLY",
            "red_flags": [],
            "filters": {"domain_specialization": False},
            "confidence_score": 95,
            "cloud": {"is_cloud_role": True, "primary_cloud": "AWS", "cloud_providers": ["AWS"]},
            "domain_scores": {
                "database": 5, "cloud_database": 6, "network": 0, "infrastructure": 0, "platform": 0, "automation": 0, "devops": 0, "cicd": 0, "sre": 0, "security": 0, "devsecops": 0, "system": 0, "data": 0, "mlops": 0, "aiops": 0
            },
            "dominant_domains": ["cloud_database", "database"],
            "dominant_signals": {
                "database": ["SQL Server development", "stored procedures", "triggers", "stored functions", "schema design", "performance tuning", "backup and recovery"],
                "network": [],
                "infrastructure": [],
                "platform": [],
                "automation": ["deployment and rollback scripts"],
                "devops": [],
                "sre": []
            },
            "decision_trace": {"top_score": 6, "runner_up_score": 5, "tie_break_applied": False, "priority_rule_used": "", "strong_signal_override": False},
            "rationale": "The role focuses on SQL Server development and administration in AWS (RDS, EC2) with 5+ years of experience. Responsibilities include schema design, performance tuning, and optimizing data access from microservices in AWS.",
            "rationale_formatted": [
                "5+ years of SQL Server development and database administration experience",
                "Strong focus on AWS database platforms (RDS for SQL Server, EC2)",
                "Handles data modeling, schema design, and microservices integration in AWS",
                "No red flags or sponsorship restrictions detected"
            ]
        }
    }
    
    # Candidate 3: Razer - Senior Database Engineer
    classifications[3] = {
        "apply_decision": "DO_NOT_APPLY",
        "strongest_label": "OutOfScope",
        "confidence_score": 100,
        "red_flags": ["Out of scope"],
        "rationale": "The role is located in Malaysia (Shah Alam / i-City office), which does not satisfy the requirement for US-based remote or hybrid engineering roles.",
        "payload": {
            "all_labels": ["OutOfScope"],
            "strongest_label": "OutOfScope",
            "other_labels": [],
            "apply_decision": "DO_NOT_APPLY",
            "red_flags": ["Out of scope"],
            "filters": {"domain_specialization": False},
            "confidence_score": 100,
            "cloud": {"is_cloud_role": False, "primary_cloud": "", "cloud_providers": []},
            "domain_scores": {k: 0 for k in ["database", "cloud_database", "network", "infrastructure", "platform", "automation", "devops", "cicd", "sre", "security", "devsecops", "system", "data", "mlops", "aiops"]},
            "dominant_domains": [],
            "dominant_signals": {k: [] for k in ["database", "network", "infrastructure", "platform", "automation", "devops", "sre"]},
            "decision_trace": {"top_score": 0, "runner_up_score": 0, "tie_break_applied": False, "priority_rule_used": "", "strong_signal_override": False},
            "rationale": "The role is located in Malaysia (Shah Alam / i-City office), which does not satisfy the requirement for US-based remote or hybrid engineering roles.",
            "rationale_formatted": ["Location is Malaysia (Shah Alam / i-City office)", "Not a US-based remote or hybrid engineering role"]
        }
    }
    
    # Candidate 4: Entefy - Sr. DevOps Engineer
    classifications[4] = {
        "apply_decision": "APPLY",
        "strongest_label": "DevOps Engineer",
        "confidence_score": 90,
        "red_flags": [],
        "req_id_override": "cd590dd7-36b1-4296-9f5d-764c663ef578",
        "rationale": "The role requires 6+ years of experience in deployment automation, networking, and server deployment. Since the role spans multiple automation domains without a single dominant specialization, it is classified under the default DevOps Engineer label.",
        "payload": {
            "all_labels": ["DevOps Engineer"],
            "strongest_label": "DevOps Engineer",
            "other_labels": [],
            "apply_decision": "APPLY",
            "red_flags": [],
            "filters": {"domain_specialization": False},
            "confidence_score": 90,
            "cloud": {"is_cloud_role": False, "primary_cloud": "", "cloud_providers": []},
            "domain_scores": {
                "database": 0, "cloud_database": 0, "network": 3, "infrastructure": 0, "platform": 0, "automation": 4, "devops": 4, "cicd": 0, "sre": 0, "security": 0, "devsecops": 0, "system": 0, "data": 0, "mlops": 0, "aiops": 0
            },
            "dominant_domains": ["devops", "automation"],
            "dominant_signals": {
                "database": [],
                "network": ["computer networks"],
                "infrastructure": [],
                "platform": [],
                "automation": ["deployment automation"],
                "devops": ["DevOps Engineer title", "uptime", "fault tolerance"],
                "sre": []
            },
            "decision_trace": {"top_score": 4, "runner_up_score": 4, "tie_break_applied": True, "priority_rule_used": "Choose broader default label for multi-domain automation roles", "strong_signal_override": False},
            "rationale": "The role requires 6+ years of experience in deployment automation, networking, and server deployment. Since the role spans multiple automation domains without a single dominant specialization, it is classified under the default DevOps Engineer label.",
            "rationale_formatted": [
                "6+ years of experience in deployment automation, secure systems, and fault tolerance",
                "Broad responsibilities spanning servers, networking, and deployment",
                "Fits the default DevOps Engineer category due to cross-functional automation scope",
                "No red flags or sponsorship restrictions detected"
            ]
        }
    }
    
    # Candidate 5: Bluelightconsulting - DevOps Engineer
    classifications[5] = {
        "apply_decision": "DO_NOT_APPLY",
        "strongest_label": "DevOps Engineer",
        "confidence_score": 85,
        "red_flags": ["Experience requirement violation"],
        "rationale": "The job description fails to specify any years of experience requirement, which violates the MAAS policy experience rules requiring explicit experience statements.",
        "payload": {
            "all_labels": ["DevOps Engineer"],
            "strongest_label": "DevOps Engineer",
            "other_labels": [],
            "apply_decision": "DO_NOT_APPLY",
            "red_flags": ["Experience requirement violation"],
            "filters": {"domain_specialization": False},
            "confidence_score": 85,
            "cloud": {"is_cloud_role": True, "primary_cloud": "", "cloud_providers": ["AWS", "GCP", "Azure"]},
            "domain_scores": {"devops": 3, "automation": 3},
            "dominant_domains": ["devops"],
            "dominant_signals": {k: [] for k in ["database", "network", "infrastructure", "platform", "automation", "devops", "sre"]},
            "decision_trace": {"top_score": 3, "runner_up_score": 3, "tie_break_applied": False, "priority_rule_used": "", "strong_signal_override": False},
            "rationale": "The job description fails to specify any years of experience requirement, which violates the MAAS policy experience rules requiring explicit experience statements.",
            "rationale_formatted": ["No years of experience mentioned in the job description", "Triggers experience requirement violation red flag"]
        }
    }
    
    # Candidate 6: Fico - DevOps Engineer (Kubernetes)
    classifications[6] = {
        "apply_decision": "DO_NOT_APPLY",
        "strongest_label": "DevOps Engineer",
        "confidence_score": 85,
        "red_flags": ["Experience requirement violation"],
        "rationale": "The job description does not mention any required years of experience, which triggers the 'no experience mentioned' red flag policy override.",
        "payload": {
            "all_labels": ["DevOps Engineer"],
            "strongest_label": "DevOps Engineer",
            "other_labels": [],
            "apply_decision": "DO_NOT_APPLY",
            "red_flags": ["Experience requirement violation"],
            "filters": {"domain_specialization": False},
            "confidence_score": 85,
            "cloud": {"is_cloud_role": True, "primary_cloud": "AWS", "cloud_providers": ["AWS"]},
            "domain_scores": {"devops": 3, "automation": 3},
            "dominant_domains": ["devops"],
            "dominant_signals": {k: [] for k in ["database", "network", "infrastructure", "platform", "automation", "devops", "sre"]},
            "decision_trace": {"top_score": 3, "runner_up_score": 3, "tie_break_applied": False, "priority_rule_used": "", "strong_signal_override": False},
            "rationale": "The job description does not mention any required years of experience, which triggers the 'no experience mentioned' red flag policy override.",
            "rationale_formatted": ["No years of experience mentioned in the job description", "Triggers experience requirement violation red flag"]
        }
    }
    
    # Candidate 7: Abbott - Senior Cybersecurity Engineer
    classifications[7] = {
        "apply_decision": "DO_NOT_APPLY",
        "strongest_label": "OutOfScope",
        "confidence_score": 100,
        "red_flags": ["Out of scope"],
        "rationale": "The role is for a Senior Cybersecurity Engineer focusing on product security risk, threat modeling, and application security scanning (SAST/DAST/Burp Suite) for medical devices, which is out of scope for the MAAS engineering categories.",
        "payload": {
            "all_labels": ["OutOfScope"],
            "strongest_label": "OutOfScope",
            "other_labels": [],
            "apply_decision": "DO_NOT_APPLY",
            "red_flags": ["Out of scope"],
            "filters": {"domain_specialization": False},
            "confidence_score": 100,
            "cloud": {"is_cloud_role": False, "primary_cloud": "", "cloud_providers": []},
            "domain_scores": {k: 0 for k in ["database", "cloud_database", "network", "infrastructure", "platform", "automation", "devops", "cicd", "sre", "security", "devsecops", "system", "data", "mlops", "aiops"]},
            "dominant_domains": [],
            "dominant_signals": {k: [] for k in ["database", "network", "infrastructure", "platform", "automation", "devops", "sre"]},
            "decision_trace": {"top_score": 0, "runner_up_score": 0, "tie_break_applied": False, "priority_rule_used": "", "strong_signal_override": False},
            "rationale": "The role is for a Senior Cybersecurity Engineer focusing on product security risk, threat modeling, and application security scanning (SAST/DAST/Burp Suite) for medical devices, which is out of scope for the MAAS engineering categories.",
            "rationale_formatted": ["Product security and application scanning focus for medical devices", "Does not fall under DevOps/infrastructure/database engineering"]
        }
    }
    
    # Candidate 8: Fico - Senior DevOps Engineer - Kubernetes
    classifications[8] = {
        "apply_decision": "DO_NOT_APPLY",
        "strongest_label": "DevOps Engineer",
        "confidence_score": 85,
        "red_flags": ["Experience requirement violation"],
        "rationale": "The job description does not list any required years of experience, which violates the policy's experience check (triggers 'no experience mentioned' flag).",
        "payload": {
            "all_labels": ["DevOps Engineer"],
            "strongest_label": "DevOps Engineer",
            "other_labels": [],
            "apply_decision": "DO_NOT_APPLY",
            "red_flags": ["Experience requirement violation"],
            "filters": {"domain_specialization": False},
            "confidence_score": 85,
            "cloud": {"is_cloud_role": True, "primary_cloud": "AWS", "cloud_providers": ["AWS"]},
            "domain_scores": {"devops": 3, "automation": 3},
            "dominant_domains": ["devops"],
            "dominant_signals": {k: [] for k in ["database", "network", "infrastructure", "platform", "automation", "devops", "sre"]},
            "decision_trace": {"top_score": 3, "runner_up_score": 3, "tie_break_applied": False, "priority_rule_used": "", "strong_signal_override": False},
            "rationale": "The job description does not list any required years of experience, which violates the policy's experience check (triggers 'no experience mentioned' flag).",
            "rationale_formatted": ["No years of experience mentioned in the job description", "Triggers experience requirement violation red flag"]
        }
    }
    
    # Candidate 9: Icf - Salesforce DevOps Engineer
    classifications[9] = {
        "apply_decision": "APPLY",
        "strongest_label": "Continuous Integration (CI/CD)",
        "confidence_score": 85,
        "red_flags": [],
        "rationale": "The role requires 4+ years of experience in release engineering, deployment automation, and CI/CD pipelines, specifically utilizing Copado for Salesforce environments, making it a strong fit for Continuous Integration (CI/CD).",
        "payload": {
            "all_labels": ["Continuous Integration (CI/CD)", "DevOps Engineer"],
            "strongest_label": "Continuous Integration (CI/CD)",
            "other_labels": ["DevOps Engineer"],
            "apply_decision": "APPLY",
            "red_flags": [],
            "filters": {"domain_specialization": False},
            "confidence_score": 85,
            "cloud": {"is_cloud_role": False, "primary_cloud": "", "cloud_providers": []},
            "domain_scores": {
                "cicd": 5, "devops": 4, "database": 0, "cloud_database": 0, "network": 0, "infrastructure": 0, "platform": 0, "automation": 3, "sre": 0, "security": 0, "devsecops": 0, "system": 0, "data": 0, "mlops": 0, "aiops": 0
            },
            "dominant_domains": ["cicd", "devops"],
            "dominant_signals": {
                "database": [],
                "network": [],
                "infrastructure": [],
                "platform": [],
                "automation": ["deployment automation", "automated testing"],
                "devops": ["Salesforce DevOps Engineer title", "DevSecOps practices"],
                "sre": []
            },
            "decision_trace": {"top_score": 5, "runner_up_score": 4, "tie_break_applied": False, "priority_rule_used": "", "strong_signal_override": False},
            "rationale": "The role requires 4+ years of experience in release engineering, deployment automation, and CI/CD pipelines, specifically utilizing Copado for Salesforce environments, making it a strong fit for Continuous Integration (CI/CD).",
            "rationale_formatted": [
                "4+ years of release engineering and deployment automation experience",
                "Focused on Salesforce release management using Copado and Git version control",
                "Responsible for CI/CD pipelines, automated testing integrations, and sandbox management",
                "No red flags or sponsorship restrictions detected"
            ]
        }
    }
    
    # Candidate 10: Jobgether - Site Reliability Engineer (SRE)
    classifications[10] = {
        "apply_decision": "APPLY",
        "strongest_label": "Site Reliability Engineer (SRE)",
        "confidence_score": 98,
        "red_flags": [],
        "rationale": "The role is explicitly for a Site Reliability Engineer, requiring 5+ years of experience. Responsibilities are heavily centered on SRE core practices (SLIs/SLOs, error budgets, incident response, chaos engineering, and observability with Prometheus/Grafana/OpenTelemetry).",
        "payload": {
            "all_labels": ["Site Reliability Engineer (SRE)"],
            "strongest_label": "Site Reliability Engineer (SRE)",
            "other_labels": [],
            "apply_decision": "APPLY",
            "red_flags": [],
            "filters": {"domain_specialization": False},
            "confidence_score": 98,
            "cloud": {"is_cloud_role": True, "primary_cloud": "", "cloud_providers": ["AWS", "Azure", "GCP"]},
            "domain_scores": {
                "sre": 7, "devops": 4, "database": 0, "cloud_database": 0, "network": 0, "infrastructure": 0, "platform": 0, "automation": 3, "cicd": 0, "security": 0, "devsecops": 0, "system": 0, "data": 0, "mlops": 0, "aiops": 0
            },
            "dominant_domains": ["sre", "observability"],
            "dominant_signals": {
                "database": [],
                "network": [],
                "infrastructure": [],
                "platform": [],
                "automation": ["automation tools", "CI/CD pipelines"],
                "devops": [],
                "sre": ["SLOs", "SLIs", "error budget management", "incident response", "observability frameworks", "Prometheus", "Grafana", "chaos engineering"]
            },
            "decision_trace": {"top_score": 7, "runner_up_score": 4, "tie_break_applied": False, "priority_rule_used": "", "strong_signal_override": False},
            "rationale": "The role is explicitly for a Site Reliability Engineer, requiring 5+ years of experience. Responsibilities are heavily centered on SRE core practices (SLIs/SLOs, error budgets, incident response, chaos engineering, and observability with Prometheus/Grafana/OpenTelemetry).",
            "rationale_formatted": [
                "5+ years of SRE/DevOps experience",
                "Focuses heavily on SRE fundamentals (SLIs, SLOs, incident response)",
                "Requires expertise in observability tools (Prometheus, Grafana, OpenTelemetry)",
                "No red flags; explicitly offers H1B transfer support"
            ]
        }
    }
    
    # Candidate 11: Outsystems - Senior Site Reliability Engineer
    classifications[11] = {
        "apply_decision": "APPLY",
        "strongest_label": "Site Reliability Engineer (SRE)",
        "confidence_score": 98,
        "red_flags": [],
        "rationale": "The role is a Senior Site Reliability Engineer requiring 6+ years of SRE experience. Key responsibilities include managing SLAs, SLOs, incident management, MTTA/MTTR KPIs, on-call rotation, and Prometheus/Grafana monitoring.",
        "payload": {
            "all_labels": ["Site Reliability Engineer (SRE)"],
            "strongest_label": "Site Reliability Engineer (SRE)",
            "other_labels": [],
            "apply_decision": "APPLY",
            "red_flags": [],
            "filters": {"domain_specialization": False},
            "confidence_score": 98,
            "cloud": {"is_cloud_role": True, "primary_cloud": "AWS", "cloud_providers": ["AWS"]},
            "domain_scores": {
                "sre": 7, "devops": 4, "database": 0, "cloud_database": 0, "network": 0, "infrastructure": 0, "platform": 0, "automation": 3, "cicd": 0, "security": 0, "devsecops": 0, "system": 0, "data": 0, "mlops": 0, "aiops": 0
            },
            "dominant_domains": ["sre", "observability"],
            "dominant_signals": {
                "database": [],
                "network": [],
                "infrastructure": [],
                "platform": [],
                "automation": ["automation of operational tasks", "IaC"],
                "devops": [],
                "sre": ["SLOs", "SLAs", "monitoring", "alerting", "logging", "tracing", "incident response", "RCA/post-mortems", "MTTA", "MTTR"]
            },
            "decision_trace": {"top_score": 7, "runner_up_score": 4, "tie_break_applied": False, "priority_rule_used": "", "strong_signal_override": False},
            "rationale": "The role is a Senior Site Reliability Engineer requiring 6+ years of SRE experience. Key responsibilities include managing SLAs, SLOs, incident management, MTTA/MTTR KPIs, on-call rotation, and Prometheus/Grafana monitoring.",
            "rationale_formatted": [
                "6+ years of SRE experience managing infrastructure at scale",
                "Full SRE responsibilities including SLAs, SLOs, and MTTA/MTTR KPIs",
                "Tech stack includes AWS, Kubernetes/EKS, Prometheus, Grafana, and Python",
                "No visa/citizenship restrictions or other red flags detected"
            ]
        }
    }
    
    # Candidate 12: Veritone - Site Reliability Engineer
    classifications[12] = {
        "apply_decision": "APPLY",
        "strongest_label": "Site Reliability Engineer (SRE)",
        "confidence_score": 95,
        "red_flags": [],
        "rationale": "The role is a Site Reliability Engineer II requiring 7+ years of systems management experience. Key responsibilities include managing SLAs, auto-remediation, incident response, on-call rotation, Prometheus/Grafana monitoring, and ArgoCD/GitOps.",
        "payload": {
            "all_labels": ["Site Reliability Engineer (SRE)"],
            "strongest_label": "Site Reliability Engineer (SRE)",
            "other_labels": [],
            "apply_decision": "APPLY",
            "red_flags": [],
            "filters": {"domain_specialization": False},
            "confidence_score": 95,
            "cloud": {"is_cloud_role": True, "primary_cloud": "AWS", "cloud_providers": ["AWS", "Azure", "GCP"]},
            "domain_scores": {
                "sre": 6, "devops": 4, "database": 0, "cloud_database": 0, "network": 0, "infrastructure": 0, "platform": 0, "automation": 4, "cicd": 0, "security": 0, "devsecops": 0, "system": 0, "data": 0, "mlops": 0, "aiops": 0
            },
            "dominant_domains": ["sre", "observability"],
            "dominant_signals": {
                "database": [],
                "network": [],
                "infrastructure": [],
                "platform": [],
                "automation": ["CI/CD pipelines", "automating deployments", "disaster recovery"],
                "devops": [],
                "sre": ["SLA", "incident response", "auto-remediation", "on-call rotation", "observability", "Prometheus", "Grafana", "Thanos", "RCA", "post-mortems"]
            },
            "decision_trace": {"top_score": 6, "runner_up_score": 4, "tie_break_applied": False, "priority_rule_used": "", "strong_signal_override": False},
            "rationale": "The role is a Site Reliability Engineer II requiring 7+ years of systems management experience. Key responsibilities include managing SLAs, auto-remediation, incident response, on-call rotation, Prometheus/Grafana monitoring, and ArgoCD/GitOps.",
            "rationale_formatted": [
                "7+ years of systems and software management experience",
                "Strong focus on SRE practices (SLAs, incident response, RCAs, auto-remediation)",
                "Uses AWS/Azure, Kubernetes, Terraform, ArgoCD, Prometheus, and Grafana",
                "No visa/citizenship restrictions or other red flags detected"
            ]
        }
    }
    
    # Candidate 13: Aledade - Senior Data Platform Engineer II
    classifications[13] = {
        "apply_decision": "APPLY",
        "strongest_label": "Data Platform Engineer",
        "confidence_score": 95,
        "red_flags": [],
        "req_id_override": "e7c0c6cc-7d22-4ca4-8484-f5f2e5c59eba",
        "rationale": "The role is for a Senior Data Platform Engineer II, focusing on architecting and managing Databricks Lakehouse and Snowflake data environments, building ETL pipelines, and utilizing Terraform for infrastructure automation, aligning perfectly with Data Platform Engineer.",
        "payload": {
            "all_labels": ["Data Platform Engineer"],
            "strongest_label": "Data Platform Engineer",
            "other_labels": [],
            "apply_decision": "APPLY",
            "red_flags": [],
            "filters": {"domain_specialization": False},
            "confidence_score": 95,
            "cloud": {"is_cloud_role": True, "primary_cloud": "AWS", "cloud_providers": ["AWS"]},
            "domain_scores": {
                "data": 6, "automation": 4, "database": 0, "cloud_database": 0, "network": 0, "infrastructure": 0, "platform": 0, "devops": 0, "cicd": 0, "sre": 0, "security": 0, "devsecops": 0, "system": 0, "mlops": 0, "aiops": 0
            },
            "dominant_domains": ["data", "automation"],
            "dominant_signals": {
                "database": [],
                "network": [],
                "infrastructure": [],
                "platform": [],
                "automation": ["Terraform", "CI/CD pipelines"],
                "devops": [],
                "sre": []
            },
            "decision_trace": {"top_score": 6, "runner_up_score": 4, "tie_break_applied": False, "priority_rule_used": "", "strong_signal_override": False},
            "rationale": "The role is for a Senior Data Platform Engineer II, focusing on architecting and managing Databricks Lakehouse and Snowflake data environments, building ETL pipelines, and utilizing Terraform for infrastructure automation, aligning perfectly with Data Platform Engineer.",
            "rationale_formatted": [
                "6+ years of experience building and optimizing scalable distributed data systems",
                "Deep expertise in Databricks, Spark, Snowflake, and Unity Catalog",
                "Uses Terraform for automating data infrastructure provisioning",
                "No red flags or sponsorship restrictions detected"
            ]
        }
    }
    
    # Candidate 14: Epiqsystems - Platform Engineer
    classifications[14] = {
        "apply_decision": "APPLY",
        "strongest_label": "Platform Engineering",
        "confidence_score": 95,
        "red_flags": [],
        "rationale": "The role is for a Platform Engineer, requiring 5+ years of experience. Key responsibilities center on building and evolving the core systems of the AIDA platform (including IAM systems, multi-tenant databases, distributed systems, and storage layouts), which fits Platform Engineering.",
        "payload": {
            "all_labels": ["Platform Engineering"],
            "strongest_label": "Platform Engineering",
            "other_labels": [],
            "apply_decision": "APPLY",
            "red_flags": [],
            "filters": {"domain_specialization": False},
            "confidence_score": 95,
            "cloud": {"is_cloud_role": True, "primary_cloud": "Azure", "cloud_providers": ["Azure"]},
            "domain_scores": {
                "platform": 6, "database": 4, "cloud_database": 0, "network": 0, "infrastructure": 0, "automation": 3, "devops": 0, "cicd": 0, "sre": 0, "security": 0, "devsecops": 0, "system": 0, "data": 0, "mlops": 0, "aiops": 0
            },
            "dominant_domains": ["platform", "database"],
            "dominant_signals": {
                "database": ["PostgreSQL", "Solr", "Qdrant", "multi-tenant database architectures"],
                "network": [],
                "infrastructure": [],
                "platform": ["Platform Engineer title", "Kubernetes", "internal platforms"],
                "automation": ["Terraform"],
                "devops": [],
                "sre": []
            },
            "decision_trace": {"top_score": 6, "runner_up_score": 4, "tie_break_applied": False, "priority_rule_used": "", "strong_signal_override": False},
            "rationale": "The role is for a Platform Engineer, requiring 5+ years of experience. Key responsibilities center on building and evolving the core systems of the AIDA platform (including IAM systems, multi-tenant databases, distributed systems, and storage layouts), which fits Platform Engineering.",
            "rationale_formatted": [
                "5+ years of experience in platform or infrastructure engineering",
                "Responsible for core platform design, database architecture, and identity foundations",
                "Utilizes Azure, Terraform, Kubernetes, PostgreSQL, Qdrant, and Prometheus",
                "No visa/citizenship restrictions or other red flags detected"
            ]
        }
    }
    
    # Candidate 15: Veritone - Sr. Platform Engineer
    classifications[15] = {
        "apply_decision": "APPLY",
        "strongest_label": "Platform Engineering",
        "confidence_score": 98,
        "red_flags": [],
        "rationale": "The role is for a Senior Platform Engineer, focusing on designing and maintaining an internal developer platform, high-availability Kubernetes clusters, and GitOps workflows. Requirements include Kubernetes mastery, Go development experience, Helm charts, and ArgoCD.",
        "payload": {
            "all_labels": ["Platform Engineering"],
            "strongest_label": "Platform Engineering",
            "other_labels": [],
            "apply_decision": "APPLY",
            "red_flags": [],
            "filters": {"domain_specialization": False},
            "confidence_score": 98,
            "cloud": {"is_cloud_role": True, "primary_cloud": "AWS", "cloud_providers": ["AWS", "Azure", "GCP"]},
            "domain_scores": {
                "platform": 7, "automation": 5, "database": 0, "cloud_database": 0, "network": 0, "infrastructure": 0, "devops": 0, "cicd": 0, "sre": 0, "security": 0, "devsecops": 0, "system": 0, "data": 0, "mlops": 0, "aiops": 0
            },
            "dominant_domains": ["platform", "automation"],
            "dominant_signals": {
                "database": [],
                "network": [],
                "infrastructure": [],
                "platform": ["internal developer platform", "Kubernetes mastery", "EKS", "AKS", "RKE2"],
                "automation": ["ArgoCD", "GitOps", "Helm", "process automation"],
                "devops": [],
                "sre": []
            },
            "decision_trace": {"top_score": 7, "runner_up_score": 5, "tie_break_applied": False, "priority_rule_used": "", "strong_signal_override": False},
            "rationale": "The role is for a Senior Platform Engineer, focusing on designing and maintaining an internal developer platform, high-availability Kubernetes clusters, and GitOps workflows. Requirements include Kubernetes mastery, Go development experience, Helm charts, and ArgoCD.",
            "rationale_formatted": [
                "2+ years of Helm and Cloud experience, with Go programming skills",
                "Focuses on internal developer platform and Kubernetes cluster lifecycle",
                "Uses GitOps (ArgoCD), Helm, AWS/GCP/Azure, and Go development",
                "No visa/citizenship restrictions or other red flags detected"
            ]
        }
    }
    
    # Candidate 16: Ksmcpa - Cloud Infrastructure Engineer
    classifications[16] = {
        "apply_decision": "APPLY",
        "strongest_label": "Cloud Infrastructure Engineer",
        "confidence_score": 95,
        "red_flags": [],
        "rationale": "The role is for a Cloud Infrastructure Engineer, requiring a minimum of 3 years of cloud experience. Key responsibilities center on building, configuring, and maintaining AWS cloud infrastructure components (compute, storage, and networking) and automating provisioning using Terraform.",
        "payload": {
            "all_labels": ["Cloud Infrastructure Engineer"],
            "strongest_label": "Cloud Infrastructure Engineer",
            "other_labels": [],
            "apply_decision": "APPLY",
            "red_flags": [],
            "filters": {"domain_specialization": False},
            "confidence_score": 95,
            "cloud": {"is_cloud_role": True, "primary_cloud": "AWS", "cloud_providers": ["AWS"]},
            "domain_scores": {
                "infrastructure": 6, "automation": 4, "database": 0, "cloud_database": 0, "network": 0, "platform": 0, "devops": 0, "cicd": 0, "sre": 0, "security": 0, "devsecops": 0, "system": 0, "data": 0, "mlops": 0, "aiops": 0
            },
            "dominant_domains": ["infrastructure", "automation"],
            "dominant_signals": {
                "database": [],
                "network": ["VPCs"],
                "infrastructure": ["provisioning AWS-based environments", "EC2", "S3", "compute, storage, and networking layers"],
                "platform": [],
                "automation": ["Terraform modules", "CI/CD pipelines"],
                "devops": [],
                "sre": []
            },
            "decision_trace": {"top_score": 6, "runner_up_score": 4, "tie_break_applied": False, "priority_rule_used": "", "strong_signal_override": False},
            "rationale": "The role is for a Cloud Infrastructure Engineer, requiring a minimum of 3 years of cloud experience. Key responsibilities center on building, configuring, and maintaining AWS cloud infrastructure components (compute, storage, and networking) and automating provisioning using Terraform.",
            "rationale_formatted": [
                "3+ years of cloud computing experience",
                "Responsible for provisioning AWS environments and configuring compute, network, and storage",
                "Writes and maintains Terraform configurations for automation",
                "No red flags or sponsorship restrictions detected"
            ]
        }
    }
    
    return classifications

def classify_job_with_gemini(job):
    # Read systemic prompt / policy from Job_classifier_prompt.txt
    prompt_path = str(WORKSPACE / "Job_classifier_prompt.txt")
    system_instruction = ""
    if os.path.exists(prompt_path):
        try:
            with open(prompt_path, 'r') as f:
                system_instruction = f.read()
        except Exception as e:
            print(f"Error reading Job_classifier_prompt.txt: {e}")
            
    if not system_instruction:
        print("Systemic prompt file not found! Falling back to rule-based classification.")
        return None

    # Load API key and build user prompt
    title = job.get("job_title", "Unknown Title")
    description = job.get("job_description", "")
    
    user_prompt = f"""
Analyze this job posting:
Title: {title}
Description:
{description}

Return a JSON object conforming exactly to the following structure:
{{
  "apply_decision": "APPLY" or "DO_NOT_APPLY",
  "strongest_label": "DevOps Engineer" | "Cloud Automation Engineer" | "Platform Engineering" | "Cloud Infrastructure Engineer" | "Cloud Security Engineer" | "DevSecOps" | "Site Reliability Engineer (SRE)" | "Continuous Integration (CI/CD)" | "System Engineer" | "Cloud Network Engineer" | "Data Platform Engineer" | "Machine Learning Engineer (MLOps)" | "AI Platform Engineer (AIOps)" | "OutOfScope",
  "confidence_score": 0-100,
  "red_flags": ["list of red flag categories matched, empty list if none"],
  "rationale": "detailed general explanation of classification and red flag decisions",
  "rationale_formatted": ["bullet point 1", "bullet point 2", ...],
  "domain_scores": {{
    "devops": 0-10,
    "automation": 0-10,
    "platform": 0-10,
    "infrastructure": 0-10,
    "security": 0-10,
    "devsecops": 0-10,
    "sre": 0-10,
    "cicd": 0-10,
    "system": 0-10,
    "network": 0-10,
    "database": 0-10,
    "cloud_database": 0-10,
    "data": 0-10,
    "mlops": 0-10,
    "aiops": 0-10
  }},
  "primary_cloud": "AWS" | "Azure" | "GCP" | "",
  "cloud_providers": ["AWS", "Azure", "GCP", ...]
}}
"""
    
    try:
        model = genai.GenerativeModel(
            model_name="gemini-2.5-flash",
            generation_config={"response_mime_type": "application/json"},
            system_instruction=system_instruction
        )
        response = model.generate_content(user_prompt)
        result = json.loads(response.text)
        
        # Verify result format and key constraints
        apply_decision = result.get("apply_decision", "DO_NOT_APPLY")
        strongest_label = result.get("strongest_label", "OutOfScope")
        confidence = result.get("confidence_score", 50)
        red_flags = result.get("red_flags", [])
        rationale = result.get("rationale", "")
        rationale_formatted = result.get("rationale_formatted", [])
        domain_scores = result.get("domain_scores", {})
        primary_cloud = result.get("primary_cloud", "")
        cloud_providers = result.get("cloud_providers", [])
        
        # Reconstruct full payload
        payload = {
            "all_labels": [strongest_label],
            "strongest_label": strongest_label,
            "other_labels": [],
            "apply_decision": apply_decision,
            "red_flags": red_flags,
            "filters": {"domain_specialization": False},
            "confidence_score": confidence,
            "cloud": {
                "is_cloud_role": len(cloud_providers) > 0 or primary_cloud != "",
                "primary_cloud": primary_cloud,
                "cloud_providers": cloud_providers
            },
            "domain_scores": domain_scores,
            "dominant_domains": [strongest_label],
            "dominant_signals": {},
            "decision_trace": {"top_score": max(domain_scores.values()) if domain_scores else 0},
            "rationale": rationale,
            "rationale_formatted": rationale_formatted
        }
        
        return {
            "apply_decision": apply_decision,
            "strongest_label": strongest_label,
            "confidence_score": confidence,
            "red_flags": red_flags,
            "rationale": rationale,
            "payload": payload
        }
    except Exception as e:
        print(f"Gemini API classification failed: {e}. Falling back to rule-based classification.", flush=True)
        return None

def classify_job_dynamically(job):
    title = job.get("job_title", "").lower()
    desc = job.get("job_description", "").lower()
    
    label_scores = {
        "DevOps Engineer": 0,
        "Cloud Automation Engineer": 0,
        "Platform Engineering": 0,
        "Cloud Infrastructure Engineer": 0,
        "Cloud Security Engineer": 0,
        "DevSecOps": 0,
        "Site Reliability Engineer (SRE)": 0,
        "Continuous Integration (CI/CD)": 0,
        "System Engineer": 0,
        "Cloud Network Engineer": 0,
        "Data Platform Engineer": 0,
        "Machine Learning Engineer (MLOps)": 0,
        "AI Platform Engineer (AIOps)": 0
    }
    
    # Simple keyword mapping
    if "devsecops" in title:
        label_scores["DevSecOps"] += 10
    elif "secops" in title or "security" in title:
        label_scores["Cloud Security Engineer"] += 10
        
    if "sre" in title or "reliability" in title:
        label_scores["Site Reliability Engineer (SRE)"] += 10
        
    if "platform" in title:
        if "data" in title:
            label_scores["Data Platform Engineer"] += 10
        elif "ml" in title or "machine learning" in title or "mlops" in title:
            label_scores["Machine Learning Engineer (MLOps)"] += 10
        elif "ai" in title or "aiops" in title:
            label_scores["AI Platform Engineer (AIOps)"] += 10
        else:
            label_scores["Platform Engineering"] += 10
            
    if "automation" in title:
        label_scores["Cloud Automation Engineer"] += 10
        
    if "infrastructure" in title:
        label_scores["Cloud Infrastructure Engineer"] += 10
        
    if "network" in title:
        label_scores["Cloud Network Engineer"] += 10
        
    if "ci/cd" in title or "cicd" in title or "release" in title or "integration" in title:
        label_scores["Continuous Integration (CI/CD)"] += 10
        
    if "data" in title and "engineer" in title:
        label_scores["Data Platform Engineer"] += 5
        
    if "machine learning" in title or "mlops" in title:
        label_scores["Machine Learning Engineer (MLOps)"] += 5
        
    if "devops" in title:
        label_scores["DevOps Engineer"] += 5
        
    if "system" in title or "systems" in title:
        label_scores["System Engineer"] += 5
        
    # Check description keywords (low weight)
    if "devops" in desc:
        label_scores["DevOps Engineer"] += 1
    if any(k in desc for k in ["slo", "sli", "error budget", "sre", "reliability", "observability"]):
        label_scores["Site Reliability Engineer (SRE)"] += 2
    if any(k in desc for k in ["internal platform", "developer platform", "kubernetes", "platform engineer"]):
        label_scores["Platform Engineering"] += 1
    if any(k in desc for k in ["ci/cd", "pipeline", "jenkins", "github actions", "gitlab", "circleci"]):
        label_scores["Continuous Integration (CI/CD)"] += 1
    if any(k in desc for k in ["security", "compliance", "iam", "vulnerability", "threat", "soc 2"]):
        if label_scores["DevSecOps"] > 0 or "devsecops" in desc:
            label_scores["DevSecOps"] += 2
        else:
            label_scores["Cloud Security Engineer"] += 1
    if any(k in desc for k in ["spark", "databricks", "snowflake", "data pipeline", "etl", "data warehouse"]):
        label_scores["Data Platform Engineer"] += 2
    if any(k in desc for k in ["mlops", "model deployment", "kubeflow", "mlflow"]):
        label_scores["Machine Learning Engineer (MLOps)"] += 2
    if any(k in desc for k in ["aiops", "llm infra", "gpu workload"]):
        label_scores["AI Platform Engineer (AIOps)"] += 2

    top_label = max(label_scores, key=label_scores.get)
    top_score = label_scores[top_label]
    if top_score == 0:
        top_label = "DevOps Engineer"
        
    red_flags = job.get("red_flags", [])
    apply_decision = "APPLY" if not red_flags else "DO_NOT_APPLY"
    
    confidence = 85
    rationale = f"This job was dynamically classified as {top_label} using rule-based keyword signals matching the target role profile."
    if red_flags:
        rationale += f" Red flags detected: {', '.join(red_flags)}."
        
    payload = {
        "all_labels": [top_label],
        "strongest_label": top_label,
        "other_labels": [],
        "apply_decision": apply_decision,
        "red_flags": red_flags,
        "filters": {"domain_specialization": False},
        "confidence_score": confidence,
        "cloud": {"is_cloud_role": "cloud" in desc or "aws" in desc or "azure" in desc or "gcp" in desc, "primary_cloud": "", "cloud_providers": []},
        "domain_scores": label_scores,
        "dominant_domains": [top_label],
        "dominant_signals": {},
        "decision_trace": {"top_score": top_score},
        "rationale": rationale,
        "rationale_formatted": [rationale]
    }
    
    return {
        "apply_decision": apply_decision,
        "strongest_label": top_label,
        "confidence_score": confidence,
        "red_flags": red_flags,
        "rationale": rationale,
        "payload": payload
    }

def normalize_url(url):
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        path = parsed.path.rstrip('/')
        return f"{parsed.netloc}{path}".lower()
    except Exception:
        return url.lower().strip()

def main():
    with open(str(WORKSPACE / "active_candidate_jobs.json"), "r") as f:
        jobs = json.load(f)
        
    classifications = get_job_classifications()
    approved_hashes, failed_hashes = load_known_hashes(WORKSPACE)
    
    # Build URL to static classification index mapping using candidate_jobs.json
    url_to_idx = {}
    candidate_jobs_path = str(WORKSPACE / "candidate_jobs.json")
    if os.path.exists(candidate_jobs_path):
        try:
            with open(candidate_jobs_path, "r") as f:
                cand_jobs = json.load(f)
            for idx, c_job in enumerate(cand_jobs):
                c_url = c_job.get("job_url")
                if c_url:
                    url_to_idx[normalize_url(c_url)] = idx + 1
        except Exception as e:
            print(f"Warning: Failed to load candidate_jobs.json: {e}")
            
    approved_jobs = []
    
    for job in jobs:
        url = job.get("job_url")
        norm_url = normalize_url(url)
        cls_idx = url_to_idx.get(norm_url)
        
        cls = None
        if cls_idx:
            cls = classifications.get(cls_idx)
            
        h = job.get("description_hash")
        if not cls and h:
            if h in approved_hashes:
                print(f"  Cache HIT (Approved) for '{job.get('job_title')}'. Reusing classification.", flush=True)
                matched = approved_hashes[h]
                cls = {
                    "apply_decision": matched.get("apply_decision", "APPLY"),
                    "strongest_label": matched.get("strongest_label", ""),
                    "confidence_score": matched.get("confidence_score", 100),
                    "red_flags": matched.get("red_flags", []),
                    "rationale": matched.get("rationale", ""),
                    "payload": matched.get("apply_decision_payload", {})
                }
                if "requirement_id" in matched:
                    cls["req_id_override"] = matched["requirement_id"]
                # Copy pipeline & salary fields to prevent wiping them out during runs
                for key in ["pipeline_stage", "min_salary", "max_salary", "is_hourly", "salary_text"]:
                    if key in matched:
                        job[key] = matched[key]
            elif h in failed_hashes:
                print(f"  Cache HIT (Failed) for '{job.get('job_title')}'. Reusing rejection.", flush=True)
                matched = failed_hashes[h]
                cls = {
                    "apply_decision": "DO_NOT_APPLY",
                    "strongest_label": matched.get("strongest_label", ""),
                    "confidence_score": matched.get("confidence_score", 100),
                    "red_flags": matched.get("red_flags", ["Previously rejected"]),
                    "rationale": matched.get("rationale", "Previously rejected cache hit."),
                    "payload": matched.get("apply_decision_payload", {})
                }
                # Copy pipeline & salary fields for failed cache hits too
                for key in ["pipeline_stage", "min_salary", "max_salary", "is_hourly", "salary_text"]:
                    if key in matched:
                        job[key] = matched[key]
            
        if not cls:
            # Try LLM-driven classification if API key is present
            if api_key:
                print(f"  Classifying '{job.get('job_title')}' dynamically using Gemini API...", flush=True)
                time.sleep(4)
                cls = classify_job_with_gemini(job)
                
            if not cls:
                # Fall back to dynamic rule-based classifier
                print(f"  Classifying '{job.get('job_title')}' dynamically using keyword rules...", flush=True)
                cls = classify_job_dynamically(job)
            
        job["apply_decision"] = cls["apply_decision"]
        job["strongest_label"] = cls["strongest_label"]
        job["confidence_score"] = cls["confidence_score"]
        job["red_flags"] = cls["red_flags"]
        job["rationale"] = cls["rationale"]
        job["apply_decision_payload"] = cls["payload"]
        
        # Override requirement ID if needed
        if "req_id_override" in cls:
            job["requirement_id"] = cls["req_id_override"]
            
        # Notion save gate
        if (job["apply_decision"] == "APPLY" and 
            len(job["red_flags"]) == 0 and 
            job["strongest_label"] != "OutOfScope" and
            job["job_url"] and
            job["requirement_id"] and
            job["requirement_id"] != "Unknown"):
            approved_jobs.append(job)
            
    # Write to approved_jobs.json
    output_path = str(WORKSPACE / "approved_jobs.json")
    with open(output_path, "w") as f:
        json.dump(approved_jobs, f, indent=2)
        
    print(f"Successfully classified {len(jobs)} candidates.")
    print(f"Saved {len(approved_jobs)} approved jobs to {output_path}:")
    for j in approved_jobs:
        print(f"  - [{j['company_name']}] {j['job_title']} ({j['strongest_label']}) - Req ID: {j['requirement_id']}")

if __name__ == '__main__':
    main()
