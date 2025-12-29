# Initialize git repository and make initial commit (PowerShell)

Write-Host "Initializing git repository..." -ForegroundColor Yellow

# Check if git is installed
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "Error: Git is not installed. Please install Git first:" -ForegroundColor Red
    Write-Host "  Download from: https://git-scm.com/download/win" -ForegroundColor Yellow
    exit 1
}

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

Write-Host ""
Write-Host "Git repository initialized and initial commit created!" -ForegroundColor Green
Write-Host ""
Write-Host "To connect to a remote repository:" -ForegroundColor Cyan
Write-Host "  git remote add origin <your-repo-url>"
Write-Host "  git push -u origin main"
Write-Host ""


