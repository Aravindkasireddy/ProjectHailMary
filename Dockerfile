# Python API + pipeline (Playwright WebKit). Default port 8080.
# Keep this tag in sync with playwright== in requirements.txt (browser bundles match pip version).
FROM mcr.microsoft.com/playwright/python:v1.60.0-jammy

WORKDIR /app

# Shared browser cache for root (install) and non-root (runtime). The official
# image usually sets this already; pin it explicitly so a USER switch never
# leaves browsers only under /root/.cache/ms-playwright/.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# OS packages sometimes needed by native wheels / TLS
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# Deps are version-pinned in requirements.txt (satisfies Hadolint DL3013 intent).
RUN --mount=type=tmpfs,target=/root/.cache \
    pip install --no-cache-dir -r requirements.txt

RUN addgroup --system appuser && adduser --system --ingroup appuser appuser \
    && mkdir -p "${PLAYWRIGHT_BROWSERS_PATH}" \
    && chown -R appuser:appuser "${PLAYWRIGHT_BROWSERS_PATH}"

# Reinstall chromium/webkit if pip upgraded playwright past the base image.
# Keep ownership on appuser so runtime launches resolve the same path.
RUN python -m playwright install chromium webkit \
    && chown -R appuser:appuser "${PLAYWRIGHT_BROWSERS_PATH}"

COPY --chown=appuser:appuser . .

# Ensure writable runtime dirs exist with correct ownership before switching user.
# The bind-mount (volumes: .:/app) may overlay these, but if logs/ doesn't exist
# on the host yet Docker will create it as root — this mkdir makes the host dir
# get created by the entrypoint as appuser instead.
RUN mkdir -p /app/logs /app/data && chown -R appuser:appuser /app/logs /app/data

USER appuser
ENV PYTHONUNBUFFERED=1
ENV JOBSEARCH_DASHBOARD_PORT=8080
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${JOBSEARCH_DASHBOARD_PORT}/" >/dev/null || exit 1

CMD ["python3", "dashboard_server.py"]
