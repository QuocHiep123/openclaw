#!/usr/bin/env bash
# run_server.sh — Start the MCP tool server
# Run from the ai-lab/ directory: bash scripts/run_server.sh

set -euo pipefail

source .venv/bin/activate
echo "Starting MCP Tool Server…"
python main.py server
