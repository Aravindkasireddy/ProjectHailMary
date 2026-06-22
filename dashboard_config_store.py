"""Config/policy persistence helpers.

Extracted verbatim from dashboard_server.py. These functions depend on
module-level paths/constants (CONFIG_PATH, POLICY_CONFIG_PATH,
WORKSPACE_DIR) and the resolve_path() helper, which still live in
dashboard_server.py as the single source of truth. They are imported lazily
inside each function to avoid a circular import at module load time.
"""
import os
import json


def load_config(email=None):
    import dashboard_server as ds
    import jobsearch_constants as jc

    path = ds.resolve_path(ds.CONFIG_PATH, email)
    if os.path.exists(path):
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading config file {path}: {e}")
    # Default config
    return {
        "target_titles": list(jc.DEFAULT_TARGET_TITLES),
        "scheduler": {
            "enabled": True,
            "run_at_hour": 8,
            "run_at_minute": 0
        },
        "webhook_url": "",
        "search": {
            "country_phrase": "United States",
            "include_remote_primary_boards": True,
            "merge_previous_scrape": True,
            "send_digest_only": True,
            "max_digest_items": 10,
        },
    }


def save_config(cfg, email=None):
    import dashboard_server as ds

    try:
        cfg = dict(cfg)
        if os.environ.get("JOBSEARCH_WEBHOOK_URL", "").strip():
            cfg.pop("webhook_url", None)
        path = ds.resolve_path(ds.CONFIG_PATH, email)
        with open(path, 'w') as f:
            json.dump(cfg, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving config file: {e}")
        return False


def load_policy_config(email=None):
    import dashboard_server as ds

    path = ds.resolve_path(ds.POLICY_CONFIG_PATH, email)
    if os.path.exists(path):
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading policy config {path}: {e}")
    return {
        "max_experience_years": 8,
        "min_salary_annual": 80000,
        "min_salary_hourly": 50,
        "enforce_visa_sponsorship": True,
        "enforce_no_clearance": True,
        "custom_red_flag_keywords": []
    }


def save_policy_config(cfg, email=None):
    import dashboard_server as ds

    try:
        path = ds.resolve_path(ds.POLICY_CONFIG_PATH, email)
        with open(path, 'w') as f:
            json.dump(cfg, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving policy config: {e}")
        return False


def rebuild_classifier_prompt(config):
    import dashboard_server as ds

    prompt_path = os.path.join(ds.WORKSPACE_DIR, "Job_classifier_prompt.txt")
    if not os.path.exists(prompt_path):
        return False, "Job_classifier_prompt.txt not found"
    try:
        backup_path = prompt_path + ".bak"
        with open(prompt_path, 'r') as f:
            content = f.read()
        with open(backup_path, 'w') as f:
            f.write(content)
        max_exp = int(config.get("max_experience_years", 8))
        min_sal = int(config.get("min_salary_annual", 80000))
        min_sal_hr = int(config.get("min_salary_hourly", 50))
        enforce_visa = bool(config.get("enforce_visa_sponsorship", True))
        enforce_clearance = bool(config.get("enforce_no_clearance", True))
        custom_red_flags = config.get("custom_red_flag_keywords", [])

        visa_rules = ""
        if enforce_visa:
            visa_rules = """- no visa sponsorship / not eligible for sponsorship / unable to sponsor visas / does not sponsor work authorization
- cannot sponsor H1B / cannot provide visa sponsorship now or in the future
- not eligible for immigration sponsorship / this role is not eligible for sponsorship
- must be authorized to work in the US without sponsorship / must have permanent work authorization
- no future sponsorship available / without sponsorship now or in the future / work authorization required without sponsorship / no current or future sponsorship"""
        clearance_rules = ""
        if enforce_clearance:
            clearance_rules = """- active security clearance / government clearance / secret clearance / top secret clearance / TS/SCI
- ITAR / International Traffic in Arms Regulations / export control / export-controlled / U.S. export regulations"""
        custom_rules_str = ""
        if custom_red_flags:
            custom_rules_str = "\n".join([f"- {kw}" for kw in custom_red_flags if kw.strip()])
        min_sal_k = f"{min_sal // 1000}k" if min_sal >= 1000 else str(min_sal)

        allowed_max_non_sre = max_exp - 2 if max_exp > 2 else 1
        allowed_max_sre = max_exp - 1 if max_exp > 1 else 1
        allowed_non_sre_ranges = " / ".join([f"{i} / {i}+" for i in range(3, allowed_max_non_sre + 1)])
        allowed_sre_ranges = " / ".join([f"{i} / {i}+" for i in range(5, allowed_max_sre + 1)]) if allowed_max_sre >= 5 else "5 / 5+"

        new_red_flags_block = f"""## RED FLAG RULES

Hard rule: if any item below is present, you MUST add the matching red flag and MUST set `apply_decision = DO_NOT_APPLY`.

### Work authorization restriction
- US citizenship only / must be US citizen / US citizens only
{visa_rules}
{clearance_rules}
- must be U.S. person / U.S. persons only / as defined by 8 U.S.C. 1324b(a)(3)
{custom_rules_str}
- If any of these appear: add red_flag: "Work authorization restriction"

### Experience requirement violation
- any requirement ≥{max_exp} years
- ranges where upper bound ≥{max_exp}
- no experience mentioned
- treat written numbers the same as digits: three, four, five, six, seven, eight, nine, ten
- treat plus phrasing the same as numeric plus: 3+, 4+, 5+, 6+, 7+, three plus, five plus, seven plus
Allowed experience ranges (non-SRE): {allowed_non_sre_ranges or "3 / 3+"}
ranges where maximum ≤{allowed_max_non_sre}
Allowed experience ranges (SRE): {allowed_sre_ranges}
ranges where maximum ≤{allowed_max_sre}
- If above the allowed cap: add red_flag: "Experience requirement violation"

### Seniority / title violation
- Manager / Director / Principal / Architect / Lead
- Senior and Staff are allowed only when total experience requirement is ≤{max_exp - 1} years
- If experience >{max_exp - 1} years: treat it as R3
- If the title itself violates this rule: add red_flag: "Seniority / title violation"

### Out of scope
- Pure QA
- Pure development
- EDI
- Desktop support
- Data science
- If present: add red_flag: "Out of scope"

### Salary rule
- Salaried full-time: minimum salary < ${min_sal_k} → DO_NOT_APPLY
- Hourly: ≤ ${min_sal_hr}/hr → DO_NOT_APPLY
- If salary is not listed, do not trigger

If red_flags is non-empty:
MUST set apply_decision = DO_NOT_APPLY

--------------------------------------------------
APPLICATION DECISION
--------------------------------------------------

If red_flags is non-empty:
MUST set apply_decision = DO_NOT_APPLY

Return APPLY when the role belongs to the engineering domains above.

Return DO_NOT_APPLY when the role belongs to:

sales
marketing
finance
HR
business operations
pure project management
pure scrum master / delivery coordination without hands-on engineering scope

--------------------------------------------------
---
"""
        start_marker = "## RED FLAG RULES"
        end_marker = "## DATABASE ENGINEER RULE"
        start_idx = content.find(start_marker)
        end_idx = content.find(end_marker)
        if start_idx == -1 or end_idx == -1:
            return False, "Could not find red flag rule boundaries in prompt file"
        new_content = content[:start_idx] + new_red_flags_block + content[end_idx:]
        with open(prompt_path, 'w') as f:
            f.write(new_content)
        return True, "Classifier prompt rebuilt successfully!"
    except Exception as e:
        return False, f"Rebuild failed: {str(e)}"


