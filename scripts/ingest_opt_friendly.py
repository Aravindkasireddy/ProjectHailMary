import os
import sys
import pandas as pd
from pathlib import Path

# Add root folder to sys.path so we can import supabase_client
sys.path.append(str(Path(__file__).resolve().parent.parent))
from supabase_client import get_supabase_client

EXCEL_PATH = Path(__file__).resolve().parent.parent / "Opt_freindly" / "Gopall-OPT-Friendly-2 copy.xlsx"

def run_ingestion():
    print("Initializing Supabase Client...")
    try:
        supabase = get_supabase_client()
    except Exception as e:
        print(f"Failed to initialize Supabase client: {e}")
        sys.exit(1)

    print(f"Reading Excel file: {EXCEL_PATH}...")
    try:
        df = pd.read_excel(EXCEL_PATH)
    except Exception as e:
        print(f"Failed to read Excel file: {e}")
        sys.exit(1)
        
    print(f"Found {len(df)} companies in the dataset.")
    
    # Filter out empty or invalid names
    df = df.dropna(subset=['Employer Name'])
    
    records = []
    seen = set()
    for _, row in df.iterrows():
        company_name = str(row['Employer Name']).strip()
        
        if company_name and company_name not in seen:
            seen.add(company_name)
            
            # Safe value extractor and converter
            def clean_val(val, val_type=str):
                if pd.isna(val):
                    return None
                try:
                    if val_type == int:
                        return int(float(val))
                    if val_type == float:
                        return float(val)
                    return str(val).strip()
                except Exception:
                    return None
            
            records.append({
                "company_name": company_name,
                "is_sponsor": True,
                "company_type": clean_val(row.get('company_type')),
                "w2_contractor": clean_val(row.get('w2_contractor')),
                "employee_count": clean_val(row.get('employee_count'), float),
                "linkedin_account": clean_val(row.get('linkedin_account')),
                "career_portal": clean_val(row.get('career_portal')),
                "website": clean_val(row.get('website')),
                "sponsor_status": clean_val(row.get('Sponsor Status')),
                "recommended_action": clean_val(row.get('Recommended Action')),
                "opt_friendly_score": clean_val(row.get('OPT-Friendly Hiring Score (0-100)'), float),
                "cases_2024": clean_val(row.get('Cases 2024'), int),
                "cases_2025": clean_val(row.get('Cases 2025'), int),
                "cases_2026": clean_val(row.get('Cases 2026'), int),
                "recent_cases": clean_val(row.get('Recent Cases (2024-2026)'), int),
                "recent_approvals": clean_val(row.get('Recent New Employment Approvals (2024-2026)'), int),
                "trend_label": clean_val(row.get('Trend Label')),
                "top_state": clean_val(row.get('Top State'))
            })

    print(f"Upserting {len(records)} unique OPT-friendly sponsors with rich metadata...")
    
    # Upsert in batches of 1000
    batch_size = 1000
    success_count = 0
    for i in range(0, len(records), batch_size):
        batch = records[i:i+batch_size]
        try:
            supabase.table("h1b_sponsors").upsert(batch, on_conflict="company_name").execute()
            success_count += len(batch)
            print(f"Uploaded batch {i//batch_size + 1}: {len(batch)} records")
        except Exception as e:
            print(f"Failed to ingest batch {i//batch_size + 1}: {e}")

    print(f"Successfully ingested {success_count} OPT-friendly sponsors with metadata into Supabase.")

if __name__ == "__main__":
    run_ingestion()
