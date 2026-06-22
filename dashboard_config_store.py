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
    """Splice the policy-driven Work authorization sub-block into Job_classifier_prompt.txt.

    As of the 2026-06 MAAS prompt rewrite, experience/seniority/scope caps are
    fixed MAAS-standard text (no longer driven by max_experience_years/salary
    config), and salary is explicitly a non-blocker. Only visa/clearance
    enforcement toggles and custom red-flag keywords are still config-driven —
    this function only rewrites that one sub-block, leaving the rest of the
    (much larger) RED FLAG RULES section untouched.
    """
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

        enforce_visa = bool(config.get("enforce_visa_sponsorship", True))
        enforce_clearance = bool(config.get("enforce_no_clearance", True))
        custom_red_flags = config.get("custom_red_flag_keywords", [])

        visa_rules = ""
        if enforce_visa:
            visa_rules = """
- no visa sponsorship / not eligible for sponsorship / unable to sponsor visas / does not sponsor work authorization
- cannot sponsor H1B / cannot provide visa sponsorship now or in the future
- not eligible for immigration sponsorship / this role is not eligible for sponsorship
- must be authorized to work in the US without sponsorship / must have permanent work authorization
- no future sponsorship available / without sponsorship now or in the future / work authorization required without sponsorship / no current or future sponsorship"""
        clearance_rules = ""
        if enforce_clearance:
            clearance_rules = """
- active security clearance / government clearance / secret clearance / top secret clearance / TS/SCI
- ITAR / International Traffic in Arms Regulations / export control / export-controlled / U.S. export regulations"""
        custom_rules_str = ""
        if custom_red_flags:
            custom_rules_str = "\n" + "\n".join([f"- {kw}" for kw in custom_red_flags if kw.strip()])

        new_work_auth_block = f"""### Work authorization restriction
- US citizenship only / must be US citizen / US citizens only{clearance_rules}
- must be U.S. person / U.S. persons only / as defined by 8 U.S.C. 1324b(a)(3){visa_rules}{custom_rules_str}
- If any of these appear: add red_flag: \"Work authorization restriction\""""

        start_marker = "### Work authorization restriction"
        end_marker = "### Experience requirement violation"
        start_idx = content.find(start_marker)
        end_idx = content.find(end_marker)
        if start_idx == -1 or end_idx == -1:
            return False, "Could not find work-authorization rule boundaries in prompt file"
        new_content = content[:start_idx] + new_work_auth_block + "\n\n" + content[end_idx:]
        with open(prompt_path, 'w') as f:
            f.write(new_content)
        return True, "Classifier prompt rebuilt successfully!"
    except Exception as e:
        return False, f"Rebuild failed: {str(e)}"


