"""
Automation Agent — manages daily pipelines, scheduling, and triggers.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

from config.environment import get_llm
from config.settings import settings
from memory.research_memory import research_memory

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "automation_prompt.md"
_SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")

_LANG_SUFFIX = {
    "vi": "\n\nHãy trả lời bằng tiếng Việt.",
    "en": "",
}


class AutomationAgent:
    """Agent that runs and monitors automated research pipelines."""

    name = "AutomationAgent"

    def __init__(self):
        self.llm = get_llm(temperature=0.2)

    async def run(self, task: str, chat_history: list = None) -> str:
        """
        Execute an automation / pipeline task.

        Typical commands:
            "daily" — run the daily pipeline
            "status" — report system status
        """
        logger.info("[AutomationAgent] Starting task: %s", task)

        # Gather system stats
        stats = research_memory.stats()
        now = datetime.now(timezone.utc).isoformat()

        if "daily" in task.lower():
            return await self._run_daily_pipeline(stats, now)

        if "status" in task.lower():
            return self._status_report(stats, now)

        # Generic: ask LLM
        lang = _LANG_SUFFIX.get(settings.bot_language, "")
        messages = [
            SystemMessage(content=_SYSTEM_PROMPT + lang),
            HumanMessage(
                content=(
                    f"Task: {task}\n\n"
                    f"Current time (UTC): {now}\n"
                    f"Memory stats: {stats}\n\n"
                    "Please carry out this automation task and provide a report."
                )
            ),
        ]
        response = await self.llm.ainvoke(messages)
        return response.content

    # ---- pipelines --------------------------------------------------------

    async def _run_daily_pipeline(self, stats: dict, now: str) -> str:
        """Trigger the daily arXiv pipeline and return a report."""
        from pipelines.arxiv_pipeline import run_arxiv_pipeline

        report = await run_arxiv_pipeline()
        updated_stats = research_memory.stats()

        return (
            f"## Daily Pipeline Report — {now[:10]}\n\n"
            f"{report}\n\n"
            f"**Memory after run:** {updated_stats}"
        )

    @staticmethod
    def _status_report(stats: dict, now: str) -> str:
        lines = [
            f"## 📊 System Status — {now[:10]}",
            "",
            "| Collection | Count |",
            "|------------|-------|",
        ]
        for name, count in stats.items():
            lines.append(f"| {name} | {count} |")
        return "\n".join(lines)
