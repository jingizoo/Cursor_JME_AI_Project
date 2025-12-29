#!/usr/bin/env bash
# Initialize git repository and make initial commit

set -e

echo "Initializing git repository..."

# Initialize git repo
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

echo ""
echo "Git repository initialized and initial commit created!"
echo ""
echo "To connect to a remote repository:"
echo "  git remote add origin <your-repo-url>"
echo "  git push -u origin main"
echo ""


