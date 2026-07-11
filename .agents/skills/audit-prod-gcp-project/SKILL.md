---
name: audit-prod-gcp-project
description: Use this skill whenever the user asks to "check the health of the production project", "audit the GCP project", or "get a status report on project-3ed0b7ac-aa3e-4949-b77".
---

# Production GCP Project Audit 

This skill provides a comprehensive status report on the production GCP project (`project-3ed0b7ac-aa3e-4949-b77`).

When triggered, you MUST sequentially run the following `gcloud` commands to gather a full snapshot of the project's health, resources, and billing. Do not stop until all data is gathered. Formulate the final output into a clean, easy-to-read Markdown report for the user.

### 1. Initialize & Authentication
Ensure you are operating on the correct project.
```bash
gcloud config set project project-3ed0b7ac-aa3e-4949-b77
```

### 2. Cloud Billing
Check the active billing account associated with this project.
```bash
gcloud beta billing projects describe project-3ed0b7ac-aa3e-4949-b77
```

### 3. Active Services
List all currently enabled Google Cloud APIs and services to see the project's footprint.
```bash
gcloud services list --enabled
```

### 4. Compute Resources
List all virtual machines to verify the `jobsearch-dashboard` (and any other instances) are healthy.
```bash
gcloud compute instances list
```

### 5. Storage
List all Cloud Storage buckets to check for data persistence layers, backups, or static assets.
```bash
gcloud storage ls
```

### 6. Monitoring and Observability
Check for any configured uptime checks or logging metrics to ensure the project is being monitored.
```bash
# Check Uptime Checks (Monitoring)
gcloud monitoring uptime list

# Check Custom Logging Metrics
gcloud logging metrics list
```

### 7. Final Report
After executing the above commands, compile the results into an artifact (e.g., `gcp_audit_report.md`) or a detailed chat response. The report MUST include sections for:
* **Billing Status:** Is billing enabled and linked?
* **Enabled APIs:** Summary of the core APIs running.
* **Compute Infrastructure:** Name, Zone, IP, and Status of all VMs.
* **Storage Assets:** List of buckets.
* **Observability:** Are uptime checks or custom logging metrics active?
