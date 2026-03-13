"""
Web search tool using DuckDuckGo.

Returns a list of search-result dicts with title, url, and snippet.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import List

from duckduckgo_search import DDGS


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str

    def to_dict(self) -> dict:
        return asdict(self)


def web_search(query: str, max_results: int = 5) -> List[SearchResult]:
    """
    Search the web via DuckDuckGo.

    Args:
        query: Free-text search query.
        max_results: Maximum number of results to return.

    Returns:
        List of SearchResult instances.
    """
    results: List[SearchResult] = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, max_results=max_results):
            results.append(
                SearchResult(
                    title=r.get("title", ""),
                    url=r.get("href", ""),
                    snippet=r.get("body", ""),
                )
            )
    return results
