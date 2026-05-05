# 🔬 AI Research Lab — Multi-Agent Automation System

An AI-powered research automation system with **multi-agent architecture**, **LangGraph orchestration**, **MCP tool server**, and **Telegram interface**.

## Architecture Overview

```
Telegram / CLI
      │
      ▼
  LangGraph Orchestrator
      │
  ┌───┼───────────┬──────────────┐
  ▼   ▼           ▼              ▼
Research  Experiment  Automation  Productivity
 Agent      Agent       Agent       Agent
  │         │           │           │
  └─────────┴─────┬─────┴───────────┘
                  ▼
           Shared Memory (Chroma)
                  │
            MCP Tool Server
         ┌────┬────┬────┬────┐
         arXiv GitHub Python FS  Web
```

## Quick Start

### 1. Clone & Setup

```bash
cd ai-lab
# Windows:
.\scripts\setup.ps1
# Linux/macOS:
bash scripts/setup.sh
```

### 2. Configure API Keys

Edit `.env` with your keys:
```
OPENAI_API_KEY=sk-...
TELEGRAM_BOT_TOKEN=123456:ABC...
```

### 3. Run

```bash
# Interactive CLI
python main.py cli

# Telegram bot
python main.py bot

# MCP tool server
python main.py server

# Run daily pipeline once
python main.py daily

# Run NLP/LLM PDF email report once
python main.py nlp_daily_report
```

## NLP/LLM Daily Research Report

Pipeline name: **NLP_LLM_Daily_Research_Report**

What it does automatically:
- Fetch newest arXiv papers from `cs.CL`, `cs.AI` (up to 50)
- Filter for NLP/LLM relevance with LLM scoring
- Summarise each selected paper
- Generate teaching-style research lessons + ideas
- Build a structured digest
- Generate `NLP_LLM_Research_Report_YYYY_MM_DD.pdf`
- Send PDF to Gmail via SMTP

Required `.env` values:
```
GMAIL_ADDRESS=your-gmail@gmail.com
GMAIL_APP_PASSWORD=your-app-password
RESEARCH_REPORT_RECIPIENT=dangquochiep2908@gmail.com
RESEARCH_REPORT_HOUR=7
RESEARCH_REPORT_MINUTE=30
```

Recommended host cron schedule (UTC):
```bash
30 7 * * * cd /path/to/ai-lab && /path/to/ai-lab/.venv/Scripts/python main.py nlp_daily_report >> /path/to/ai-lab/logs/nlp_daily_report.log 2>&1
```

## Commands

| Command | Description |
|---------|-------------|
| `/paper <query>` | Search & summarise arXiv papers |
| `/experiment <name>` | Design & run an ML experiment |
| `/daily` | Run the daily automation pipeline |
| `/todo <text>` | Add a research task |
| `/tasks` | List all tasks |
| `/report` | Generate progress report |
| `/status` | System status |

## Project Structure

```
ai-lab/
├── agents/           # Four specialised agents
├── orchestrator/     # LangGraph workflow & router
├── tools/            # arXiv, GitHub, Python runner, etc.
├── mcp/              # FastAPI tool server
├── memory/           # Chroma vector store
├── pipelines/        # Daily & arXiv automation
├── interface/        # Telegram bot & CLI
├── prompts/          # Agent system prompts
├── config/           # Settings & environment
├── scripts/          # Setup & run scripts
└── main.py           # Entry point
```

## Technology Stack

- **LangGraph** + **LangChain** — agent orchestration
- **Chroma** — vector memory
- **FastAPI** — MCP tool server
- **python-telegram-bot** — Telegram interface
- **OpenAI / Gemini** — LLM backend

## Deploy 24/7 (Recommended)

This project is now container-ready and supports runtime mode via environment variable:

```
APP_MODE=bot      # Telegram bot worker (24/7)
APP_MODE=server   # MCP FastAPI server
APP_MODE=nlp_daily_report  # Run NLP/LLM report pipeline once
```

### Option A — Docker Compose on VPS (most stable)

1. Prepare env:

```bash
cp .env.example .env
# Fill OPENAI_API_KEY, TELEGRAM_BOT_TOKEN, etc.
```

2. Start services:

```bash
docker compose up -d --build
```

3. Check status/logs:

```bash
docker compose ps
docker compose logs -f bot
docker compose logs -f mcp
```

`restart: always` keeps both services running after reboot/crash.

### Option B — Deploy Telegram bot as a cloud worker

For Railway/Render/Fly workers:

- Build from the included `Dockerfile`
- Set environment variables from `.env.example`
- Set `APP_MODE=bot`
- Mount persistent volume for `/app/data` (for Chroma memory)

If you also want MCP HTTP API online, deploy a second service with:

- `APP_MODE=server`
- Exposed port `8100`
