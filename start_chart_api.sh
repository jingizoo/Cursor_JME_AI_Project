#!/usr/bin/env bash
# Start the Chart API server

set -e

# Check if virtual environment is activated
if [ -z "$VIRTUAL_ENV" ]; then
    echo "Warning: Virtual environment not activated."
    echo "Activating virtual environment..."
    if [ -d ".venv" ]; then
        source .venv/bin/activate
    else
        echo "Error: Virtual environment not found. Please run ./deploy.sh first or create it manually."
        exit 1
    fi
fi

# Set environment variables
export JME_DATA_DIR="${JME_DATA_DIR:-./data}"
export JME_CACHE_DIR="${JME_CACHE_DIR:-./.cache}"
export OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"
export OLLAMA_MODEL="${OLLAMA_MODEL:-qwen2.5:3b}"

# Create directories if they don't exist
mkdir -p "$JME_DATA_DIR"
mkdir -p "$JME_CACHE_DIR"

# Check if Ollama is accessible (non-blocking)
if ! curl -s --max-time 2 "$OLLAMA_URL/api/tags" > /dev/null 2>&1; then
    echo "Warning: Cannot connect to Ollama at $OLLAMA_URL"
    echo "Make sure Ollama is running. The API will start but may fail when using LLM features."
fi

echo "Starting JME AI Finance Pipeline Chart API..."
echo "  DATA_DIR: $JME_DATA_DIR"
echo "  CACHE_DIR: $JME_CACHE_DIR"
echo "  OLLAMA_URL: $OLLAMA_URL"
echo "  OLLAMA_MODEL: $OLLAMA_MODEL"
echo "  API: http://0.0.0.0:8011"
echo "  Docs: http://0.0.0.0:8011/docs"
echo ""

python -m uvicorn src.chart_api:app --host 0.0.0.0 --port 8011


