"""
Semantic Scholar API client for prof-curated paper retrieval.

Wraps `GET /graph/v1/author/{author_id}/papers` with:
- retry/backoff on 429 (S2 unauthenticated rate limit is harsh)
- optional SEMANTIC_SCHOLAR_API_KEY for higher quota
- arxiv_id extraction via externalIds.ArXiv (papers without arxiv ID are dropped)
- conversion to the existing ArxivPaper dataclass so the downstream pipeline
  is unchanged
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

import requests

from utils.arxiv_fetch import ArxivPaper

logger = logging.getLogger(__name__)

_S2_BASE = "https://api.semanticscholar.org/graph/v1"
_HEADERS: dict[str, str] = {
    "User-Agent": "openclaw-ailab/0.1 (mailto:dangquochiep2908@gmail.com)",
}
_API_KEY = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "").strip()
if _API_KEY:
    _HEADERS["x-api-key"] = _API_KEY

_PRE_CALL_DELAY = 0.0 if _API_KEY else 1.5
_TIMEOUT = 30
_BACKOFF_SECONDS = (5, 15, 45, 90)

_PAPER_FIELDS = ",".join([
    "title",
    "abstract",
    "publicationDate",
    "year",
    "externalIds",
    "authors.name",
    "venue",
    "fieldsOfStudy",
])


def _get_with_retry(path: str, params: dict) -> Optional[dict]:
    """Return JSON or None if all retries exhausted."""
    url = f"{_S2_BASE}{path}"
    last_status = None
    for delay in (_PRE_CALL_DELAY,) + _BACKOFF_SECONDS:
        if delay:
            time.sleep(delay)
        try:
            r = requests.get(url, params=params, headers=_HEADERS, timeout=_TIMEOUT)
        except requests.RequestException as exc:
            logger.warning("[s2] request error on %s: %s", path, exc)
            continue
        if r.status_code == 429:
            last_status = 429
            continue
        if r.status_code == 404:
            logger.warning("[s2] 404 on %s", path)
            return None
        try:
            r.raise_for_status()
        except requests.HTTPError as exc:
            last_status = r.status_code
            logger.warning("[s2] HTTP %d on %s: %s", r.status_code, path, exc)
            continue
        return r.json()
    logger.warning("[s2] retries exhausted on %s (last_status=%s)", path, last_status)
    return None


def _extract_arxiv_id(p: dict) -> Optional[str]:
    ext = p.get("externalIds") or {}
    arxiv = ext.get("ArXiv")
    if not arxiv:
        return None
    aid = str(arxiv).strip()
    # Normalise: strip trailing version suffix (e.g. "2604.27393v1" -> "2604.27393")
    # so dedup across S2 fragments works reliably.
    import re as _re
    return _re.sub(r"v\d+$", "", aid)


def _publication_date(p: dict) -> Optional[datetime]:
    pub = p.get("publicationDate")
    if pub:
        try:
            return datetime.strptime(pub, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    year = p.get("year")
    if year:
        try:
            return datetime(int(year), 1, 1, tzinfo=timezone.utc)
        except (TypeError, ValueError):
            pass
    return None


def _to_arxiv_paper(p: dict) -> Optional[ArxivPaper]:
    arxiv_id = _extract_arxiv_id(p)
    if not arxiv_id:
        return None
    pub_dt = _publication_date(p)
    pub_date = pub_dt.strftime("%Y-%m-%d") if pub_dt else "1970-01-01"
    abstract = (p.get("abstract") or "").replace("\n", " ").strip()
    title = (p.get("title") or "").strip()
    if not title:
        return None
    authors = [(a.get("name") or "").strip() for a in (p.get("authors") or [])]
    authors = [a for a in authors if a]
    fos = p.get("fieldsOfStudy") or []
    return ArxivPaper(
        arxiv_id=arxiv_id,
        title=title,
        authors=authors,
        abstract=abstract,
        pdf_link=f"https://arxiv.org/pdf/{arxiv_id}",
        published_date=pub_date,
        categories=[str(f) for f in fos],
    )


def fetch_author_papers(
    author_id: str,
    since_days: int = 7,
    max_papers: int = 50,
) -> list[ArxivPaper]:
    """
    Fetch recent papers for a single S2 author_id, restricted to those with an
    arXiv ID in externalIds, published within `since_days`.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)

    # S2 returns papers ordered by recency when no sort is specified for /papers.
    # We over-fetch then filter client-side by publicationDate.
    data = _get_with_retry(
        f"/author/{author_id}/papers",
        {"fields": _PAPER_FIELDS, "limit": min(max_papers * 4, 1000), "offset": 0},
    )
    if not data:
        return []

    papers: list[ArxivPaper] = []
    for raw in data.get("data") or []:
        pub_dt = _publication_date(raw)
        if pub_dt is None or pub_dt < cutoff:
            continue
        ap = _to_arxiv_paper(raw)
        if ap is None:
            continue
        papers.append(ap)
        if len(papers) >= max_papers:
            break

    logger.info(
        "[s2] author=%s recent_with_arxiv=%d (since_days=%d)",
        author_id, len(papers), since_days,
    )
    return papers


def fetch_papers_for_authors(
    author_ids: Iterable[str],
    since_days: int = 7,
    max_per_author: int = 50,
) -> list[ArxivPaper]:
    """Fetch + dedupe across multiple authors."""
    seen: set[str] = set()
    out: list[ArxivPaper] = []
    for aid in author_ids:
        for p in fetch_author_papers(aid, since_days=since_days, max_papers=max_per_author):
            if p.arxiv_id in seen:
                continue
            seen.add(p.arxiv_id)
            out.append(p)
    return out
