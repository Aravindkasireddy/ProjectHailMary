import os
import sys
from pathlib import Path

# Add root folder to sys.path so we can import supabase_client
sys.path.append(str(Path(__file__).resolve().parent.parent))
from supabase_client import get_supabase_client

# Top 50 Tech Companies known for H1B sponsorship (for demonstration/seed)
# In production, replace this with a CSV parser from USCIS Data Hub
KNOWN_SPONSORS = [
    "Google", "Meta", "Facebook", "Amazon", "Apple", "Microsoft", 
    "Netflix", "Tesla", "Uber", "Lyft", "Airbnb", "Salesforce",
    "Adobe", "Oracle", "IBM", "Intel", "Cisco", "Nvidia", "AMD",
    "LinkedIn", "Twitter", "X", "Snap", "Pinterest", "Stripe",
    "Square", "Block", "PayPal", "Intuit", "Atlassian", "Databricks",
    "Snowflake", "Palantir", "Splunk", "Twilio", "Okta", "Zoom",
    "Dropbox", "Box", "DocuSign", "ServiceNow", "Workday", "Shopify",
    "Coinbase", "Robinhood", "Instacart", "DoorDash", "Roku", "Wayfair",
    "Zillow", "Spotify", "Epic Games", "Roblox", "Electronic Arts"
]

def run_ingestion():
    print("Initializing Supabase Client...")
    try:
        supabase = get_supabase_client()
    except Exception as e:
        print(f"Failed to initialize Supabase client: {e}")
        sys.exit(1)

    print(f"Ingesting {len(KNOWN_SPONSORS)} known H1B sponsors...")
    
    records = []
    for sponsor in KNOWN_SPONSORS:
        records.append({
            "company_name": sponsor,
            "is_sponsor": True
        })

    try:
        # Upsert records into h1b_sponsors table
        supabase.table("h1b_sponsors").upsert(records, on_conflict="company_name").execute()
        print("Successfully ingested H1B sponsors into Supabase.")
    except Exception as e:
        print(f"Failed to ingest data: {e}")

if __name__ == "__main__":
    run_ingestion()
