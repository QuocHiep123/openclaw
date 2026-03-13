"""
AI Research Lab — main entry-point.

Usage:
    python main.py bot          # Start Telegram bot
    python main.py cli          # Start interactive CLI
    python main.py server       # Start MCP tool server
    python main.py daily        # Run daily pipeline once
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys

from config.settings import settings


def _setup_logging():
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main():
    _setup_logging()
    logger = logging.getLogger("ai-lab")

    if len(sys.argv) >= 2:
        command = sys.argv[1].lower()
    else:
        command = os.getenv("APP_MODE", "bot").lower()
        logger.info("No CLI command provided, using APP_MODE=%s", command)

    if command == "bot":
        from interface.telegram_bot import start_bot
        logger.info("Launching Telegram bot…")
        start_bot()

    elif command == "cli":
        from interface.cli import main as cli_main
        cli_main()

    elif command == "server":
        from mcp.server import start_server
        logger.info("Launching MCP tool server on %s:%s", settings.mcp_host, settings.mcp_port)
        start_server()

    elif command == "daily":
        from pipelines.daily_pipeline import run_daily_pipeline

        async def _run():
            report = await run_daily_pipeline()
            print(report)

        logger.info("Running daily pipeline…")
        asyncio.run(_run())

    else:
        print(f"Unknown command: {command}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
