# Quick Start Guide

Get the JME AI Finance Pipeline up and running in minutes!

## 🚀 Installation (Choose Your Platform)

### Windows

```powershell
# Run installation script
.\install.ps1
```

### Linux / macOS

```bash
# Make executable and run
chmod +x install.sh
./install.sh
```

The installation script will:
- ✅ Check prerequisites (Python, Ollama)
- ✅ Create virtual environment
- ✅ Install all dependencies
- ✅ Set up directories
- ✅ Check/pull Ollama models
- ✅ Create startup scripts

## 📋 Prerequisites

Before running the installation:

1. **Python 3.8+** - [Download](https://www.python.org/downloads/)
2. **Ollama** - [Download](https://ollama.ai)

## 🎯 Quick Start (After Installation)

### 1. Activate Virtual Environment

**Windows:**
```powershell
.\venv\Scripts\Activate.ps1
```

**Linux/macOS:**
```bash
source venv/bin/activate
```

### 2. Start the API

**Windows:**
```powershell
.\start.ps1
```

**Linux/macOS:**
```bash
./start.sh
```

### 3. Access the API

- **API Docs:** http://localhost:8010/docs
- **Health Check:** http://localhost:8010/health

### 4. Ingest Your Data

Place Excel/PDF files in the `data/` directory, then:

```bash
curl -X POST http://localhost:8010/ingest
```

### 5. Ask Questions

```bash
curl -X POST http://localhost:8010/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "show me top 5 expenses"}'
```

Or use the webapp: http://localhost:8012

## 📚 What's Included

- **Main API** (`src/api.py`) - Port 8010
- **Chart API** (`src/chart_api.py`) - Port 8011
- **Webapp** (`src/webapp.py`) - Port 8012

## 🔧 Configuration

Create `.env` file (optional):

```env
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=qwen3:8b
JME_DATA_DIR=./data
JME_CACHE_DIR=./.cache
```

## 📖 Full Documentation

- **Installation:** `INSTALLATION.md`
- **Deployment:** `DEPLOYMENT_LINUX.md`
- **Vector DB:** `VECTOR_DB_README.md`
- **Wiki Ingestion:** `WIKI_INGESTION_README.md`
- **Webapp:** `WEBAPP_README.md`

## ❓ Troubleshooting

### Python Not Found
- Make sure Python is in your PATH
- Windows: Check during Python installation
- Linux: `sudo apt install python3`

### Ollama Not Found
- Install from https://ollama.ai
- Restart terminal after installation
- Verify: `ollama --version`

### Port Already in Use
- Change port: `PORT=8011 ./start.sh`
- Or kill process using the port

### Models Not Found
```bash
ollama pull qwen3:8b
ollama pull nomic-embed-text
```

## 🎉 You're Ready!

Once the API is running, you can:
- Upload Excel/PDF files
- Ingest wiki pages
- Ask natural language questions
- Generate charts and reports
- Integrate with Superset

Happy querying! 🚀


