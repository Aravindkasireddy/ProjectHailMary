import re

def extract_benefits(description):
    """
    Scans the job description text and extracts matching employee benefits.
    Returns a list of matching benefit names (e.g. ['401(k)', 'Health Insurance']).
    """
    if not description:
        return []
        
    text = description.lower()
    
    # Map from output benefit name to a list of regexes or simple string patterns
    benefit_mappings = {
        "Health Insurance": [
            r"\bhealth\s+insurance\b", r"\bhealth\s+care\b", r"\bmedical\b", r"\bhealth\s+benefits\b",
            r"\bmedical\s+insurance\b", r"\bhealth\s+plans?\b"
        ],
        "Dental Insurance": [
            r"\bdental\b", r"\bdental\s+insurance\b", r"\bdental\s+benefits\b"
        ],
        "Vision Insurance": [
            r"\bvision\b", r"\bvision\s+insurance\b", r"\bvision\s+benefits\b"
        ],
        "401(k)": [
            r"\b401\(?k\)?\b", r"\b401\s*k\b", r"\bretirement\s+plans?\b", r"\bretirement\s+savings\b"
        ],
        "PTO / Vacation": [
            r"\bpto\b", r"\bpaid\s+time\s+off\b", r"\bvacation\b", r"\bpaid\s+holidays?\b", 
            r"\bannual\s+leave\b", r"\btime\s+off\b"
        ],
        "Equity / Stock Options": [
            r"\bequity\b", r"\bstock\s+options?\b", r"\brsu\b", r"\brsus\b", 
            r"\bstock\s+grants?\b", r"\bshares\b", r"\bownership\b"
        ],
        "Parental Leave": [
            r"\bparental\s+leave\b", r"\bmaternity\b", r"\bpaternity\b", 
            r"\bbaby\s+bond\b", r"\bfamily\s+leave\b"
        ],
        "Stipend / Allowance": [
            r"\bstipend\b", r"\ballowance\b", r"\bhome\s+office\s+budget\b", 
            r"\bwellness\s+budget\b", r"\binternet\s+stipend\b"
        ],
        "Tuition / Learning Budget": [
            r"\btuition\b", r"\blearning\s+budget\b", r"\beducation\s+budget\b", 
            r"\bprofessional\s+development\b"
        ]
    }
    
    extracted = []
    for benefit_name, patterns in benefit_mappings.items():
        matched = False
        for pattern in patterns:
            if re.search(pattern, text):
                matched = True
                break
        if matched:
            extracted.append(benefit_name)
            
    return extracted

if __name__ == "__main__":
    # Quick self-test
    test_desc = "We offer great medical, dental, and vision insurance! Also stock options, a 401k matching plan, and unlimited PTO."
    results = extract_benefits(test_desc)
    print("Test extraction:")
    print("Input:", test_desc)
    print("Output:", results)
