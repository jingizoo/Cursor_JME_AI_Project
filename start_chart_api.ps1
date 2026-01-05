# Start the Chart API server (PowerShell)

# Check if virtual environment is activated
if (-not $env:VIRTUAL_ENV) {
    Write-Host "Warning: Virtual environment not activated." -ForegroundColor Yellow
    Write-Host "Activating virtual environment..."
    if (Test-Path ".venv") {
        & .venv\Scripts\Activate.ps1
    } else {
        Write-Host "Error: Virtual environment not found. Please create it first." -ForegroundColor Red
        exit 1
    }
}

# Set environment variables
$env:JME_DATA_DIR = if ($env:JME_DATA_DIR) { $env:JME_DATA_DIR } else { (Resolve-Path ".\data").Path }
$env:JME_CACHE_DIR = if ($env:JME_CACHE_DIR) { $env:JME_CACHE_DIR } else { (Resolve-Path ".\.cache").Path }
$env:OLLAMA_URL = if ($env:OLLAMA_URL) { $env:OLLAMA_URL } else { "http://localhost:11434" }
$env:OLLAMA_MODEL = if ($env:OLLAMA_MODEL) { $env:OLLAMA_MODEL } else { "qwen2.5:3b" }

# Create directories if they don't exist
New-Item -ItemType Directory -Force -Path $env:JME_DATA_DIR | Out-Null
New-Item -ItemType Directory -Force -Path $env:JME_CACHE_DIR | Out-Null

Write-Host "Starting JME AI Finance Pipeline Chart API..." -ForegroundColor Green
Write-Host "  DATA_DIR: $env:JME_DATA_DIR"
Write-Host "  CACHE_DIR: $env:JME_CACHE_DIR"
Write-Host "  OLLAMA_URL: $env:OLLAMA_URL"
Write-Host "  OLLAMA_MODEL: $env:OLLAMA_MODEL"
Write-Host "  API: http://0.0.0.0:8011"
Write-Host "  Docs: http://0.0.0.0:8011/docs"
Write-Host ""

python -m uvicorn src.chart_api:app --host 0.0.0.0 --port 8011


