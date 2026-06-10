# Python API + pipeline (Playwright WebKit). Default port 8080.
# Keep this tag in sync with playwright== in requirements.txt (browser bundles match pip version).
FROM mcr.microsoft.com/playwright/python:v1.60.0-jammy

WORKDIR /app

# OS packages sometimes needed by native wheels / TLS
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Browsers in base image match Playwright ~1.60; reinstall chromium and webkit if pip upgraded playwright
RUN python -m playwright install chromium webkit


COPY . .

ENV PYTHONUNBUFFERED=1
ENV JOBSEARCH_DASHBOARD_PORT=8080
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${JOBSEARCH_DASHBOARD_PORT}/" >/dev/null || exit 1

CMD ["python3", "dashboard_server.py"]
