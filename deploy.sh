#!/bin/bash
set -euo pipefail

cd ~/OpenClaw/ai-lab || cd ~/OpenClaw

echo "[1/4] Pull latest code..."
git pull --rebase

echo "[2/4] Stop current containers..."
docker compose down

echo "[3/4] Build and start containers..."
docker compose up -d --build

echo "[4/4] Status..."
docker compose ps

echo "Deploy completed successfully."
