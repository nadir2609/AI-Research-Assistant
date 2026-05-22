#!/usr/bin/env sh
# Start PostgreSQL + API with one command (macOS / Linux).
# Usage: ./run.sh

set -e
cd "$(dirname "$0")"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed or not on PATH." >&2
  exit 1
fi

echo "Starting PostgreSQL + Research Assistant API..."
echo "  Health:  http://localhost:8000/health"
echo "  API:     http://localhost:8000/ask"
echo "  Postgres: localhost:5432  (user/password, db research_assistant)"
echo ""
echo "Add API keys to .env (see .env.docker.example) for live research requests."
echo "Press Ctrl+C to stop."
echo ""

docker compose up --build
