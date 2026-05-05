"""
NLP_LLM_Daily_Research_Report pipeline.

Flow:
1) Fetch latest arXiv papers
2) LLM relevance filtering
3) Per-paper summary generation
4) Per-paper teaching lesson generation
5) Structured report compilation
6) PDF generation
7) Email delivery via Gmail SMTP
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from langchain_core.messages import HumanMessage, SystemMessage

from config.environment import get_llm
from config.settings import settings
from utils.arxiv_fetch import ArxivPaper, fetch_latest_papers
from utils.email_sender import send_email_with_attachment
from utils.pdf_report_generator import generate_pdf_report
from tools.prof_search_tool import fetch_curated_papers

logger = logging.getLogger(__name__)

_PIPELINE_NAME = "NLP_LLM_Daily_Research_Report"
_DEFAULT_CATEGORIES = ["cs.CL", "cs.AI"]
_DEFAULT_KEYWORDS = [
    "LLM",
    "Large Language Model",
    "transformer",
    "NLP",
    "RAG",
    "alignment",
    "reasoning",
]
_DEFAULT_MAX_PAPERS = 50
_DEFAULT_TOP_RELEVANT = 12
_DEFAULT_SINCE_DAYS = 7
_USE_PROF_CURATED = True  # set False to fall back to keyword-only fetch

_BASE_DIR = Path(__file__).resolve().parent.parent
_PROMPTS_DIR = _BASE_DIR / "prompts"
_REPORTS_DIR = _BASE_DIR / "data" / "reports"


@dataclass
class PaperInsight:
    """Final enriched representation of a paper in the generated report."""

    paper: ArxivPaper
    summary: str
    lesson: str


def _is_quota_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return "resource_exhausted" in text or "quota" in text or "429" in text


def _keyword_relevance_score(paper: ArxivPaper, keywords: list[str]) -> int:
    haystack = f"{paper.title} {paper.abstract} {' '.join(paper.categories)}".lower()
    return sum(1 for kw in keywords if kw.lower() in haystack)


def _fallback_summary(paper: ArxivPaper) -> str:
    abstract = paper.abstract.strip()
    if len(abstract) > 900:
        abstract = abstract[:900] + "..."
    return (
        f"Title: {paper.title}\n"
        f"Authors: {', '.join(paper.authors)}\n"
        "Problem: The paper addresses a challenge in NLP/LLM research based on the provided abstract.\n"
        f"Key Idea: {abstract}\n"
        "Method: See abstract and linked PDF for detailed architecture/training setup.\n"
        "Main Results: Refer to the paper PDF for exact reported metrics.\n"
        "Limitations: Not fully inferable from abstract alone; full paper review recommended.\n"
        "Future Directions: Extend experiments, improve robustness, and validate on broader NLP tasks."
    )


def _fallback_lesson(paper: ArxivPaper) -> str:
    return (
        "Intuition:\n"
        f"- This work explores an NLP/LLM problem centered on: {paper.title}.\n\n"
        "Architecture:\n"
        "- The abstract indicates a model/system design for language understanding or generation.\n"
        "- Review the PDF for exact components and training pipeline.\n\n"
        "Why it matters for LLM research:\n"
        "- It contributes evidence or ideas relevant to modern LLM capabilities and deployment.\n\n"
        "3 research ideas inspired by the paper:\n"
        "1) Reproduce the method on a newer open LLM and compare efficiency-quality tradeoffs.\n"
        "2) Test robustness under long-context and domain-shift settings.\n"
        "3) Integrate retrieval/tool-usage and evaluate grounded reasoning quality."
    )


def _read_prompt(filename: str) -> str:
    path = _PROMPTS_DIR / filename
    return path.read_text(encoding="utf-8")


def _extract_json_block(text: str) -> dict[str, Any]:
    """Extract JSON object from plain/fenced model output."""
    cleaned = text.strip()

    fenced = re.search(r"```json\s*(\{.*?\})\s*```", cleaned, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        cleaned = fenced.group(1)

    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").strip()

    return json.loads(cleaned)


def _chunks(items: list[Any], size: int) -> Iterable[list[Any]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


async def _filter_relevant_papers(
    papers: list[ArxivPaper],
    top_k: int,
) -> list[ArxivPaper]:
    """Use LLM relevance scoring to keep top NLP/LLM papers."""
    if not papers:
        return []

    llm = get_llm(temperature=0.0)
    system_prompt = _read_prompt("filter_papers.md")

    all_scored: dict[str, float] = {}

    for batch in _chunks(papers, 20):
        serialized = []
        for idx, paper in enumerate(batch, start=1):
            serialized.append(
                {
                    "index": idx,
                    "arxiv_id": paper.arxiv_id,
                    "title": paper.title,
                    "authors": paper.authors[:8],
                    "abstract": paper.abstract,
                    "categories": paper.categories,
                    "published_date": paper.published_date,
                }
            )

        user_prompt = (
            "Score each paper relevance for NLP/LLM research and return strict JSON only.\n\n"
            "JSON format:\n"
            "{\n"
            "  \"papers\": [\n"
            "    {\"arxiv_id\": \"...\", \"score\": 0-10, \"reason\": \"...\"}\n"
            "  ]\n"
            "}\n\n"
            f"Candidates:\n{json.dumps(serialized, ensure_ascii=False)}"
        )

        try:
            response = await llm.ainvoke(
                [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_prompt),
                ]
            )

            data = _extract_json_block(str(response.content))
            for row in data.get("papers", []):
                try:
                    pid = str(row["arxiv_id"]).strip()
                    score = float(row.get("score", 0))
                    if pid:
                        all_scored[pid] = max(all_scored.get(pid, 0.0), score)
                except Exception:
                    continue
        except Exception as exc:
            logger.warning("Filter batch failed, using keyword fallback for this batch: %s", exc)
            for paper in batch:
                all_scored[paper.arxiv_id] = max(
                    all_scored.get(paper.arxiv_id, 0.0),
                    float(_keyword_relevance_score(paper, _DEFAULT_KEYWORDS)),
                )

    ranked = sorted(papers, key=lambda p: all_scored.get(p.arxiv_id, 0.0), reverse=True)

    # Keep only strongly related papers (score >= 6), fallback to top_k if sparse.
    strong = [p for p in ranked if all_scored.get(p.arxiv_id, 0.0) >= 6.0]
    if len(strong) >= min(3, top_k):
        return strong[:top_k]

    return ranked[:top_k]


async def _summarize_paper(paper: ArxivPaper) -> str:
    llm = get_llm(temperature=0.2)
    system_prompt = _read_prompt("summarize_paper.md")
    user_prompt = (
        "Summarize the paper using the exact template in the system prompt.\n\n"
        f"Title: {paper.title}\n"
        f"Authors: {', '.join(paper.authors)}\n"
        f"Published: {paper.published_date}\n"
        f"PDF: {paper.pdf_link}\n"
        f"Abstract: {paper.abstract}\n"
    )
    response = await llm.ainvoke(
        [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
    )
    return str(response.content).strip()


async def _teach_paper(paper: ArxivPaper, summary: str) -> str:
    llm = get_llm(temperature=0.3)
    system_prompt = _read_prompt("teach_paper.md")
    user_prompt = (
        "Teach this paper for a graduate data science student.\n\n"
        f"Title: {paper.title}\n"
        f"Authors: {', '.join(paper.authors)}\n"
        f"Abstract: {paper.abstract}\n\n"
        f"Current Summary:\n{summary}\n"
    )
    response = await llm.ainvoke(
        [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
    )
    return str(response.content).strip()


def _build_report(date_str: str, insights: list[PaperInsight]) -> str:
    lines = [
        "# Daily NLP & LLM Research Digest",
        "",
        f"Date: {date_str}",
        "",
    ]

    for idx, insight in enumerate(insights, start=1):
        paper = insight.paper
        lines.extend(
            [
                f"## Paper {idx}",
                f"Title: {paper.title}",
                f"Authors: {', '.join(paper.authors)}",
                f"arXiv ID: {paper.arxiv_id}",
                f"Published Date: {paper.published_date}",
                f"PDF: {paper.pdf_link}",
                "",
                "### Summary",
                insight.summary,
                "",
                "### Key Idea",
                "Included in the summary section above.",
                "",
                "### Research Lesson",
                insight.lesson,
                "",
                "### Research Ideas",
                "Included in the research lesson section above.",
                "",
            ]
        )

    if not insights:
        lines.append("No relevant papers passed filtering today.")

    return "\n".join(lines).strip() + "\n"


async def run_nlp_llm_daily_research_report(
    max_papers: int = _DEFAULT_MAX_PAPERS,
    top_relevant_papers: int = _DEFAULT_TOP_RELEVANT,
    categories: list[str] | None = None,
    keywords: list[str] | None = None,
    email_target: str | None = None,
) -> dict[str, Any]:
    """
    Execute the full NLP/LLM daily research report pipeline.

    Returns metadata with generated report path and selected paper count.
    """
    logger.info("[%s] started", _PIPELINE_NAME)

    cats = categories or _DEFAULT_CATEGORIES
    kws = keywords or _DEFAULT_KEYWORDS
    recipient = email_target or settings.research_report_recipient

    if _USE_PROF_CURATED:
        papers = fetch_curated_papers(since_days=_DEFAULT_SINCE_DAYS)
        logger.info("[%s] prof-curated papers=%d", _PIPELINE_NAME, len(papers))
        if not papers:
            logger.warning("[%s] prof curated empty, falling back to keyword fetch", _PIPELINE_NAME)
            papers = fetch_latest_papers(categories=cats, keywords=kws, max_papers=max_papers)
    else:
        papers = fetch_latest_papers(categories=cats, keywords=kws, max_papers=max_papers)
    logger.info("[%s] fetched papers=%d", _PIPELINE_NAME, len(papers))

    relevant = await _filter_relevant_papers(papers, top_k=top_relevant_papers)
    logger.info("[%s] relevant papers=%d", _PIPELINE_NAME, len(relevant))

    insights: list[PaperInsight] = []
    llm_available = True
    for paper in relevant:
        if llm_available:
            try:
                summary = await _summarize_paper(paper)
                lesson = await _teach_paper(paper, summary)
            except Exception as exc:
                if _is_quota_error(exc):
                    llm_available = False
                    logger.warning("LLM quota exhausted, switching to fallback mode: %s", exc)
                else:
                    logger.warning("LLM paper processing failed, using fallback for this paper: %s", exc)
                summary = _fallback_summary(paper)
                lesson = _fallback_lesson(paper)
        else:
            summary = _fallback_summary(paper)
            lesson = _fallback_lesson(paper)

        insights.append(PaperInsight(paper=paper, summary=summary, lesson=lesson))

    now_utc = datetime.now(timezone.utc)
    date_compact = now_utc.strftime("%Y_%m_%d")
    date_display = now_utc.strftime("%Y-%m-%d")

    markdown_report = _build_report(date_display, insights)
    pdf_name = f"NLP_LLM_Research_Report_{date_compact}.pdf"
    pdf_path = _REPORTS_DIR / pdf_name
    generate_pdf_report(markdown_report, pdf_path)

    id_lines = "\n".join(f"  - {p.paper.arxiv_id}: {p.paper.title}" for p in insights)
    body = (
        "Attached is today's automated research digest for NLP and LLM papers.\n\n"
        "To get a full Vietnamese translation of any paper, send this on Telegram:\n"
        "  /translate <arxiv_id>\n\n"
        f"Today's papers ({len(insights)}):\n"
        f"{id_lines}\n"
    )
    send_email_with_attachment(
        to_email=recipient,
        subject="Daily NLP & LLM Research Report",
        body=body,
        attachment_path=pdf_path,
        sender_email=settings.gmail_address or None,
        app_password=settings.gmail_app_password or None,
    )

    logger.info(
        "[%s] success | pdf=%s | sent_to=%s | papers=%d",
        _PIPELINE_NAME,
        pdf_path,
        recipient,
        len(insights),
    )

    return {
        "pipeline": _PIPELINE_NAME,
        "status": "success",
        "pdf_path": str(pdf_path),
        "recipient": recipient,
        "fetched_papers": len(papers),
        "selected_papers": len(insights),
    }
