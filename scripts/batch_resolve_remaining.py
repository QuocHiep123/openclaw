"""Batch-resolve the 6 profs that phase 1 missed or got wrong.

Each prof: paper-search with targeted query, find authorIds matching name,
print frequency table. Output appended to config/manual_resolutions.json.
"""
from __future__ import annotations

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
INITIAL_PAUSE = 120  # generous wait for rate-limit window after prior heavy use
INTER_QUERY = 30     # generous gap between profs

TARGETS = [
    ("Zhiyuan Liu",   "Zhiyuan Liu OpenBMB MiniCPM"),
    ("Xu Han",        "Xu Han Tsinghua relation extraction language model"),
    ("Bowen Zhou",    "Bowen Zhou multimodal alignment foundation model"),
    ("Yanyan Lan",    "Yanyan Lan information retrieval CAS"),
    ("Zongqing Lu",   "Zongqing Lu cooperative multi-agent reinforcement"),
]


def name_match(cand: str, target: str) -> bool:
    c = {t.lower().rstrip(".") for t in cand.split() if t}
    t = {tt.lower().rstrip(".") for tt in target.split() if tt}
    if not c or not t:
        return False
    for tt in t:
        if tt in c or any(ct.startswith(tt) for ct in c):
            continue
        return False
    return True


def search(query: str, limit: int = 25) -> list[dict]:
    last = None
    for delay in [3, 15, 45, 90, 180]:
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
    print(f"  FAIL after retries (last={last})")
    return []


def main() -> int:
    print(f"Initial pause {INITIAL_PAUSE}s for rate-limit window to clear...")
    time.sleep(INITIAL_PAUSE)

    out_path = _ROOT / "config" / "manual_resolutions.json"
    results = []

    for i, (name, query) in enumerate(TARGETS, 1):
        if i > 1:
            print(f"\nInter-prof pause {INTER_QUERY}s...")
            time.sleep(INTER_QUERY)
        print(f"\n[{i}/{len(TARGETS)}] {name}  query={query!r}")
        papers = search(query, limit=20)
        if not papers:
            results.append({"name_en": name, "query": query, "candidates": []})
            continue

        counter: Counter[str] = Counter()
        cite_for_id: dict[str, int] = {}
        name_for_id: dict[str, str] = {}
        sample_titles: dict[str, list[str]] = {}
        for p in papers:
            title = (p.get("title") or "")[:80]
            cite = p.get("citationCount", 0)
            for a in p.get("authors") or []:
                if not name_match(a.get("name", ""), name):
                    continue
                aid = a.get("authorId")
                if not aid:
                    continue
                counter[aid] += 1
                cite_for_id[aid] = max(cite_for_id.get(aid, 0), cite)
                name_for_id[aid] = a.get("name", "")
                sample_titles.setdefault(aid, []).append(title)

        cands = []
        for aid, hits in counter.most_common(5):
            cands.append({
                "authorId": aid,
                "name": name_for_id[aid],
                "hits_in_top20": hits,
                "max_citations_in_sample": cite_for_id[aid],
                "sample_titles": sample_titles[aid][:3],
            })
            print(f"  -> {aid}  hits={hits}  max_cites={cite_for_id[aid]}  name={name_for_id[aid]}")
            for t in sample_titles[aid][:2]:
                print(f"       \"{t}\"")

        results.append({"name_en": name, "query": query, "candidates": cands})

    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {out_path}")

    print("\n=== SUMMARY ===")
    for r in results:
        c = r.get("candidates") or []
        if c:
            top = c[0]
            print(f"  {r['name_en']:<22} {top['authorId']:<12} hits={top['hits_in_top20']}  "
                  f"max_cites={top['max_citations_in_sample']}")
        else:
            print(f"  {r['name_en']:<22} <UNRESOLVED>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
