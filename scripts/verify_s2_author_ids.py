"""
Phase 2: verify candidate S2 author IDs and expand to multi-ID per prof.

S2 fragments famous Chinese researchers across multiple author entities. To
maximise recall, we keep ALL candidate authorIds whose recent papers are
topically consistent with the prof's lab keywords.

Input:  config/s2_author_ids.json   (Phase 1: top 3 candidates per prof)
Output: config/s2_author_ids_verified.json
        prints a review table.

Verification criterion: pull up to 15 recent papers per candidate, count
papers whose title+abstract contains at least one prof keyword. Accept if
hits >= MIN_HITS (default 2). This drops same-name authors in unrelated
fields while keeping legitimate fragmented entities.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
_PHASE1 = _ROOT / "config" / "s2_author_ids.json"
_PROF_LIST = _ROOT / "config" / "prof_list.yaml"
_OUT = _ROOT / "config" / "s2_author_ids_verified.json"

load_dotenv(_ROOT / ".env")

S2 = "https://api.semanticscholar.org/graph/v1"
HEADERS = {"User-Agent": "openclaw-ailab/0.1 (mailto:dangquochiep2908@gmail.com)"}
_API_KEY = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "").strip()
if _API_KEY:
    HEADERS["x-api-key"] = _API_KEY
    print(f"[s2] using API key (***{_API_KEY[-4:]})")
TIMEOUT = 30
_PRE_CALL = 0 if _API_KEY else 2
_BACKOFF = (10, 30, 60, 120)
MIN_HITS = 2  # min keyword hits across recent papers to accept an authorId
SAMPLE_LIMIT = 15
GENERIC = {
    "language model", "NLP", "nlp", "alignment", "reasoning", "retrieval",
    "Tsinghua", "Peking", "PKU", "Nanyang", "NTU", "Singapore", "AIR",
    "Institute for AI Industry Research",
}


def _get(path: str, params: dict):
    url = f"{S2}{path}"
    last = None
    for delay in (_PRE_CALL,) + _BACKOFF:
        if delay:
            time.sleep(delay)
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
        except requests.RequestException as exc:
            last = exc
            continue
        if r.status_code == 429:
            last = "429"
            continue
        if r.status_code == 404:
            return None
        try:
            r.raise_for_status()
        except requests.HTTPError as exc:
            last = exc
            continue
        return r.json()
    print(f"  [warn] retries exhausted on {path} (last={last})")
    return None


def _sample_papers(author_id: str) -> list[dict]:
    data = _get(
        f"/author/{author_id}/papers",
        {"fields": "title,abstract,year,publicationDate,externalIds", "limit": SAMPLE_LIMIT},
    )
    if not data:
        return []
    return data.get("data") or []


def _keyword_hits(papers: list[dict], keywords: list[str]) -> tuple[int, int]:
    """Return (hits, arxiv_count). hits = papers w/ at least one keyword in title+abstract."""
    kws = [k.lower() for k in keywords if k.lower() not in GENERIC and k.strip()]
    hits = 0
    arxiv_count = 0
    for p in papers:
        text = f"{p.get('title') or ''} {p.get('abstract') or ''}".lower()
        if any(k in text for k in kws):
            hits += 1
        ext = p.get("externalIds") or {}
        if ext.get("ArXiv"):
            arxiv_count += 1
    return hits, arxiv_count


def main() -> int:
    if not _PHASE1.exists():
        print(f"missing {_PHASE1} — run build_s2_author_ids.py first")
        return 2

    phase1 = json.loads(_PHASE1.read_text(encoding="utf-8"))

    # Load prof list keywords by name_en
    import yaml
    prof_data = yaml.safe_load(_PROF_LIST.read_text(encoding="utf-8"))
    kw_by_name: dict[str, list[str]] = {}
    for prof in prof_data.get("profs") or []:
        kws = ((prof.get("disambiguation") or {}).get("keywords") or [])
        kw_by_name[prof["name_en"]] = kws

    out = []
    for entry in phase1:
        name = entry.get("name_en", "?")
        cands = entry.get("candidates") or []
        if not cands:
            print(f"\n=== {name}: no candidates ===")
            out.append({"name_en": name, "verified_author_ids": [], "verifications": []})
            continue

        kws = kw_by_name.get(name, [])
        print(f"\n=== {name} (keywords: {kws[:5]}) ===")
        verifications = []
        verified = []
        for c in cands:
            aid = c["authorId"]
            print(f"  candidate {aid} (matched_name={c.get('matched_name','?')}, "
                  f"papers={c.get('paperCount')}, h={c.get('hIndex')}) ...")
            papers = _sample_papers(aid)
            hits, arxiv_count = _keyword_hits(papers, kws)
            verdict = "ACCEPT" if hits >= MIN_HITS else "reject"
            print(f"    sampled={len(papers)}  kw_hits={hits}  arxiv_papers={arxiv_count}  -> {verdict}")
            verifications.append({
                "authorId": aid,
                "sample_size": len(papers),
                "keyword_hits": hits,
                "arxiv_papers_in_sample": arxiv_count,
                "matched_name": c.get("matched_name"),
                "paperCount": c.get("paperCount"),
                "hIndex": c.get("hIndex"),
                "affiliations": c.get("affiliations") or [],
                "verdict": verdict,
            })
            if verdict == "ACCEPT":
                verified.append(aid)

        # If nothing accepted, keep the highest-hits candidate as a fallback (don't lose the prof)
        if not verified and verifications:
            best = max(verifications, key=lambda v: (v["keyword_hits"], v.get("paperCount") or 0))
            print(f"  !! no candidate met threshold; keeping best fallback {best['authorId']} "
                  f"(hits={best['keyword_hits']})")
            verified = [best["authorId"]]

        out.append({
            "name_en": name,
            "verified_author_ids": verified,
            "verifications": verifications,
        })

    _OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {_OUT}")

    # Summary table
    print("\n=== VERIFICATION SUMMARY ===")
    print(f"{'Name':<22} {'#IDs':<5} {'AuthorIDs'}")
    for r in out:
        ids = ",".join(r["verified_author_ids"]) or "(none)"
        print(f"{r['name_en'][:21]:<22} {len(r['verified_author_ids']):<5} {ids}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
