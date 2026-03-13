#!/usr/bin/env bash
# setup.sh — Bootstrap the AI Research Lab environment
# Run from the ai-lab/ directory: bash scripts/setup.sh

set -euo pipefail

echo "=== AI Research Lab — Setup ==="

# 1. Check Python version
PYTHON=${PYTHON:-python3}
echo "[1/5] Checking Python…"
$PYTHON --version

# 2. Create virtual environment
echo "[2/5] Creating virtual environment…"
$PYTHON -m venv .venv
source .venv/bin/activate

# 3. Upgrade pip
echo "[3/5] Upgrading pip…"
pip install --upgrade pip

# 4. Install dependencies
echo "[4/5] Installing dependencies…"
pip install -r requirements.txt

# 5. Create .env from template if it doesn't exist
echo "[5/5] Setting up .env…"
if [ ! -f .env ]; then
    cp .env.example .env
    echo "  → Created .env from .env.example.  Please edit it with your API keys."
else
    echo "  → .env already exists, skipping."
fi

echo ""
echo "=== Setup complete! ==="
echo "Activate the environment:  source .venv/bin/activate"
echo "Edit your API keys:        nano .env"
echo "Start the CLI:             python main.py cli"
echo "Start the Telegram bot:    python main.py bot"
echo "Start the MCP server:      python main.py server"
