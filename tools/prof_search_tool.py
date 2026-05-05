"""
Prof-curated paper retrieval (Semantic Scholar primary, arXiv fallback).

Loads:
- config/prof_list.yaml         — prof metadata, keywords, reject_keywords, etc.
- config/s2_author_ids_verified.json — verified S2 authorIds per prof (1..N)

For each prof:
  if verified S2 author IDs exist:
      query S2 /author/{id}/papers for each, dedupe by arxiv_id
  else (no S2 IDs available):
      fall back to arxiv au:"Name" + heuristic disambiguation (legacy behaviour)

After per-prof fetching, apply optional reject_keywords filter (drops papers
whose title/abstract contains any reject keyword).

The downstream LLM relevance filter in nlp_llm_research_pipeline.py is the
second-pass safety net.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import arxiv
import yaml

from utils.arxiv_fetch import ArxivPaper
from tools.s2_client import fetch_papers_for_authors

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_PROF_LIST_PATH = _PROJECT_ROOT / "config" / "prof_list.yaml"
_S2_VERIFIED_PATH = _PROJECT_ROOT / "config" / "s2_author_ids_verified.json"
_DEFAULT_CATS = ("cs.CL", "cs.AI", "cs.LG")


@dataclass
class ProfEntry:
    name_en: str
    name_cn: str | None
    affiliation: str
    arxiv_au_query: str
    coauthors: list[str]
    keywords: list[str]
    reject_keywords: list[str]
    topics: list[str]
    s2_author_ids: list[str]


def _load_s2_ids() -> dict[str, list[str]]:
    """Map name_en -> verified author IDs. Empty dict if file missing."""
    if not _S2_VERIFIED_PATH.exists():
        logger.warning("s2_author_ids_verified.json not found; all profs will use arxiv fallback")
        return {}
    try:
        data = json.loads(_S2_VERIFIED_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("failed to parse s2_author_ids_verified.json: %s", exc)
        return {}
    return {
        r["name_en"]: list(r.get("verified_author_ids") or [])
        for r in data
        if r.get("name_en")
    }


def _load_prof_list() -> tuple[list[ProfEntry], dict]:
    if not _PROF_LIST_PATH.exists():
        raise FileNotFoundError(f"{_PROF_LIST_PATH} not found")

    with _PROF_LIST_PATH.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    s2_ids = _load_s2_ids()

    profs: list[ProfEntry] = []
    for raw in data.get("profs") or []:
        dis = raw.get("disambiguation") or {}
        name_en = raw["name_en"]
        profs.append(
            ProfEntry(
                name_en=name_en,
                name_cn=raw.get("name_cn"),
                affiliation=raw["affiliation"],
                arxiv_au_query=raw["arxiv_au_query"],
                coauthors=dis.get("coauthors") or [],
                keywords=dis.get("keywords") or [],
                reject_keywords=dis.get("reject_keywords") or [],
                topics=raw.get("topics") or [],
                s2_author_ids=s2_ids.get(name_en, []),
            )
        )
    return profs, (data.get("fallback") or {})


def _passes_reject_filter(paper: ArxivPaper, reject_keywords: list[str]) -> bool:
    if not reject_keywords:
        return True
    haystack = f"{paper.title} {paper.abstract}".lower()
    return not any(rk.lower() in haystack for rk in reject_keywords)


# ---- arxiv fallback (legacy heuristic) ------------------------------------

def _date_range_clause(since_days: int) -> str:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=since_days)
    return f"submittedDate:[{start.strftime('%Y%m%d')}0000 TO {end.strftime('%Y%m%d')}2359]"


def _category_clause(cats: Iterable[str]) -> str:
    return " OR ".join(f"cat:{c}" for c in cats)


def _arxiv_matches_prof(paper, prof: ProfEntry) -> bool:
    haystack_text = f"{paper.title} {paper.summary}".lower()
    author_names = {a.name.lower() for a in paper.authors}

    for rk in prof.reject_keywords:
        if rk.lower() in haystack_text:
            return False
    for co in prof.coauthors:
        if any(co.lower() in name for name in author_names):
            return True
    for kw in prof.keywords:
        if kw.lower() in haystack_text:
            return True
    return False


def _arxiv_to_paper(result) -> ArxivPaper:
    raw_id = result.entry_id.split("/")[-1]
    # Normalise version suffix to align with S2 IDs (avoids dup like 2604.27393 vs 2604.27393v1)
    arxiv_id = re.sub(r"v\d+$", "", raw_id)
    return ArxivPaper(
        arxiv_id=arxiv_id,
        title=result.title.strip(),
        authors=[a.name for a in result.authors],
        abstract=result.summary.replace("\n", " ").strip(),
        pdf_link=f"https://arxiv.org/pdf/{arxiv_id}",
        published_date=result.published.strftime("%Y-%m-%d"),
        categories=list(result.categories),
    )


def _arxiv_search(query: str, max_results: int) -> list:
    client = arxiv.Client()
    search = arxiv.Search(
        query=query,
        max_results=max_results,
        sort_by=arxiv.SortCriterion.SubmittedDate,
        sort_order=arxiv.SortOrder.Descending,
    )
    return list(client.results(search))


def _fetch_via_arxiv_fallback(
    prof: ProfEntry,
    since_days: int,
    max_results: int,
    cats: Iterable[str],
) -> list[ArxivPaper]:
    """Legacy heuristic: arxiv au:"Name" + coauthor/keyword filter."""
    cat_clause = _category_clause(cats)
    date_clause = _date_range_clause(since_days)
    query = f"({prof.arxiv_au_query}) AND ({cat_clause}) AND {date_clause}"
    try:
        raw = _arxiv_search(query, max_results)
    except Exception as exc:
        logger.warning("arxiv fallback failed for %s: %s", prof.name_en, exc)
        return []

    out: list[ArxivPaper] = []
    for r in raw:
        if not _arxiv_matches_prof(r, prof):
            continue
        out.append(_arxiv_to_paper(r))
    logger.info(
        "[prof_search] %s: arxiv-fallback raw=%d kept=%d",
        prof.name_en, len(raw), len(out),
    )
    return out


# ---- main fetch -----------------------------------------------------------

def fetch_prof_papers(
    since_days: int = 7,
    max_per_prof: int = 20,
    cats: Iterable[str] = _DEFAULT_CATS,
) -> list[ArxivPaper]:
    """Fetch recent papers from each prof. S2 primary, arxiv fallback per-prof."""
    profs, _ = _load_prof_list()

    seen_ids: set[str] = set()
    papers: list[ArxivPaper] = []

    for prof in profs:
        if prof.s2_author_ids:
            kept = fetch_papers_for_authors(
                prof.s2_author_ids,
                since_days=since_days,
                max_per_author=max_per_prof,
            )
            source = f"s2[{len(prof.s2_author_ids)}ids]"
        else:
            kept = _fetch_via_arxiv_fallback(prof, since_days, max_per_prof * 2, cats)
            source = "arxiv-fallback"

        new_for_prof = 0
        for p in kept:
            if p.arxiv_id in seen_ids:
                continue
            if not _passes_reject_filter(p, prof.reject_keywords):
                continue
            seen_ids.add(p.arxiv_id)
            papers.append(p)
            new_for_prof += 1

        logger.info(
            "[prof_search] %s (%s): kept=%d new=%d",
            prof.name_en, source, len(kept), new_for_prof,
        )

    return papers


def fetch_topic_fallback_papers(
    since_days: int = 7,
    cats: Iterable[str] = _DEFAULT_CATS,
) -> list[ArxivPaper]:
    """Topic keyword fallback (arxiv keyword search) for top venues / focus areas."""
    _, fallback = _load_prof_list()
    if not fallback.get("enabled"):
        return []

    keywords = fallback.get("keywords") or []
    if not keywords:
        return []

    max_papers = int(fallback.get("max_papers") or 15)
    cat_clause = _category_clause(cats)
    date_clause = _date_range_clause(since_days)
    kw_clause = " OR ".join(f'(ti:"{k}" OR abs:"{k}")' for k in keywords)
    query = f"({cat_clause}) AND ({kw_clause}) AND {date_clause}"

    try:
        raw = _arxiv_search(query, max_papers)
    except Exception as exc:
        logger.warning("topic fallback search failed: %s", exc)
        return []

    papers: list[ArxivPaper] = []
    seen: set[str] = set()
    for r in raw:
        arxiv_id = r.entry_id.split("/")[-1]
        if arxiv_id in seen:
            continue
        seen.add(arxiv_id)
        papers.append(_arxiv_to_paper(r))
    logger.info("[prof_search] topic-fallback kept=%d", len(papers))
    return papers


def fetch_curated_papers(since_days: int = 7) -> list[ArxivPaper]:
    """Combined prof-curated + topic fallback. Deduped, sorted by date desc."""
    prof_papers = fetch_prof_papers(since_days=since_days)
    fallback_papers = fetch_topic_fallback_papers(since_days=since_days)

    seen = {p.arxiv_id for p in prof_papers}
    merged = list(prof_papers)
    for p in fallback_papers:
        if p.arxiv_id not in seen:
            seen.add(p.arxiv_id)
            merged.append(p)

    merged.sort(
        key=lambda p: datetime.strptime(p.published_date, "%Y-%m-%d"),
        reverse=True,
    )
    return merged
