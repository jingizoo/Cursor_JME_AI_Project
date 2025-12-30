#!/bin/bash
# Installation script for JME AI Finance Pipeline
# Supports Linux and macOS

set -e  # Exit on error

echo "🚀 JME AI Finance Pipeline - Installation Script"
echo "================================================"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check Python version
echo "📋 Checking prerequisites..."
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ Python 3 is not installed. Please install Python 3.8 or higher.${NC}"
    exit 1
fi

PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}' | cut -d. -f1,2)
PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)

if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 8 ]); then
    echo -e "${RED}❌ Python 3.8 or higher is required. Found: Python $PYTHON_VERSION${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Python $PYTHON_VERSION found${NC}"

# Check Ollama
if ! command -v ollama &> /dev/null; then
    echo -e "${YELLOW}⚠️  Ollama is not installed or not in PATH${NC}"
    echo "   Please install Ollama from https://ollama.ai"
    echo "   After installation, make sure 'ollama' command is available"
    read -p "   Press Enter to continue anyway (you'll need to install Ollama later)..."
else
    echo -e "${GREEN}✓ Ollama found${NC}"
fi

# Create virtual environment
echo ""
echo "📦 Creating virtual environment..."
if [ -d "venv" ]; then
    echo -e "${YELLOW}⚠️  Virtual environment already exists. Removing old one...${NC}"
    rm -rf venv
fi

python3 -m venv venv
echo -e "${GREEN}✓ Virtual environment created${NC}"

# Activate virtual environment
echo ""
echo "🔧 Activating virtual environment..."
source venv/bin/activate
echo -e "${GREEN}✓ Virtual environment activated${NC}"

# Upgrade pip
echo ""
echo "⬆️  Upgrading pip..."
pip install --upgrade pip setuptools wheel
echo -e "${GREEN}✓ pip upgraded${NC}"

# Install dependencies
echo ""
echo "📥 Installing Python dependencies..."
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt
    echo -e "${GREEN}✓ Dependencies installed${NC}"
else
    echo -e "${RED}❌ requirements.txt not found${NC}"
    exit 1
fi

# Create necessary directories
echo ""
echo "📁 Creating directories..."
mkdir -p data
mkdir -p .cache
mkdir -p data/.chroma_db
echo -e "${GREEN}✓ Directories created${NC}"

# Check Ollama models
echo ""
echo "🤖 Checking Ollama models..."

if command -v ollama &> /dev/null; then
    # Check if Ollama is running
    if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
        echo -e "${GREEN}✓ Ollama is running${NC}"
        
        # Check for LLM model
        LLM_MODEL="${OLLAMA_MODEL:-qwen3:8b}"
        echo "   Checking for LLM model: $LLM_MODEL"
        if ollama list | grep -q "$LLM_MODEL"; then
            echo -e "${GREEN}✓ LLM model '$LLM_MODEL' found${NC}"
        else
            echo -e "${YELLOW}⚠️  LLM model '$LLM_MODEL' not found${NC}"
            read -p "   Would you like to pull it now? (y/n) " -n 1 -r
            echo
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                ollama pull "$LLM_MODEL"
                echo -e "${GREEN}✓ LLM model pulled${NC}"
            fi
        fi
        
        # Check for embedding model
        EMBEDDING_MODEL="nomic-embed-text"
        echo "   Checking for embedding model: $EMBEDDING_MODEL"
        if ollama list | grep -q "$EMBEDDING_MODEL"; then
            echo -e "${GREEN}✓ Embedding model '$EMBEDDING_MODEL' found${NC}"
        else
            echo -e "${YELLOW}⚠️  Embedding model '$EMBEDDING_MODEL' not found${NC}"
            read -p "   Would you like to pull it now? (y/n) " -n 1 -r
            echo
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                ollama pull "$EMBEDDING_MODEL"
                echo -e "${GREEN}✓ Embedding model pulled${NC}"
            fi
        fi
    else
        echo -e "${YELLOW}⚠️  Ollama is not running${NC}"
        echo "   Please start Ollama: ollama serve"
        echo "   Or run: ollama pull qwen3:8b"
        echo "   And: ollama pull nomic-embed-text"
    fi
else
    echo -e "${YELLOW}⚠️  Ollama not found in PATH${NC}"
    echo "   Please install Ollama and pull required models:"
    echo "   - ollama pull qwen3:8b"
    echo "   - ollama pull nomic-embed-text"
fi

# Create .env.example if it doesn't exist
echo ""
echo "📝 Setting up configuration..."
if [ ! -f ".env.example" ]; then
    cat > .env.example << 'EOF'
# Ollama Configuration
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=qwen3:8b

# Data Directories
JME_DATA_DIR=./data
JME_CACHE_DIR=./.cache

# CORS (for Superset integration)
CORS_ORIGINS=*
EOF
    echo -e "${GREEN}✓ Created .env.example${NC}"
fi

# Create startup script
echo ""
echo "📝 Creating startup scripts..."

# Linux startup script
cat > start.sh << 'EOF'
#!/bin/bash
# Start the JME AI Finance Pipeline API

# Activate virtual environment
if [ -d "venv" ]; then
    source venv/bin/activate
else
    echo "❌ Virtual environment not found. Please run install.sh first."
    exit 1
fi

# Check if Ollama is running
if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "⚠️  Warning: Ollama doesn't seem to be running."
    echo "   Please start Ollama: ollama serve"
    echo ""
fi

# Load environment variables if .env exists
if [ -f ".env" ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

# Default values
OLLAMA_URL=${OLLAMA_URL:-http://localhost:11434}
OLLAMA_MODEL=${OLLAMA_MODEL:-qwen3:8b}
PORT=${PORT:-8010}

echo "🚀 Starting JME AI Finance Pipeline API..."
echo "   Ollama URL: $OLLAMA_URL"
echo "   Ollama Model: $OLLAMA_MODEL"
echo "   Port: $PORT"
echo ""

python -m uvicorn src.api:app --host 0.0.0.0 --port $PORT
EOF

chmod +x start.sh
echo -e "${GREEN}✓ Created start.sh${NC}"

# Summary
echo ""
echo "================================================"
echo -e "${GREEN}✅ Installation Complete!${NC}"
echo "================================================"
echo ""
echo "Next steps:"
echo ""
echo "1. Activate the virtual environment:"
echo "   source venv/bin/activate"
echo ""
echo "2. (Optional) Create .env file with your configuration:"
echo "   cp .env.example .env"
echo "   # Edit .env as needed"
echo ""
echo "3. Make sure Ollama is running:"
echo "   ollama serve"
echo ""
echo "4. Pull required models (if not done during installation):"
echo "   ollama pull qwen3:8b"
echo "   ollama pull nomic-embed-text"
echo ""
echo "5. Place your Excel/PDF files in the data/ directory"
echo ""
echo "6. Start the API:"
echo "   ./start.sh"
echo "   # Or: python -m uvicorn src.api:app --host 0.0.0.0 --port 8010"
echo ""
echo "7. Access the API:"
echo "   http://localhost:8010/docs"
echo ""
echo "For more information, see:"
echo "  - DEPLOYMENT_LINUX.md"
echo "  - VECTOR_DB_README.md"
echo "  - WIKI_INGESTION_README.md"
echo ""

