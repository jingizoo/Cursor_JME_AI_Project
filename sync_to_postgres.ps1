# Sync DuckDB -> Postgres (PowerShell)

if (-not $env:VIRTUAL_ENV) {
    if (Test-Path ".venv") {
        & .venv\Scripts\Activate.ps1
    }
}

if (-not $env:JME_PG_URL) {
    Write-Host "JME_PG_URL is required, e.g.:" -ForegroundColor Yellow
    Write-Host '  $env:JME_PG_URL = "postgresql+psycopg2://user:pass@localhost:5432/dbname"' -ForegroundColor Yellow
    exit 1
}

python sync_to_postgres.py


