"""
Research Agent — searches arXiv, summarises papers, generates ideas.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

from langchain_core.messages import HumanMessage, SystemMessage

from config.environment import get_llm
from config.settings import settings
from memory.research_memory import research_memory
from tools.arxiv_tool import arxiv_search, PaperInfo

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "research_prompt.md"
_SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")

_LANG_SUFFIX = {
    "vi": "\n\nHãy trả lời bằng tiếng Việt.",
    "en": "",
}


class ResearchAgent:
    """Agent that performs literature search, summarisation, and ideation."""

    name = "ResearchAgent"

    def __init__(self):
        self.llm = get_llm(temperature=0.4)

    async def run(self, task: str, chat_history: list = None) -> str:
        """
        Execute a research task.

        Args:
            task: User query (e.g. "transformer attention mechanisms").
            chat_history: Previous conversation messages for context.

        Returns:
            Markdown-formatted research report.
        """
        logger.info("[ResearchAgent] Starting task: %s", task)

        # 1. Search arXiv
        papers = arxiv_search(task, max_results=8)
        if not papers:
            return f"No papers found for query: **{task}**"

        # 2. Build context for the LLM
        paper_block = self._format_papers(papers)

        # 3. Build messages with chat history
        lang = _LANG_SUFFIX.get(settings.bot_language, "")
        messages = [
            SystemMessage(content=_SYSTEM_PROMPT + lang),
        ]
        # Add chat history for context
        if chat_history:
            for msg in chat_history[-6:]:  # Last 6 messages
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role == "user":
                    messages.append(HumanMessage(content=content))
                else:
                    from langchain_core.messages import AIMessage
                    messages.append(AIMessage(content=content))

        messages.append(
            HumanMessage(
                content=(
                    f"The user asked about: **{task}**\n\n"
                    f"Here are recent arXiv papers:\n\n{paper_block}\n\n"
                    "Please:\n"
                    "1. Summarise each paper (2-3 sentences).\n"
                    "2. Identify common themes.\n"
                    "3. Propose 3 novel research ideas inspired by these papers."
                )
            ),
        )

        response = await self.llm.ainvoke(messages)
        report = response.content

        # 4. Store in memory
        for paper in papers:
            research_memory.store_paper(
                arxiv_id=paper.arxiv_id,
                title=paper.title,
                summary=paper.abstract,
                metadata={
                    "authors": ", ".join(paper.authors),
                    "categories": ", ".join(paper.categories),
                    "published": paper.published,
                },
            )

        logger.info("[ResearchAgent] Stored %d papers in memory", len(papers))
        return report

    # ---- helpers ----------------------------------------------------------

    @staticmethod
    def _format_papers(papers: list[PaperInfo]) -> str:
        parts = []
        for i, p in enumerate(papers, 1):
            parts.append(
                f"### {i}. {p.title}\n"
                f"**ID:** {p.arxiv_id} | **Published:** {p.published}\n"
                f"**Authors:** {', '.join(p.authors)}\n"
                f"**Abstract:** {p.short_summary(500)}\n"
            )
        return "\n".join(parts)
