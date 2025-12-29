$env:JME_DATA_DIR = (Resolve-Path ".\data").Path
$env:JME_CACHE_DIR = (Resolve-Path ".\.cache").Path
if (-not $env:OLLAMA_URL) { $env:OLLAMA_URL = "http://localhost:11434" }
if (-not $env:OLLAMA_MODEL) { $env:OLLAMA_MODEL = "qwen3:8b" }
python -m uvicorn src.api:app --host 127.0.0.1 --port 8010
