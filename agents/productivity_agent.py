"""
Productivity Agent — task tracking, progress summaries, research reports.
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

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "productivity_prompt.md"
_SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")

_LANG_SUFFIX = {
    "vi": "\n\nHãy trả lời bằng tiếng Việt.",
    "en": "",
}


class ProductivityAgent:
    """Agent that manages tasks, notes, and progress reports."""

    name = "ProductivityAgent"

    def __init__(self):
        self.llm = get_llm(temperature=0.3)

    async def run(self, task: str, chat_history: list = None) -> str:
        """
        Execute a productivity task.

        Typical commands:
            "add task: ..."  — add a new TODO
            "list tasks"     — show all tasks
            "report"         — weekly progress report
        """
        logger.info("[ProductivityAgent] Starting task: %s", task)

        lower = task.lower()

        # Add a task
        if lower.startswith("add task:") or lower.startswith("todo:"):
            content = task.split(":", 1)[1].strip()
            research_memory.store_task(content, status="open")
            return f"✅ Task added: **{content}**"

        # List tasks
        if "list" in lower and "task" in lower:
            tasks = research_memory.search_tasks("open task TODO", n=20)
            if not tasks:
                return "No tasks found in memory." if settings.bot_language == "en" else "Không tìm thấy task nào."
            lines = ["## 📋 Research Tasks\n"]
            for t in tasks:
                status = t["metadata"].get("status", "?")
                icon = "☑️" if status == "done" else "⬜"
                lines.append(f"{icon} {t['document']}")
            return "\n".join(lines)

        # Generate a progress report
        if "report" in lower or "progress" in lower or "summary" in lower:
            return await self._generate_report()

        # Fallback: ask LLM
        stats = research_memory.stats()
        lang = _LANG_SUFFIX.get(settings.bot_language, "")
        messages = [
            SystemMessage(content=_SYSTEM_PROMPT + lang),
            HumanMessage(
                content=(
                    f"User request: {task}\n\n"
                    f"Memory stats: {stats}\n"
                    "Please help with this productivity request."
                )
            ),
        ]
        resp = await self.llm.ainvoke(messages)
        return resp.content

    # ---- report -----------------------------------------------------------

    async def _generate_report(self) -> str:
        stats = research_memory.stats()
        now = datetime.now(timezone.utc).isoformat()

        # Gather recent items from each collection
        recent_papers = research_memory.search_papers("recent research papers", n=5)
        recent_ideas = research_memory.search_ideas("recent research ideas", n=5)
        recent_exps = research_memory.search_experiments("recent experiments", n=5)

        context = (
            f"Date: {now[:10]}\n"
            f"Stats: {stats}\n\n"
            f"Recent papers:\n{self._fmt(recent_papers)}\n\n"
            f"Recent ideas:\n{self._fmt(recent_ideas)}\n\n"
            f"Recent experiments:\n{self._fmt(recent_exps)}\n"
        )

        lang = _LANG_SUFFIX.get(settings.bot_language, "")
        messages = [
            SystemMessage(content=_SYSTEM_PROMPT + lang),
            HumanMessage(
                content=(
                    "Generate a concise research progress report based on:\n\n"
                    f"{context}\n\n"
                    "Include: papers reviewed, ideas generated, experiments run, and suggested next steps."
                )
            ),
        ]
        resp = await self.llm.ainvoke(messages)
        return resp.content

    @staticmethod
    def _fmt(items: list) -> str:
        if not items:
            return "(none)"
        return "\n".join(
            f"- {it['document'][:200]}" for it in items
        )
