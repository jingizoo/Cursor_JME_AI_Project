# Installation Guide

This guide provides step-by-step instructions for installing the JME AI Finance Pipeline on Windows and Linux/macOS.

## Quick Start

### Windows (PowerShell)

```powershell
# Run the installation script
.\install.ps1
```

### Linux/macOS (Bash)

```bash
# Make script executable and run
chmod +x install.sh
./install.sh
```

## Manual Installation

If you prefer to install manually, follow these steps:

### Prerequisites

1. **Python 3.8 or higher**
   - Download from: https://www.python.org/downloads/
   - Verify: `python --version` or `python3 --version`

2. **Ollama** (for LLM and embeddings)
   - Download from: https://ollama.ai
   - Verify: `ollama --version`

### Step-by-Step Installation

#### 1. Clone or Download the Project

```bash
# If using git
git clone <repository-url>
cd Cursor_JME_AI_Project

# Or extract the project files to a directory
```

#### 2. Create Virtual Environment

**Windows:**
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

**Linux/macOS:**
```bash
python3 -m venv venv
source venv/bin/activate
```

#### 3. Upgrade pip

```bash
pip install --upgrade pip setuptools wheel
```

#### 4. Install Dependencies

```bash
pip install -r requirements.txt
```

#### 5. Create Directories

```bash
# Windows PowerShell
New-Item -ItemType Directory -Force -Path "data", ".cache", "data\.chroma_db"

# Linux/macOS
mkdir -p data .cache data/.chroma_db
```

#### 6. Install Ollama Models

Make sure Ollama is running, then pull the required models:

```bash
# LLM model (for SQL generation)
ollama pull qwen3:8b

# Embedding model (for vector DB)
ollama pull nomic-embed-text
```

#### 7. Configure (Optional)

Create a `.env` file with your configuration:

```bash
# Windows
Copy-Item .env.example .env

# Linux/macOS
cp .env.example .env
```

Edit `.env` as needed:

```env
# Ollama Configuration
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=qwen3:8b

# Performance Optimizations
# Set to 1 to disable PDF context search (faster for Excel-only queries)
JME_DISABLE_PDF_CONTEXT=0

# Data Directories
JME_DATA_DIR=./data
JME_CACHE_DIR=./.cache

# CORS (for Superset integration)
CORS_ORIGINS=*
```

**Performance Tips:**
- For faster queries, consider using a smaller model: `OLLAMA_MODEL=qwen3:4b`
- To disable PDF context search (saves 100-500ms per query): `JME_DISABLE_PDF_CONTEXT=1`
- See `PERFORMANCE_OPTIMIZATION.md` for detailed optimization guide

## Verification

### Check Installation

1. **Verify Python packages:**
   ```bash
   pip list | grep -E "fastapi|duckdb|pandas|chromadb"
   ```

2. **Verify Ollama:**
   ```bash
   ollama list
   # Should show: qwen3:8b and nomic-embed-text
   ```

3. **Test Ollama connection:**
   ```bash
   curl http://localhost:11434/api/tags
   ```

### Start the Application

**Windows:**
```powershell
.\start.ps1
# Or manually:
.\venv\Scripts\Activate.ps1
python -m uvicorn src.api:app --host 0.0.0.0 --port 8010
```

**Linux/macOS:**
```bash
./start.sh
# Or manually:
source venv/bin/activate
python -m uvicorn src.api:app --host 0.0.0.0 --port 8010
```

### Access the API

- **API Documentation:** http://localhost:8010/docs
- **Health Check:** http://localhost:8010/health
- **Webapp:** http://localhost:8012 (if started separately)

## Troubleshooting

### Python Not Found

**Windows:**
- Make sure Python is added to PATH during installation
- Or use full path: `C:\Python39\python.exe`

**Linux/macOS:**
- Install Python: `sudo apt install python3` (Ubuntu/Debian)
- Or: `brew install python3` (macOS)

### Ollama Not Found

1. Install Ollama from https://ollama.ai
2. Add to PATH (usually automatic on Windows)
3. Restart terminal/PowerShell
4. Verify: `ollama --version`

### Ollama Not Running

```bash
# Start Ollama service
ollama serve

# Or on Windows, Ollama usually runs as a service automatically
```

### Virtual Environment Issues

**Windows:**
- If activation fails, try: `.\venv\Scripts\python.exe -m pip install -r requirements.txt`
- Execution policy: `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`

**Linux/macOS:**
- Make sure you're in the project directory
- Use `source venv/bin/activate` (not `./venv/bin/activate`)

### Port Already in Use

If port 8010 is already in use:

```bash
# Change port in .env or command line
PORT=8011 python -m uvicorn src.api:app --host 0.0.0.0 --port 8011
```

### Missing Dependencies

If you get `ModuleNotFoundError`:

```bash
# Reinstall dependencies
pip install -r requirements.txt --force-reinstall
```

### ChromaDB Issues

If vector DB doesn't work:

```bash
# Reinstall chromadb
pip install --upgrade chromadb
```

### Model Not Found

If Ollama can't find models:

```bash
# List available models
ollama list

# Pull missing models
ollama pull qwen3:8b
ollama pull nomic-embed-text

# Verify
ollama show qwen3:8b
```

## Additional Services

### Chart API

Start the chart API on a different port:

```bash
python -m uvicorn src.chart_api:app --host 0.0.0.0 --port 8011
```

### Webapp

Start the webapp:

```bash
python -m uvicorn src.webapp:app --host 0.0.0.0 --port 8012
```

## Production Deployment

For production deployment, see:
- `DEPLOYMENT_LINUX.md` - Linux deployment guide
- Use a process manager like `systemd`, `supervisor`, or `pm2`
- Set up reverse proxy (nginx, Apache)
- Configure SSL/TLS certificates
- Set up proper firewall rules

## Next Steps

1. **Place data files** in the `data/` directory (Excel, PDF files)
2. **Run ingestion:**
   ```bash
   curl -X POST http://localhost:8010/ingest
   ```
3. **Ask questions:**
   ```bash
   curl -X POST http://localhost:8010/ask \
     -H "Content-Type: application/json" \
     -d '{"question": "show me top 5 expenses"}'
   ```
4. **Access webapp:** http://localhost:8012

## Support

For more information:
- `DEPLOYMENT_LINUX.md` - Deployment details
- `VECTOR_DB_README.md` - Vector DB setup
- `WIKI_INGESTION_README.md` - Wiki ingestion
- `WEBAPP_README.md` - Webapp usage


