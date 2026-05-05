"""
Daily pipeline — scheduled entry-point for all recurring automations.

Tasks:
    1. Run NLP/LLM daily research report (PDF + email).
    2. Run the arXiv pipeline.
    3. Generate a progress report.
    4. Return the combined report.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from pipelines.arxiv_pipeline import run_arxiv_pipeline
from pipelines.nlp_llm_research_pipeline import run_nlp_llm_daily_research_report
from agents.productivity_agent import ProductivityAgent

logger = logging.getLogger(__name__)


async def run_daily_pipeline() -> str:
    """
    Execute all daily tasks and return a combined Markdown report.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    sections = [f"# 🗓️ Daily Report — {now}\n"]

    # 1. NLP/LLM research email report
    logger.info("Daily pipeline: running NLP/LLM research report…")
    try:
        result = await run_nlp_llm_daily_research_report()
        sections.append(
            "## ✅ NLP_LLM_Daily_Research_Report\n"
            f"- Status: {result['status']}\n"
            f"- PDF: {result['pdf_path']}\n"
            f"- Recipient: {result['recipient']}\n"
            f"- Fetched papers: {result['fetched_papers']}\n"
            f"- Selected papers: {result['selected_papers']}"
        )
    except Exception as exc:
        logger.error("NLP/LLM report pipeline failed: %s", exc)
        sections.append(f"⚠️ NLP/LLM report pipeline failed: {exc}")

    # 2. arXiv pipeline
    logger.info("Daily pipeline: running arXiv fetch…")
    try:
        arxiv_report = await run_arxiv_pipeline()
        sections.append(arxiv_report)
    except Exception as exc:
        logger.error("arXiv pipeline failed: %s", exc)
        sections.append(f"⚠️ arXiv pipeline failed: {exc}")

    # 3. Productivity report
    logger.info("Daily pipeline: generating progress report…")
    try:
        prod_agent = ProductivityAgent()
        progress = await prod_agent.run("generate daily progress report")
        sections.append(f"\n---\n{progress}")
    except Exception as exc:
        logger.error("Progress report failed: %s", exc)
        sections.append(f"⚠️ Progress report failed: {exc}")

    return "\n\n".join(sections)
