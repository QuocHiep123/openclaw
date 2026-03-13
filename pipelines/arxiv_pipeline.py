"""
arXiv daily pipeline.

Steps:
    1. Fetch latest papers for configured categories.
    2. Summarise papers via the LLM.
    3. Generate research ideas.
    4. Store everything in vector memory.
    5. Return a Markdown report.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from langchain_core.messages import HumanMessage, SystemMessage

from config.environment import get_llm
from config.settings import settings
from memory.research_memory import research_memory
from tools.arxiv_tool import arxiv_search

logger = logging.getLogger(__name__)


async def run_arxiv_pipeline(
    categories: list[str] | None = None,
    max_papers: int | None = None,
) -> str:
    """
    Execute the full arXiv fetch → summarise → store pipeline.

    Returns a Markdown report suitable for sending via Telegram.
    """
    cats = categories or settings.arxiv_categories
    limit = max_papers or settings.arxiv_max_papers
    llm = get_llm(temperature=0.3)

    all_papers = []
    for cat in cats:
        query = f"cat:{cat}"
        papers = arxiv_search(query, max_results=limit // len(cats) or 5)
        all_papers.extend(papers)

    if not all_papers:
        return "No new papers found."

    logger.info("arXiv pipeline fetched %d papers", len(all_papers))

    # Build a summary request
    paper_text = "\n".join(
        f"- **{p.title}** ({p.arxiv_id}): {p.short_summary(200)}"
        for p in all_papers
    )

    lang_suffix = ""
    if settings.bot_language == "vi":
        lang_suffix = "\n\nHãy trả lời bằng tiếng Việt."

    messages = [
        SystemMessage(
            content=(
                "You are a research assistant. Summarise the following papers, "
                "identify key themes, and propose 3 novel research ideas."
                + lang_suffix
            )
        ),
        HumanMessage(content=f"Papers found today:\n\n{paper_text}"),
    ]

    response = await llm.ainvoke(messages)
    summary = response.content

    # Store papers in memory
    for p in all_papers:
        research_memory.store_paper(
            arxiv_id=p.arxiv_id,
            title=p.title,
            summary=p.abstract,
            metadata={
                "authors": ", ".join(p.authors),
                "categories": ", ".join(p.categories),
                "published": p.published,
                "pipeline_run": datetime.now(timezone.utc).isoformat(),
            },
        )

    # Store the generated ideas
    research_memory.store_idea(
        idea=summary,
        source="arxiv_pipeline",
        tags=cats,
    )

    stats = research_memory.stats()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    report = (
        f"## 📚 arXiv Daily Report — {now}\n\n"
        f"**Papers fetched:** {len(all_papers)}\n\n"
        f"{summary}\n\n"
        f"**Memory:** {stats}"
    )

    logger.info("arXiv pipeline complete")
    return report
