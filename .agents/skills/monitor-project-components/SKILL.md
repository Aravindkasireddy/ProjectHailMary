---
name: monitor-project-components
description: Use this skill whenever the user asks to check the status of the application, monitor project components, see if the site is up, or check docker health.
---

# Project Component Monitoring

This skill actively monitors the live application components, ensuring that the web server, API, and underlying Docker containers are healthy and responding.

When triggered, follow these steps to gather real-time health metrics:

### 1. Public Endpoint Health
Check if the external API and website are actively responding to traffic.
```bash
# Check the API Health Endpoint
curl -s -I https://jobs.arkfarms.store/api/health

# Check the Main Web Dashboard
curl -s -I https://jobs.arkfarms.store/
```

### 2. Internal Container Health & Resources
SSH into the production VM to verify the Docker containers and server resources.
```bash
gcloud compute ssh jobsearch-dashboard \
  --zone=us-south1-b \
  --project=project-3ed0b7ac-aa3e-4949-b77 \
  --command="echo '=== Docker Status ===' && sudo docker ps -a && echo '\n=== Memory Usage ===' && free -h && echo '\n=== Disk Usage ===' && df -h /"
```

### 3. Report Generation
After running the commands, summarize the findings for the user:
*   **Public Access:** Are the URLs returning `200 OK`?
*   **Containers:** Are `projecthailmary-web-1` and `projecthailmary-api-1` marked as `Up` and `healthy`?
*   **Server Resources:** Is the disk space getting too high (e.g., >85%), or is memory running low?

*Note: If the containers are down or disk space is critical, proactively recommend running `sudo docker system prune -af` or `docker compose up -d` to recover.*
