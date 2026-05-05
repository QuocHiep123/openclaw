"""
Utilities for fetching recent arXiv papers for NLP/LLM research.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Iterable, List

import arxiv


@dataclass
class ArxivPaper:
    """Structured arXiv paper metadata used in the daily report pipeline."""

    arxiv_id: str
    title: str
    authors: List[str]
    abstract: str
    pdf_link: str
    published_date: str
    categories: List[str]

    def to_dict(self) -> dict:
        return asdict(self)


def _build_query(categories: Iterable[str], keywords: Iterable[str]) -> str:
    category_clause = " OR ".join(f"cat:{cat.strip()}" for cat in categories if cat.strip())
    keyword_clause = " OR ".join(f'all:"{kw.strip()}"' for kw in keywords if kw.strip())

    if category_clause and keyword_clause:
        return f"({category_clause}) AND ({keyword_clause})"
    if category_clause:
        return category_clause
    if keyword_clause:
        return keyword_clause
    return "cat:cs.CL OR cat:cs.AI"


def fetch_latest_papers(
    categories: List[str],
    keywords: List[str],
    max_papers: int = 50,
) -> List[ArxivPaper]:
    """
    Fetch newest papers from arXiv constrained by categories + keywords.

    Returns up to max_papers unique papers sorted by submitted date desc.
    """
    query = _build_query(categories, keywords)

    search = arxiv.Search(
        query=query,
        max_results=max_papers,
        sort_by=arxiv.SortCriterion.SubmittedDate,
        sort_order=arxiv.SortOrder.Descending,
    )
    client = arxiv.Client()

    papers: List[ArxivPaper] = []
    seen_ids: set[str] = set()

    for result in client.results(search):
        # Normalise version suffix so dedup aligns with S2-sourced IDs
        arxiv_id = re.sub(r"v\d+$", "", result.entry_id.split("/")[-1])
        if arxiv_id in seen_ids:
            continue

        seen_ids.add(arxiv_id)
        papers.append(
            ArxivPaper(
                arxiv_id=arxiv_id,
                title=result.title.strip(),
                authors=[a.name for a in result.authors],
                abstract=result.summary.replace("\n", " ").strip(),
                pdf_link=f"https://arxiv.org/pdf/{arxiv_id}",
                published_date=result.published.strftime("%Y-%m-%d"),
                categories=list(result.categories),
            )
        )

        if len(papers) >= max_papers:
            break

    papers.sort(key=lambda p: datetime.strptime(p.published_date, "%Y-%m-%d"), reverse=True)
    return papers
