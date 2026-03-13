# setup.ps1 — Bootstrap the AI Research Lab environment on Windows
# Run from the ai-lab/ directory: .\scripts\setup.ps1

Write-Host "=== AI Research Lab — Setup ==="

# 1. Check Python
Write-Host "[1/5] Checking Python…"
python --version

# 2. Create virtual environment
Write-Host "[2/5] Creating virtual environment…"
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3. Upgrade pip
Write-Host "[3/5] Upgrading pip…"
pip install --upgrade pip

# 4. Install dependencies
Write-Host "[4/5] Installing dependencies…"
pip install -r requirements.txt

# 5. Create .env
Write-Host "[5/5] Setting up .env…"
if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
    Write-Host "  -> Created .env from .env.example. Please edit it with your API keys."
} else {
    Write-Host "  -> .env already exists, skipping."
}

Write-Host ""
Write-Host "=== Setup complete! ==="
Write-Host "Activate the environment:  .\.venv\Scripts\Activate.ps1"
Write-Host "Edit your API keys:        notepad .env"
Write-Host "Start the CLI:             python main.py cli"
Write-Host "Start the Telegram bot:    python main.py bot"
Write-Host "Start the MCP server:      python main.py server"
