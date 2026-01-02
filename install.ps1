# Installation script for JME AI Finance Pipeline (Windows PowerShell)
# Run: .\install.ps1

$ErrorActionPreference = "Stop"

Write-Host "🚀 JME AI Finance Pipeline - Installation Script" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

# Check Python
Write-Host "📋 Checking prerequisites..." -ForegroundColor Yellow
try {
    $pythonVersion = python --version 2>&1
    Write-Host "✓ $pythonVersion found" -ForegroundColor Green
    
    # Check Python version (3.8+)
    $versionMatch = $pythonVersion -match "Python (\d+)\.(\d+)"
    if ($versionMatch) {
        $major = [int]$matches[1]
        $minor = [int]$matches[2]
        if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 8)) {
            Write-Host "❌ Python 3.8 or higher is required. Found: Python $major.$minor" -ForegroundColor Red
            exit 1
        }
    }
} catch {
    Write-Host "❌ Python is not installed. Please install Python 3.8 or higher." -ForegroundColor Red
    Write-Host "   Download from: https://www.python.org/downloads/" -ForegroundColor Yellow
    exit 1
}

# Check Ollama
Write-Host ""
$ollamaFound = $false
try {
    $ollamaVersion = ollama --version 2>&1
    Write-Host "✓ Ollama found: $ollamaVersion" -ForegroundColor Green
    $ollamaFound = $true
} catch {
    Write-Host "⚠️  Ollama is not installed or not in PATH" -ForegroundColor Yellow
    Write-Host "   Please install Ollama from https://ollama.ai" -ForegroundColor Yellow
    Write-Host "   After installation, restart PowerShell and run this script again" -ForegroundColor Yellow
    $continue = Read-Host "   Press Enter to continue anyway (you'll need to install Ollama later)"
}

# Create virtual environment
Write-Host ""
Write-Host "📦 Creating virtual environment..." -ForegroundColor Yellow
if (Test-Path "venv") {
    Write-Host "⚠️  Virtual environment already exists. Removing old one..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force venv
}

python -m venv venv
Write-Host "✓ Virtual environment created" -ForegroundColor Green

# Activate virtual environment
Write-Host ""
Write-Host "🔧 Activating virtual environment..." -ForegroundColor Yellow
& .\venv\Scripts\Activate.ps1
Write-Host "✓ Virtual environment activated" -ForegroundColor Green

# Upgrade pip
Write-Host ""
Write-Host "⬆️  Upgrading pip..." -ForegroundColor Yellow
python -m pip install --upgrade pip setuptools wheel
Write-Host "✓ pip upgraded" -ForegroundColor Green

# Install dependencies
Write-Host ""
Write-Host "📥 Installing Python dependencies..." -ForegroundColor Yellow
if (Test-Path "requirements.txt") {
    pip install -r requirements.txt
    Write-Host "✓ Dependencies installed" -ForegroundColor Green
} else {
    Write-Host "❌ requirements.txt not found" -ForegroundColor Red
    exit 1
}

# Create necessary directories
Write-Host ""
Write-Host "📁 Creating directories..." -ForegroundColor Yellow
New-Item -ItemType Directory -Force -Path "data" | Out-Null
New-Item -ItemType Directory -Force -Path ".cache" | Out-Null
New-Item -ItemType Directory -Force -Path "data\.chroma_db" | Out-Null
Write-Host "✓ Directories created" -ForegroundColor Green

# Check Ollama models
Write-Host ""
Write-Host "🤖 Checking Ollama models..." -ForegroundColor Yellow

if ($ollamaFound) {
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        Write-Host "✓ Ollama is running" -ForegroundColor Green
        
        # Check for LLM model
        $llmModel = if ($env:OLLAMA_MODEL) { $env:OLLAMA_MODEL } else { "qwen3:8b" }
        Write-Host "   Checking for LLM model: $llmModel" -ForegroundColor Gray
        $models = ollama list
        if ($models -match $llmModel) {
            Write-Host "✓ LLM model '$llmModel' found" -ForegroundColor Green
        } else {
            Write-Host "⚠️  LLM model '$llmModel' not found" -ForegroundColor Yellow
            $pull = Read-Host "   Would you like to pull it now? (y/n)"
            if ($pull -eq "y" -or $pull -eq "Y") {
                ollama pull $llmModel
                Write-Host "✓ LLM model pulled" -ForegroundColor Green
            }
        }
        
        # Check for embedding model
        $embeddingModel = "nomic-embed-text"
        Write-Host "   Checking for embedding model: $embeddingModel" -ForegroundColor Gray
        if ($models -match $embeddingModel) {
            Write-Host "✓ Embedding model '$embeddingModel' found" -ForegroundColor Green
        } else {
            Write-Host "⚠️  Embedding model '$embeddingModel' not found" -ForegroundColor Yellow
            $pull = Read-Host "   Would you like to pull it now? (y/n)"
            if ($pull -eq "y" -or $pull -eq "Y") {
                ollama pull $embeddingModel
                Write-Host "✓ Embedding model pulled" -ForegroundColor Green
            }
        }
    } catch {
        Write-Host "⚠️  Ollama is not running" -ForegroundColor Yellow
        Write-Host "   Please start Ollama or run:" -ForegroundColor Yellow
        Write-Host "   ollama pull qwen3:8b" -ForegroundColor Yellow
        Write-Host "   ollama pull nomic-embed-text" -ForegroundColor Yellow
    }
} else {
    Write-Host "⚠️  Ollama not found in PATH" -ForegroundColor Yellow
    Write-Host "   Please install Ollama and pull required models:" -ForegroundColor Yellow
    Write-Host "   - ollama pull qwen3:8b" -ForegroundColor Yellow
    Write-Host "   - ollama pull nomic-embed-text" -ForegroundColor Yellow
}

# Create .env.example if it doesn't exist
Write-Host ""
Write-Host "📝 Setting up configuration..." -ForegroundColor Yellow
if (-not (Test-Path ".env.example")) {
    @"
# Ollama Configuration
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=qwen3:8b

# Data Directories
JME_DATA_DIR=./data
JME_CACHE_DIR=./.cache

# CORS (for Superset integration)
CORS_ORIGINS=*
"@ | Out-File -FilePath ".env.example" -Encoding utf8
    Write-Host "✓ Created .env.example" -ForegroundColor Green
}

# Create startup script
Write-Host ""
Write-Host "📝 Creating startup scripts..." -ForegroundColor Yellow

# Windows startup script
@"
# Start the JME AI Finance Pipeline API (Windows PowerShell)

# Activate virtual environment
if (Test-Path "venv\Scripts\Activate.ps1") {
    & .\venv\Scripts\Activate.ps1
} else {
    Write-Host "❌ Virtual environment not found. Please run install.ps1 first." -ForegroundColor Red
    exit 1
}

# Check if Ollama is running
try {
    Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop | Out-Null
} catch {
    Write-Host "⚠️  Warning: Ollama doesn't seem to be running." -ForegroundColor Yellow
    Write-Host "   Please start Ollama or run: ollama serve" -ForegroundColor Yellow
    Write-Host ""
}

# Load environment variables if .env exists
if (Test-Path ".env") {
    Get-Content ".env" | ForEach-Object {
        if ($_ -match '^\s*([^#][^=]+)=(.*)$') {
            $name = $matches[1].Trim()
            $value = $matches[2].Trim()
            [Environment]::SetEnvironmentVariable($name, $value, "Process")
        }
    }
}

# Default values
$OLLAMA_URL = if ($env:OLLAMA_URL) { $env:OLLAMA_URL } else { "http://localhost:11434" }
$OLLAMA_MODEL = if ($env:OLLAMA_MODEL) { $env:OLLAMA_MODEL } else { "qwen3:8b" }
$PORT = if ($env:PORT) { $env:PORT } else { "8010" }

Write-Host "🚀 Starting JME AI Finance Pipeline API..." -ForegroundColor Cyan
Write-Host "   Ollama URL: $OLLAMA_URL" -ForegroundColor Gray
Write-Host "   Ollama Model: $OLLAMA_MODEL" -ForegroundColor Gray
Write-Host "   Port: $PORT" -ForegroundColor Gray
Write-Host ""

python -m uvicorn src.api:app --host 0.0.0.0 --port $PORT
"@ | Out-File -FilePath "start.ps1" -Encoding utf8

Write-Host "✓ Created start.ps1" -ForegroundColor Green

# Summary
Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "✅ Installation Complete!" -ForegroundColor Green
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:"
Write-Host ""
Write-Host "1. Activate the virtual environment:" -ForegroundColor Yellow
Write-Host "   .\venv\Scripts\Activate.ps1" -ForegroundColor White
Write-Host ""
Write-Host "2. (Optional) Create .env file with your configuration:" -ForegroundColor Yellow
Write-Host "   Copy-Item .env.example .env" -ForegroundColor White
Write-Host "   # Edit .env as needed" -ForegroundColor White
Write-Host ""
Write-Host "3. Make sure Ollama is running:" -ForegroundColor Yellow
Write-Host "   # Ollama should start automatically, or run: ollama serve" -ForegroundColor White
Write-Host ""
Write-Host "4. Pull required models (if not done during installation):" -ForegroundColor Yellow
Write-Host "   ollama pull qwen3:8b" -ForegroundColor White
Write-Host "   ollama pull nomic-embed-text" -ForegroundColor White
Write-Host ""
Write-Host "5. Place your Excel/PDF files in the data\ directory" -ForegroundColor Yellow
Write-Host ""
Write-Host "6. Start the API:" -ForegroundColor Yellow
Write-Host "   .\start.ps1" -ForegroundColor White
Write-Host "   # Or: python -m uvicorn src.api:app --host 0.0.0.0 --port 8010" -ForegroundColor White
Write-Host ""
Write-Host "7. Access the API:" -ForegroundColor Yellow
Write-Host "   http://localhost:8010/docs" -ForegroundColor White
Write-Host ""
Write-Host "For more information, see:" -ForegroundColor Yellow
Write-Host "  - DEPLOYMENT_LINUX.md" -ForegroundColor White
Write-Host "  - VECTOR_DB_README.md" -ForegroundColor White
Write-Host "  - WIKI_INGESTION_README.md" -ForegroundColor White
Write-Host ""


