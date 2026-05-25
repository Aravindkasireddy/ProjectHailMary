import re

def extract_salary(description, title=""):
    """
    Parse hourly or yearly salary ranges from job description text using robust regex.
    Returns a dict with keys: min_salary (float), max_salary (float), is_hourly (bool), 
    salary_text (str), currency (str). Returns None if no salary info matches.
    """
    text = description or ""
    
    # 1. Look for hourly ranges/rates first (e.g. $45 - $65 / hour, $50/hr)
    # Match ranges: $35.00 to $50.00 / hour, $40-$60/hr
    hourly_range_regexes = [
        r'\$\s*([0-9]+(?:\.[0-9]+)?)\s*(?:-|–|to)\s*\$\s*([0-9]+(?:\.[0-9]+)?)\s*(?:\/|\s*per\s*)\s*(?:hr|hour|h|hourly)\b',
        r'\$\s*([0-9]+(?:\.[0-9]+)?)\s*(?:-|–|to)\s*([0-9]+(?:\.[0-9]+)?)\s*(?:\/|\s*per\s*)\s*(?:hr|hour|h|hourly)\b',
    ]
    for r_str in hourly_range_regexes:
        match = re.search(r_str, text, re.IGNORECASE)
        if match:
            try:
                val1 = float(match.group(1))
                val2 = float(match.group(2))
                if 10 <= val1 <= 500 and 10 <= val2 <= 500:
                    return {
                        "min_salary": val1,
                        "max_salary": val2,
                        "is_hourly": True,
                        "salary_text": f"${val1:.2f} - ${val2:.2f} / hr",
                        "currency": "USD"
                    }
            except ValueError:
                pass

    # Match single hourly rate: $45 / hour, $50 per hour, $60/hr
    hourly_single_regexes = [
        r'\$\s*([0-9]+(?:\.[0-9]+)?)\s*(?:\/|\s*per\s*)\s*(?:hr|hour|h|hourly)\b',
    ]
    for r_str in hourly_single_regexes:
        match = re.search(r_str, text, re.IGNORECASE)
        if match:
            try:
                val = float(match.group(1))
                if 10 <= val <= 500:
                    return {
                        "min_salary": val,
                        "max_salary": val,
                        "is_hourly": True,
                        "salary_text": f"${val:.2f} / hr",
                        "currency": "USD"
                    }
            except ValueError:
                pass

    # 2. Look for yearly ranges (e.g. $120,000 - $160,000, $120k to $160k)
    yearly_range_regexes = [
        # $120,000 to $160,000, $120,000 - $160,000
        r'\$\s*([0-9]{2,3}),?([0-9]{3})\s*(?:-|–|to)\s*\$\s*([0-9]{2,3}),?([0-9]{3})',
        # $120k - $160k, $120K to $160K
        r'\$\s*([0-9]{2,3})\s*[kK]\s*(?:-|–|to)\s*\$\s*([0-9]{2,3})\s*[kK]',
        # 120k - 160k (no leading $)
        r'\b([0-9]{2,3})\s*[kK]\s*(?:-|–|to)\s*([0-9]{2,3})\s*[kK]\b',
        # 120,000 - 160,000 base salary / annually
        r'\b([0-9]{2,3}),?([0-9]{3})\s*(?:-|–|to)\s*([0-9]{2,3}),?([0-9]{3})\b.*(?:base|salary|annual|annually|per year)',
    ]
    for r_str in yearly_range_regexes:
        match = re.search(r_str, text, re.IGNORECASE)
        if match:
            try:
                groups = match.groups()
                if len(groups) == 4:
                    val1 = float(groups[0]) * 1000 + float(groups[1] or 0)
                    val2 = float(groups[2]) * 1000 + float(groups[3] or 0)
                elif len(groups) == 2:
                    val1 = float(groups[0]) * 1000
                    val2 = float(groups[1]) * 1000
                else:
                    continue
                
                if 20000 <= val1 <= 1000000 and 20000 <= val2 <= 1000000:
                    return {
                        "min_salary": val1,
                        "max_salary": val2,
                        "is_hourly": False,
                        "salary_text": f"${val1:,.0f} - ${val2:,.0f}",
                        "currency": "USD"
                    }
            except ValueError:
                pass

    # 3. Look for yearly single rate (e.g. $120,000 / year, $130k base)
    yearly_single_regexes = [
        r'\$\s*([0-9]{2,3}),?([0-9]{3})\s*(?:base|salary|annually|annual|per year|/yr|/year)\b',
        r'\$\s*([0-9]{2,3})\s*[kK]\s*(?:base|salary|annually|annual|per year|/yr|/year)\b',
        r'\$\s*([0-9]{2,3}),?([0-9]{3})\b',
        r'\$\s*([0-9]{2,3})\s*[kK]\b'
    ]
    for r_str in yearly_single_regexes:
        match = re.search(r_str, text, re.IGNORECASE)
        if match:
            try:
                groups = match.groups()
                if len(groups) == 2:
                    val = float(groups[0]) * 1000 + float(groups[1] or 0)
                elif len(groups) == 1:
                    val = float(groups[0]) * 1000
                else:
                    continue
                
                if 20000 <= val <= 1000000:
                    return {
                        "min_salary": val,
                        "max_salary": val,
                        "is_hourly": False,
                        "salary_text": f"${val:,.0f}",
                        "currency": "USD"
                    }
            except ValueError:
                pass

    return None
