---
name: deploy-to-prod
description: Use this skill whenever the user asks to deploy the application to production, push to prod, or run the production deployment.
---

# Production Deployment Process

This project relies on GitHub Actions for automatic production deployment to the GCP VM at **https://jobs.arkfarms.store**. 

When instructed to deploy to production, you MUST follow these steps:

1. **Verify Local Checks:** First, ensure all code is committed. Run `make ci` locally to ensure strict linting and tests pass.
2. **Push to Main:** Push the latest changes to the `main` branch on GitHub.
3. **Monitor CI/CD:** Explain to the user that the push triggers `.github/workflows/ci.yml`.
4. **GitHub Approval Gate:** Remind the user that there is a **Manual approval gate** in GitHub. They must go to the Actions UI → run → "Review pending deployments" → Approve and deploy.
5. **Post-Deploy Verification:** Once the user confirms the deployment is approved and finished, run `curl -sf https://jobs.arkfarms.store/api/health` to verify the production API is up and responding.

*Note: If the user explicitly asks for a manual SSH deployment bypassing GitHub Actions, warn them first. If they confirm, SSH into the production VM and run `git reset --hard origin/main`, `docker compose up --build -d`, and check the health endpoint locally on the VM.*
