#!/usr/bin/env bash
set -e

# Activate venv if present
if [ -z "$VIRTUAL_ENV" ] && [ -d ".venv" ]; then
  source .venv/bin/activate
fi

# Ensure deps are installed
python -c "import matplotlib" >/dev/null 2>&1 || pip install -r requirements.txt

export JME_DATA_DIR="${JME_DATA_DIR:-./data}"
export JME_CACHE_DIR="${JME_CACHE_DIR:-./.cache}"
export OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"
export OLLAMA_MODEL="${OLLAMA_MODEL:-qwen2.5:3b}"

mkdir -p "$JME_DATA_DIR" "$JME_CACHE_DIR"

echo "Starting Web UI on http://localhost:8012"
python -m uvicorn src.webapp:app --host 0.0.0.0 --port 8012


