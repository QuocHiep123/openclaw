"""
arXiv search & paper retrieval tool.

Uses the `arxiv` library to query the arXiv API, download abstracts,
and return structured paper metadata.
"""
from __future__ import annotations

import textwrap
from dataclasses import dataclass, field, asdict
from typing import List, Optional

import arxiv


@dataclass
class PaperInfo:
    """Lightweight representation of an arXiv paper."""
    title: str
    authors: List[str]
    abstract: str
    arxiv_id: str
    categories: List[str]
    published: str
    pdf_url: str

    def short_summary(self, max_chars: int = 300) -> str:
        return textwrap.shorten(self.abstract, width=max_chars, placeholder="…")

    def to_dict(self) -> dict:
        return asdict(self)


def arxiv_search(
    query: str,
    max_results: int = 10,
    sort_by: str = "submittedDate",
) -> List[PaperInfo]:
    """
    Search arXiv for papers matching *query*.

    Args:
        query: Free-text or arXiv query string (e.g. "transformer attention").
        max_results: Maximum number of papers to return.
        sort_by: Sort criterion — "submittedDate" or "relevance".

    Returns:
        List of PaperInfo dataclass instances.
    """
    sort_criterion = (
        arxiv.SortCriterion.SubmittedDate
        if sort_by == "submittedDate"
        else arxiv.SortCriterion.Relevance
    )

    client = arxiv.Client()
    search = arxiv.Search(
        query=query,
        max_results=max_results,
        sort_by=sort_criterion,
    )

    papers: List[PaperInfo] = []
    for result in client.results(search):
        papers.append(
            PaperInfo(
                title=result.title,
                authors=[a.name for a in result.authors[:5]],
                abstract=result.summary.replace("\n", " "),
                arxiv_id=result.entry_id.split("/")[-1],
                categories=list(result.categories),
                published=result.published.strftime("%Y-%m-%d"),
                pdf_url=result.pdf_url,
            )
        )
    return papers


def arxiv_fetch_by_id(paper_id: str) -> Optional[PaperInfo]:
    """Fetch a single paper by its arXiv ID."""
    client = arxiv.Client()
    search = arxiv.Search(id_list=[paper_id])
    for result in client.results(search):
        return PaperInfo(
            title=result.title,
            authors=[a.name for a in result.authors[:5]],
            abstract=result.summary.replace("\n", " "),
            arxiv_id=result.entry_id.split("/")[-1],
            categories=list(result.categories),
            published=result.published.strftime("%Y-%m-%d"),
            pdf_url=result.pdf_url,
        )
    return None
