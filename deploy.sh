#!/usr/bin/env bash
# JME AI Finance Pipeline - Linux Deployment Script
# This script automates the deployment process on Linux

set -e

echo "=========================================="
echo "JME AI Finance Pipeline - Linux Deployment"
echo "=========================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if Python 3 is installed
echo -e "${YELLOW}Checking Python installation...${NC}"
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: Python 3 is not installed.${NC}"
    echo "Please install Python 3.8+ first:"
    echo "  Ubuntu/Debian: sudo apt install python3 python3-pip python3-venv"
    echo "  CentOS/RHEL: sudo yum install python3 python3-pip"
    exit 1
fi

PYTHON_VERSION=$(python3 --version | cut -d' ' -f2 | cut -d'.' -f1,2)
echo -e "${GREEN}Python ${PYTHON_VERSION} found${NC}"
echo ""

# Check if Ollama is accessible
echo -e "${YELLOW}Checking Ollama connection...${NC}"
OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"
if curl -s --max-time 5 "$OLLAMA_URL/api/tags" > /dev/null 2>&1; then
    echo -e "${GREEN}Ollama is accessible at ${OLLAMA_URL}${NC}"
else
    echo -e "${YELLOW}Warning: Cannot connect to Ollama at ${OLLAMA_URL}${NC}"
    echo "Make sure Ollama is running and accessible."
    echo "You can set OLLAMA_URL environment variable if it's on a different machine."
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi
echo ""

# Create virtual environment
echo -e "${YELLOW}Setting up Python virtual environment...${NC}"
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    echo -e "${GREEN}Virtual environment created${NC}"
else
    echo -e "${GREEN}Virtual environment already exists${NC}"
fi

# Activate virtual environment
source .venv/bin/activate

# Upgrade pip
echo -e "${YELLOW}Upgrading pip...${NC}"
pip install --upgrade pip --quiet

# Install dependencies
echo -e "${YELLOW}Installing dependencies...${NC}"
pip install -r requirements.txt --quiet
echo -e "${GREEN}Dependencies installed${NC}"
echo ""

# Create required directories
echo -e "${YELLOW}Creating required directories...${NC}"
mkdir -p data
mkdir -p .cache
echo -e "${GREEN}Directories created${NC}"
echo ""

# Set environment variables
export JME_DATA_DIR="./data"
export JME_CACHE_DIR="./.cache"
export OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"
export OLLAMA_MODEL="${OLLAMA_MODEL:-qwen3:8b}"

echo -e "${GREEN}=========================================="
echo "Deployment completed successfully!"
echo "==========================================${NC}"
echo ""
echo "Configuration:"
echo "  DATA_DIR: $JME_DATA_DIR"
echo "  CACHE_DIR: $JME_CACHE_DIR"
echo "  OLLAMA_URL: $OLLAMA_URL"
echo "  OLLAMA_MODEL: $OLLAMA_MODEL"
echo ""
echo "To start the application:"
echo "  1. Activate virtual environment: source .venv/bin/activate"
echo "  2. Run: ./start.sh"
echo "  Or: python -m uvicorn src.api:app --host 0.0.0.0 --port 8010"
echo ""
echo "API will be available at:"
echo "  - http://localhost:8010"
echo "  - http://localhost:8010/docs (Swagger UI)"
echo "  - http://localhost:8010/health (Health check)"
echo ""


