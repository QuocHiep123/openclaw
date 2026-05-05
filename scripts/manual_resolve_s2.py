"""
Targeted lookups for profs that auto-resolution missed or got wrong.

Usage:
  python scripts/manual_resolve_s2.py "Jie Tang ChatGLM" --expected-name "Jie Tang"

Prints the top 5 paper-search hits and their author lists with authorIds, so
you can pick the right person manually. This is the escape hatch when:
- Phase 1 hit 429 too aggressively
- The keyword combo in phase 1 was bad (e.g. unique author at MIT instead of NTU)
- Famous profs are split across multiple S2 entities

After picking IDs, paste them into config/s2_author_ids_verified.json or pass
to merge_into_yaml.py.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

import requests
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")

S2 = "https://api.semanticscholar.org/graph/v1"
HEADERS = {"User-Agent": "openclaw-ailab/0.1 (mailto:dangquochiep2908@gmail.com)"}
_KEY = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "").strip()
if _KEY:
    HEADERS["x-api-key"] = _KEY
TIMEOUT = 30


def _name_matches(candidate: str, target: str) -> bool:
    c_tokens = {t.lower().rstrip(".") for t in candidate.split() if t}
    t_tokens = {t.lower().rstrip(".") for t in target.split() if t}
    if not c_tokens or not t_tokens:
        return False
    for tt in t_tokens:
        if tt in c_tokens or any(ct.startswith(tt) for ct in c_tokens):
            continue
        return False
    return True


def search_with_backoff(query: str, limit: int = 25) -> list[dict]:
    delays = [2 if not _KEY else 0, 10, 30, 60, 120]
    last = None
    for delay in delays:
        if delay:
            time.sleep(delay)
        try:
            r = requests.get(
                f"{S2}/paper/search",
                params={"query": query, "limit": limit,
                        "fields": "title,authors,citationCount,year"},
                headers=HEADERS,
                timeout=TIMEOUT,
            )
        except requests.RequestException as exc:
            last = exc
            continue
        if r.status_code == 429:
            last = "429"
            continue
        if r.status_code == 200:
            return r.json().get("data") or []
        last = f"HTTP {r.status_code}"
    print(f"FAILED after retries (last={last})")
    return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query", help="paper-search query, e.g. 'Jie Tang ChatGLM'")
    ap.add_argument("--expected-name", required=True,
                    help="expected author name to match (e.g. 'Jie Tang')")
    ap.add_argument("--limit", type=int, default=20)
    args = ap.parse_args()

    papers = search_with_backoff(args.query, limit=args.limit)
    if not papers:
        return 1

    print(f"\nTop {len(papers)} papers for query: {args.query!r}\n")
    counter: Counter[str] = Counter()
    name_for_id: dict[str, str] = {}
    for p in papers:
        cite = p.get("citationCount", 0)
        year = p.get("year", "?")
        title = (p.get("title") or "")[:90]
        matched_in_paper = []
        for a in p.get("authors") or []:
            if _name_matches(a.get("name", ""), args.expected_name):
                aid = a.get("authorId") or "?"
                matched_in_paper.append((aid, a.get("name")))
                if a.get("authorId"):
                    counter[a["authorId"]] += 1
                    name_for_id[a["authorId"]] = a.get("name", "")
        if matched_in_paper:
            print(f"  [{year}] cites={cite}  {title}")
            for aid, n in matched_in_paper:
                print(f"      -> {aid}  {n}")

    print("\n=== authorId frequency among matching authors ===")
    for aid, hits in counter.most_common():
        print(f"  {aid}  hits={hits}  name={name_for_id[aid]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
