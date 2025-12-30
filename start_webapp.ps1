# Start the Web UI server (PowerShell)

# Activate venv if present
if (-not $env:VIRTUAL_ENV) {
    if (Test-Path ".venv") {
        & .venv\Scripts\Activate.ps1
    }
}

# Ensure deps are installed
try {
    python -c "import matplotlib" | Out-Null
} catch {
    Write-Host "matplotlib not found. Installing requirements..." -ForegroundColor Yellow
    pip install -r requirements.txt
}

$env:JME_DATA_DIR = if ($env:JME_DATA_DIR) { $env:JME_DATA_DIR } else { (Resolve-Path ".\data").Path }
$env:JME_CACHE_DIR = if ($env:JME_CACHE_DIR) { $env:JME_CACHE_DIR } else { (Resolve-Path ".\.cache").Path }
if (-not $env:OLLAMA_URL) { $env:OLLAMA_URL = "http://localhost:11434" }
if (-not $env:OLLAMA_MODEL) { $env:OLLAMA_MODEL = "qwen3:8b" }

New-Item -ItemType Directory -Force -Path $env:JME_DATA_DIR | Out-Null
New-Item -ItemType Directory -Force -Path $env:JME_CACHE_DIR | Out-Null

Write-Host "Starting Web UI on http://localhost:8012" -ForegroundColor Green
python -m uvicorn src.webapp:app --host 0.0.0.0 --port 8012


