# Linux Deployment Guide - JME AI Finance Pipeline

This guide covers deploying the JME AI Finance Pipeline on a Linux machine.

## Prerequisites

### 1. Python 3.8+ Installation

```bash
# Check Python version
python3 --version

# If not installed, install Python 3.8+ (Ubuntu/Debian)
sudo apt update
sudo apt install -y python3 python3-pip python3-venv

# For CentOS/RHEL
sudo yum install -y python3 python3-pip
```

### 2. Ollama Installation and Setup

```bash
# Install Ollama (if not already installed)
curl -fsSL https://ollama.com/install.sh | sh

# Start Ollama service
ollama serve

# In another terminal, pull the required model
ollama pull qwen3:8b

# Verify Ollama is running
curl http://localhost:11434/api/tags
```

**Note:** If Ollama is running on a different machine, you'll need to configure the `OLLAMA_URL` environment variable accordingly.

## Deployment Steps

### Step 1: Transfer Files to Linux Machine

Transfer the project files to your Linux machine using one of these methods:

**Option A: Using SCP**
```bash
# From your local machine
scp -r /path/to/Cursor_JME_AI_Project user@linux-host:/home/user/
```

**Option B: Using Git**
```bash
# On Linux machine
git clone <your-repo-url>
cd Cursor_JME_AI_Project
```

**Option C: Using rsync**
```bash
# From your local machine
rsync -avz /path/to/Cursor_JME_AI_Project user@linux-host:/home/user/
```

### Step 2: Navigate to Project Directory

```bash
cd /path/to/Cursor_JME_AI_Project
```

### Step 3: Create Python Virtual Environment

```bash
# Create virtual environment
python3 -m venv .venv

# Activate virtual environment
source .venv/bin/activate
```

### Step 4: Install Dependencies

```bash
# Upgrade pip
pip install --upgrade pip

# Install project dependencies
pip install -r requirements.txt
```

### Step 5: Create Required Directories

```bash
# Create data directory (if it doesn't exist)
mkdir -p data

# Create cache directory (will be created automatically, but you can pre-create it)
mkdir -p .cache
```

### Step 6: Configure Environment Variables

Create a configuration script or set environment variables:

**Option A: Using the provided start.sh script (recommended for development)**
```bash
# The start.sh script already sets defaults
# Edit it if you need to change OLLAMA_URL or OLLAMA_MODEL
chmod +x start.sh
```

**Option B: Create a .env file (for production)**
```bash
# Create .env file
cat > .env << EOF
JME_DATA_DIR=./data
JME_CACHE_DIR=./.cache
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=qwen3:8b
EOF
```

**Option C: Export environment variables directly**
```bash
export JME_DATA_DIR="./data"
export JME_CACHE_DIR="./.cache"
export OLLAMA_URL="http://localhost:11434"  # Change if Ollama is on different machine
export OLLAMA_MODEL="qwen3:8b"
```

### Step 7: Verify Ollama Connection

```bash
# Test Ollama connectivity
export OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"
curl -s $OLLAMA_URL/api/tags | head

# If Ollama is on a different machine, use that machine's IP
# export OLLAMA_URL="http://<LINUX_IP>:11434"
```

### Step 8: Run the Application

**Development Mode (using start.sh):**
```bash
# Make script executable
chmod +x start.sh

# Run the application
./start.sh
```

**Or manually:**
```bash
source .venv/bin/activate
export JME_DATA_DIR="./data"
export JME_CACHE_DIR="./.cache"
export OLLAMA_URL="http://localhost:11434"
export OLLAMA_MODEL="qwen3:8b"
python -m uvicorn src.api:app --host 0.0.0.0 --port 8010
```

The API will be available at:
- **API**: http://localhost:8010
- **Swagger Docs**: http://localhost:8010/docs
- **Health Check**: http://localhost:8010/health

## Production Deployment

### Option 1: Using systemd Service (Recommended)

Create a systemd service file for automatic startup and management:

```bash
# Create service file
sudo nano /etc/systemd/system/jme-ai-pipeline.service
```

Add the following content (adjust paths as needed):

```ini
[Unit]
Description=JME AI Finance Pipeline API
After=network.target

[Service]
Type=simple
User=your-username
WorkingDirectory=/home/your-username/Cursor_JME_AI_Project
Environment="PATH=/home/your-username/Cursor_JME_AI_Project/.venv/bin"
Environment="JME_DATA_DIR=/home/your-username/Cursor_JME_AI_Project/data"
Environment="JME_CACHE_DIR=/home/your-username/Cursor_JME_AI_Project/.cache"
Environment="OLLAMA_URL=http://localhost:11434"
Environment="OLLAMA_MODEL=qwen3:8b"
ExecStart=/home/your-username/Cursor_JME_AI_Project/.venv/bin/python -m uvicorn src.api:app --host 0.0.0.0 --port 8010
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**Enable and start the service:**
```bash
# Reload systemd
sudo systemctl daemon-reload

# Enable service to start on boot
sudo systemctl enable jme-ai-pipeline

# Start the service
sudo systemctl start jme-ai-pipeline

# Check status
sudo systemctl status jme-ai-pipeline

# View logs
sudo journalctl -u jme-ai-pipeline -f
```

### Option 2: Using screen/tmux (Simple)

```bash
# Install screen (if not installed)
sudo apt install screen  # or: sudo yum install screen

# Start a screen session
screen -S jme-pipeline

# Activate venv and run
source .venv/bin/activate
export JME_DATA_DIR="./data"
export JME_CACHE_DIR="./.cache"
export OLLAMA_URL="http://localhost:11434"
export OLLAMA_MODEL="qwen3:8b"
python -m uvicorn src.api:app --host 0.0.0.0 --port 8010

# Detach: Press Ctrl+A, then D
# Reattach: screen -r jme-pipeline
```

### Option 3: Using nohup (Background)

```bash
source .venv/bin/activate
export JME_DATA_DIR="./data"
export JME_CACHE_DIR="./.cache"
export OLLAMA_URL="http://localhost:11434"
export OLLAMA_MODEL="qwen3:8b"
nohup python -m uvicorn src.api:app --host 0.0.0.0 --port 8010 > app.log 2>&1 &
```

## Firewall Configuration

If you need to access the API from other machines:

```bash
# Ubuntu/Debian (ufw)
sudo ufw allow 8010/tcp
sudo ufw reload

# CentOS/RHEL (firewalld)
sudo firewall-cmd --permanent --add-port=8010/tcp
sudo firewall-cmd --reload

# If Ollama is on a different machine, also allow port 11434
sudo ufw allow 11434/tcp  # Ubuntu/Debian
# or
sudo firewall-cmd --permanent --add-port=11434/tcp  # CentOS/RHEL
```

## Testing the Deployment

### 1. Health Check
```bash
curl http://localhost:8010/health
```

### 2. Check API Documentation
Open in browser: `http://<server-ip>:8010/docs`

### 3. Test Ingest Endpoint
```bash
# Place Excel files in the data/ directory first
curl -X POST http://localhost:8010/ingest \
  -H "Content-Type: application/json" \
  -d '{"force": false}'
```

### 4. Test Catalog Endpoint
```bash
curl http://localhost:8010/catalog
```

## Troubleshooting

### Issue: Cannot connect to Ollama
**Solution:**
- Verify Ollama is running: `curl http://localhost:11434/api/tags`
- Check firewall settings if Ollama is on a different machine
- Verify `OLLAMA_URL` environment variable is set correctly

### Issue: Port 8010 already in use
**Solution:**
```bash
# Find process using port 8010
sudo lsof -i :8010
# or
sudo netstat -tulpn | grep 8010

# Kill the process or change port in uvicorn command
python -m uvicorn src.api:app --host 0.0.0.0 --port 8011
```

### Issue: Permission denied errors
**Solution:**
```bash
# Ensure directories are writable
chmod -R 755 data
chmod -R 755 .cache

# If using systemd, check user permissions in service file
```

### Issue: Python module not found
**Solution:**
```bash
# Ensure virtual environment is activated
source .venv/bin/activate

# Reinstall dependencies
pip install -r requirements.txt
```

## Maintenance

### Updating the Application
```bash
# Pull latest changes (if using git)
git pull

# Activate venv
source .venv/bin/activate

# Update dependencies
pip install -r requirements.txt --upgrade

# Restart service (if using systemd)
sudo systemctl restart jme-ai-pipeline
```

### Viewing Logs
```bash
# If using systemd
sudo journalctl -u jme-ai-pipeline -f

# If using nohup
tail -f app.log

# If using screen
screen -r jme-pipeline
```

### Backup
```bash
# Backup data and cache directories
tar -czf backup-$(date +%Y%m%d).tar.gz data/ .cache/
```

## Security Considerations

1. **Firewall**: Only open necessary ports (8010 for API, 11434 for Ollama if remote)
2. **User Permissions**: Run the service as a non-root user
3. **HTTPS**: For production, consider using a reverse proxy (nginx) with SSL/TLS
4. **Authentication**: Consider adding API authentication for production use

## Next Steps

1. Place your Excel files in the `data/` directory
2. Call `/ingest` endpoint to process files
3. Use `/ask` endpoint for natural language queries
4. Generate reports using `/report-pack` endpoint

For more details, see the main README.md file.


