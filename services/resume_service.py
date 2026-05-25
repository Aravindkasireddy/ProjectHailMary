import os
import re
import openai
from prompts.ark_v5 import SYSTEM_PROMPT

def extract_jd_signals(jd: str) -> dict:
    """
    Pre-process the JD to extract platform-specific signals before sending to GPT-4o.
    Returns a dict of extracted signals used to build the override block.
    """

    # --- Named platforms and products (exact string match, case-insensitive) ---
    PLATFORM_PATTERNS = [
        "Duck Creek", "Salesforce", "SAP", "ServiceNow", "Workday", "Oracle",
        "PeopleSoft", "Guidewire", "Majesco", "Applied Epic", "Veeva", "Epic",
        "Cerner", "Snowflake", "Databricks", "dbt", "Informatica", "MuleSoft",
        "Palantir", "Tableau", "Power BI", "Looker", "Splunk", "Dynatrace",
        "Sumo Logic", "Datadog", "New Relic", "PagerDuty", "Pingdom",
        "Azure DevOps", "Octopus Deploy", "Octopus", "Harness", "Spinnaker",
        "ArgoCD", "Argo CD", "Flux", "Rancher", "OpenShift", "Terraform",
        "Pulumi", "Ansible", "Chef", "Puppet", "Vault", "Consul",
        "Apache Kafka", "Apache Spark", "Apache Airflow", "Flink",
        "Kubernetes", "Docker", "Helm", "Istio", "Prometheus", "Grafana",
        "Jenkins", "CircleCI", "GitLab CI", "GitHub Actions",
        "AWS", "Azure", "GCP", "Google Cloud"
    ]

    # --- Monitoring/observability tools ---
    MONITORING_PATTERNS = [
        "Sumo Logic", "Dynatrace", "Pingdom", "PagerDuty", "Datadog",
        "New Relic", "Splunk", "Grafana", "Prometheus", "CloudWatch",
        "AppDynamics", "Instana", "Honeycomb", "Lightstep"
    ]

    # --- CI/CD tools ---
    CICD_PATTERNS = [
        "Azure DevOps", "Jenkins", "Octopus", "Octopus Deploy", "Harness",
        "GitLab CI", "GitHub Actions", "CircleCI", "TeamCity", "Bamboo",
        "Spinnaker", "ArgoCD", "Argo CD"
    ]

    # --- Compliance/regulatory signals ---
    COMPLIANCE_PATTERNS = [
        "SOX", "Sarbanes-Oxley", "HIPAA", "PCI DSS", "PCI-DSS", "GDPR",
        "FedRAMP", "ISO 27001", "NIST", "SOC 2", "FISMA"
    ]

    # --- Responsibility phrase patterns (what the person actually DOES) ---
    RESPONSIBILITY_PATTERNS = [
        r"lead[s]?\s+\w+\s+cycle",
        r"on.call rotation",
        r"post.incident review",
        r"runbook",
        r"SOP",
        r"root cause",
        r"release cycle",
        r"deployment standard",
        r"environment management",
        r"ODW provisioning",
        r"incident response",
        r"observability",
        r"branching structure",
        r"release documentation",
        r"mentor",
        r"post.deployment check"
    ]

    jd_lower = jd.lower()

    def find_matches(patterns, text):
        found = []
        for p in patterns:
            if p.lower() in text.lower():
                found.append(p)
        return found

    def find_regex_matches(patterns, text):
        found = []
        for p in patterns:
            if re.search(p, text, re.IGNORECASE):
                found.append(p.replace(r"\s+", " ").replace(r".", " ").replace("[s]?", "s"))
        return found

    platforms = find_matches(PLATFORM_PATTERNS, jd)
    monitoring = find_matches(MONITORING_PATTERNS, jd)
    cicd = find_matches(CICD_PATTERNS, jd)
    compliance = find_matches(COMPLIANCE_PATTERNS, jd)
    responsibilities = find_regex_matches(RESPONSIBILITY_PATTERNS, jd)

    # Detect dominant cloud
    cloud_scores = {"AWS": 0, "Azure": 0, "GCP": 0}
    aws_terms = ["aws", "amazon web services", "ec2", "s3", "lambda", "cloudwatch", "cloudformation"]
    azure_terms = ["azure", "microsoft azure", "azure devops", "azure sql", "azureml"]
    gcp_terms = ["gcp", "google cloud", "bigquery", "cloud run", "gke", "vertex"]
    for t in aws_terms:
        cloud_scores["AWS"] += jd_lower.count(t)
    for t in azure_terms:
        cloud_scores["Azure"] += jd_lower.count(t)
    for t in gcp_terms:
        cloud_scores["GCP"] += jd_lower.count(t)
    dominant_cloud = max(cloud_scores, key=cloud_scores.get) if max(cloud_scores.values()) > 0 else "AWS"

    # Count how many times the primary platform appears in JD
    primary_platform = None
    primary_count = 0
    for p in platforms:
        count = jd_lower.count(p.lower())
        if count > primary_count:
            primary_count = count
            primary_platform = p

    return {
        "platforms": platforms,
        "monitoring": monitoring,
        "cicd": cicd,
        "compliance": compliance,
        "responsibilities": responsibilities,
        "dominant_cloud": dominant_cloud,
        "primary_platform": primary_platform,
        "primary_platform_count": primary_count
    }


def build_override_block(signals: dict, jd: str) -> str:
    """
    Build a CRITICAL OVERRIDE block injected at the top of the user message.
    This forces GPT-4o to anchor on JD-specific tools instead of generic training data.
    """
    lines = ["CRITICAL OVERRIDE — READ BEFORE PROCESSING THE JD:"]
    lines.append("")

    if signals["primary_platform"]:
        lines.append(
            f"PRIMARY PLATFORM: This role centers on '{signals['primary_platform']}' "
            f"(mentioned {signals['primary_platform_count']} times in JD). "
            f"The word '{signals['primary_platform']}' MUST appear in: the job title, "
            f"the professional summary, at least 3 experience bullets, and the skills section."
        )

    if signals["dominant_cloud"]:
        lines.append(
            f"DOMINANT CLOUD: {signals['dominant_cloud']}. "
            f"List {signals['dominant_cloud']} first in Cloud Platforms skill line."
        )

    if signals["cicd"]:
        lines.append(
            f"CI/CD TOOLS IN JD (use these exact strings in Skills and bullets): "
            + ", ".join(signals["cicd"])
        )

    if signals["monitoring"]:
        lines.append(
            f"MONITORING/OBSERVABILITY TOOLS IN JD (use these exact strings): "
            + ", ".join(signals["monitoring"])
        )

    if signals["compliance"]:
        lines.append(
            f"COMPLIANCE REQUIREMENTS IN JD: {', '.join(signals['compliance'])}. "
            f"Add at least 1 bullet referencing these compliance frameworks — "
            f"Truist (banking) is the most credible role for this."
        )

    if signals["responsibilities"]:
        lines.append(
            f"KEY RESPONSIBILITY PHRASES FROM JD (mirror this exact language in bullets): "
            + "; ".join(signals["responsibilities"])
        )

    lines.append("")
    lines.append(
        "ANTI-HALLUCINATION RULE: Do NOT add tools from your training data that are NOT "
        "in the JD below. Only use tools explicitly named in the JD or the candidate facts. "
        "If a Skills label has no JD match, use adjacent tools from candidate facts — "
        "never invent tools to fill a line."
    )

    lines.append("")
    lines.append("=" * 60)
    lines.append("JOB DESCRIPTION:")
    lines.append("=" * 60)

    return "\n".join(lines)


def generate_resume(jd: str) -> dict:
    """
    Generate an ATS-optimized resume for the given job description.
    Runs JD pre-processing before calling GPT-4o to prevent generic hallucination.
    """
    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        return {"error": "OPENAI_API_KEY not set in environment."}

    if len(jd.split()) < 50:
        return {"error": "JD too short — paste the full job description (50+ words)."}

    # Step 1: extract signals from JD
    signals = extract_jd_signals(jd)

    # Step 2: build override block
    override_block = build_override_block(signals, jd)

    # Step 3: compose user message — override block FIRST, then full JD
    user_message = f"{override_block}\n\n{jd}"

    # Step 4: call GPT-4o
    try:
        client = openai.OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o",
            temperature=0.2,
            max_tokens=3000,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message}
            ]
        )

        resume_text = response.choices[0].message.content.strip()
        tokens_used = response.usage.total_tokens

        # Basic sanity checks
        warnings = []
        if signals["primary_platform"] and signals["primary_platform"].lower() not in resume_text.lower():
            warnings.append(f"WARNING: '{signals['primary_platform']}' not found in output — regenerate.")
        
        long_bullets = []
        for line in resume_text.split("\n"):
            if line.strip().startswith("- "):
                word_count = len(line.strip().split())
                if word_count > 24:
                    long_bullets.append({"bullet": line.strip()[:80], "words": word_count})

        return {
            "resume": resume_text,
            "stats": {
                "words": len(resume_text.split()),
                "bullets": resume_text.count("\n- "),
                "tokens_used": tokens_used,
                "long_bullets": long_bullets,
                "warnings": warnings,
                "signals_detected": {
                    "primary_platform": signals["primary_platform"],
                    "dominant_cloud": signals["dominant_cloud"],
                    "cicd_tools": signals["cicd"],
                    "monitoring_tools": signals["monitoring"],
                    "compliance": signals["compliance"]
                }
            }
        }

    except Exception as e:
        return {"error": str(e)}
