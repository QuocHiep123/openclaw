"""
Daily pipeline — scheduled entry-point for all recurring automations.

Tasks:
    1. Run the arXiv pipeline.
    2. Generate a progress report.
    3. Return the combined report (for Telegram delivery).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from pipelines.arxiv_pipeline import run_arxiv_pipeline
from agents.productivity_agent import ProductivityAgent

logger = logging.getLogger(__name__)


async def run_daily_pipeline() -> str:
    """
    Execute all daily tasks and return a combined Markdown report.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    sections = [f"# 🗓️ Daily Report — {now}\n"]

    # 1. arXiv pipeline
    logger.info("Daily pipeline: running arXiv fetch…")
    try:
        arxiv_report = await run_arxiv_pipeline()
        sections.append(arxiv_report)
    except Exception as exc:
        logger.error("arXiv pipeline failed: %s", exc)
        sections.append(f"⚠️ arXiv pipeline failed: {exc}")

    # 2. Productivity report
    logger.info("Daily pipeline: generating progress report…")
    try:
        prod_agent = ProductivityAgent()
        progress = await prod_agent.run("generate daily progress report")
        sections.append(f"\n---\n{progress}")
    except Exception as exc:
        logger.error("Progress report failed: %s", exc)
        sections.append(f"⚠️ Progress report failed: {exc}")

    return "\n\n".join(sections)
