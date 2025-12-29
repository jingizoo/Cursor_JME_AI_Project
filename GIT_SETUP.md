# Git Repository Setup

This guide will help you initialize a git repository and commit all files.

## Prerequisites

Install Git if you haven't already:
- **Windows**: Download from [https://git-scm.com/download/win](https://git-scm.com/download/win)
- **Linux**: `sudo apt install git` (Ubuntu/Debian) or `sudo yum install git` (CentOS/RHEL)
- **macOS**: `brew install git` or download from [https://git-scm.com/download/mac](https://git-scm.com/download/mac)

## Quick Setup

### Option 1: Using the provided script

**Windows (PowerShell):**
```powershell
.\init_git.ps1
```

**Linux/macOS:**
```bash
chmod +x init_git.sh
./init_git.sh
```

### Option 2: Manual setup

```bash
# Initialize git repository
git init

# Add all files
git add .

# Make initial commit
git commit -m "Initial commit: JME AI Finance Pipeline

- FastAPI application for Excel file ingestion and analysis
- Ollama LLM integration for schema mapping and SQL generation
- DuckDB for data storage
- Natural language to SQL query interface
- Monthly report pack generation
- Linux deployment scripts and documentation"
```

## Connect to Remote Repository

After initializing the repository, you can connect it to a remote repository (GitHub, GitLab, etc.):

```bash
# Add remote repository
git remote add origin <your-repo-url>

# Push to remote
git push -u origin main
```

If your default branch is `master` instead of `main`:
```bash
git branch -M main
git push -u origin main
```

## What's Included

The repository includes:
- ✅ All source code (`src/` directory)
- ✅ Configuration files (`requirements.txt`, `README.md`)
- ✅ Deployment scripts (`deploy.sh`, `start.sh`, `start.ps1`)
- ✅ Documentation (`DEPLOYMENT_LINUX.md`, `GIT_SETUP.md`)
- ✅ `.gitignore` file (excludes virtual environment, cache, database files, etc.)

## What's Excluded

The `.gitignore` file excludes:
- Virtual environment (`.venv/`, `venv/`)
- Cache directory (`.cache/`)
- Database files (`.db`, `.duckdb`)
- Python cache (`__pycache__/`, `*.pyc`)
- Environment files (`.env`)
- IDE files (`.vscode/`, `.idea/`)
- Data files (contents of `data/` directory)
- Temporary files and logs

## Next Steps

1. Initialize the repository using one of the methods above
2. Create a repository on GitHub/GitLab/Bitbucket
3. Connect your local repository to the remote
4. Push your code


