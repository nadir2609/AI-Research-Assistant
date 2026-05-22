# Start PostgreSQL + API with one command (Windows PowerShell).
# Usage: .\run.ps1

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Error "Docker is not installed or not on PATH. Install Docker Desktop and try again."
}

Write-Host "Starting PostgreSQL + Research Assistant API..."
Write-Host "  Health:  http://localhost:8000/health"
Write-Host "  API:     http://localhost:8000/ask"
Write-Host "  Postgres: localhost:5432  (user/password, db research_assistant)"
Write-Host ""
Write-Host "Add API keys to .env (see .env.docker.example) for live research requests."
Write-Host "Press Ctrl+C to stop."
Write-Host ""

docker compose up --build
