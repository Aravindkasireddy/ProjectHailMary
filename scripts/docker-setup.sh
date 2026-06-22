#!/usr/bin/env bash
# First-time Docker prep: ensure .env exists, then build images.
# Run from repo root: ./scripts/docker-setup.sh   OR   make docker-setup
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  if [[ -f .env.example ]]; then
    cp .env.example .env
    echo "[docker-setup] Created .env from .env.example"
    echo "[docker-setup] Edit .env and set at least SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY (and any Gemini keys you use)."
  else
    echo "[docker-setup] ERROR: .env missing and no .env.example found." >&2
    exit 1
  fi
else
  echo "[docker-setup] .env already present — not overwriting."
fi

if ! docker info >/dev/null 2>&1; then
  echo "[docker-setup] ERROR: Cannot reach the Docker daemon (docker.sock missing or engine not running)." >&2
  echo "         macOS: Open Docker Desktop from Applications and wait until the whale icon shows 'Docker is running'." >&2
  echo "         Then run: make docker-setup   (or: docker compose build)" >&2
  echo "         If you use Colima or OrbStack, start that backend instead of Docker Desktop." >&2
  exit 1
fi

echo "[docker-setup] Building images (this may take a few minutes)..."
docker compose build

echo "[docker-setup] Done. Start the stack with:"
echo "    docker compose up"
echo "  or:"
echo "    make docker-up"
