"""
Resolve Semantic Scholar author IDs for each prof in config/prof_list.yaml.

Strategy: S2's /author/search has poor relevance for common names. Instead, we
search /paper/search with `prof_name + first lab keyword`, take top 25 papers,
and pick the authorId that appears most often among authors whose name matches
the prof. The recurring authorId across multiple recent papers is reliably the
target prof.

Output:
- config/s2_author_ids.json — full mapping with sanity-check stats per prof
- prints a review table; user confirms before merging into prof_list.yaml.
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

import requests
import yaml
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
_PROF_LIST = _ROOT / "config" / "prof_list.yaml"
_OUT_JSON = _ROOT / "config" / "s2_author_ids.json"

load_dotenv(_ROOT / ".env")

S2 = "https://api.semanticscholar.org/graph/v1"
HEADERS = {"User-Agent": "openclaw-ailab/0.1 (mailto:dangquochiep2908@gmail.com)"}
_API_KEY = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "").strip()
if _API_KEY:
    HEADERS["x-api-key"] = _API_KEY
    print(f"[s2] using API key (***{_API_KEY[-4:]})")
else:
    print("[s2] no API key — will pace slowly to avoid 429")
TIMEOUT = 30

# Retry with backoff on 429. S2 unauthenticated rate limit is very strict on
# paper/search; backoff 10s, 30s, 60s, 120s.
_BACKOFF_SECONDS = [10, 30, 60, 120]
# Floor delay before every request when no API key (S2 unauthenticated ~1 req/sec)
_PRE_CALL_DELAY = 0 if _API_KEY else 2


def _get_with_retry(url: str, params: dict) -> dict:
    last_exc = None
    for delay in [_PRE_CALL_DELAY] + _BACKOFF_SECONDS:
        if delay:
            time.sleep(delay)
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
            if r.status_code == 429:
                last_exc = requests.HTTPError(f"429 rate limit on {url}")
                continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException as exc:
            last_exc = exc
            continue
    raise last_exc or RuntimeError("retry exhausted")


def _name_matches(candidate: str, target: str) -> bool:
    """Loose match: same set of name tokens (handles 'Yang Liu' vs 'Y. Liu', etc.)."""
    c_tokens = {t.lower().rstrip(".") for t in candidate.split() if t}
    t_tokens = {t.lower().rstrip(".") for t in target.split() if t}
    if not c_tokens or not t_tokens:
        return False
    # All target tokens (or their initials) must be in candidate
    for tt in t_tokens:
        if tt in c_tokens:
            continue
        # initial match: 'z' matches 'zhiyuan'
        if any(ct.startswith(tt) for ct in c_tokens):
            continue
        return False
    return True


def _search_papers(query: str, limit: int = 25) -> list[dict]:
    data = _get_with_retry(
        f"{S2}/paper/search",
        {
            "query": query,
            "limit": limit,
            "fields": "title,authors,citationCount,year",
        },
    )
    return data.get("data", [])


def _get_author_details(author_id: str) -> dict:
    return _get_with_retry(
        f"{S2}/author/{author_id}",
        {"fields": "name,affiliations,paperCount,hIndex,homepage"},
    )


def resolve_prof(prof: dict) -> dict:
    name = prof["name_en"]
    keywords = ((prof.get("disambiguation") or {}).get("keywords") or [])
    affiliation = prof.get("affiliation", "")

    # Build query: name + 1 strong lab keyword (filter out generic + multi-word noise)
    generic = {"language model", "NLP", "nlp", "alignment", "reasoning", "retrieval",
               "Tsinghua", "Peking", "PKU", "Nanyang", "NTU", "Singapore", "AIR",
               "Institute for AI Industry Research"}
    strong_kws = [k for k in keywords if k not in generic and len(k.split()) <= 2][:1]
    primary_query = " ".join([name] + strong_kws)

    # Try strong query first; fall back to name-only if no match
    queries_to_try = [primary_query]
    if strong_kws:
        queries_to_try.append(name)

    papers = []
    last_error = None
    used_query = primary_query
    for q in queries_to_try:
        try:
            papers = _search_papers(q, limit=25)
            used_query = q
            if papers:
                break
        except Exception as exc:
            last_error = exc
            continue

    if not papers and last_error is not None:
        return {"name_en": name, "error": f"search failed: {last_error}"}

    # Count authorIds whose name matches across top papers
    counter: Counter[str] = Counter()
    name_for_id: dict[str, str] = {}
    for p in papers:
        for a in p.get("authors") or []:
            if not _name_matches(a.get("name", ""), name):
                continue
            aid = a.get("authorId")
            if not aid:
                continue
            counter[aid] += 1
            name_for_id[aid] = a.get("name", "")

    if not counter:
        # Last resort: try name-only if we haven't yet
        if used_query != name:
            try:
                papers2 = _search_papers(name, limit=25)
                for p in papers2:
                    for a in p.get("authors") or []:
                        if not _name_matches(a.get("name", ""), name):
                            continue
                        aid = a.get("authorId")
                        if not aid:
                            continue
                        counter[aid] += 1
                        name_for_id[aid] = a.get("name", "")
                used_query = name
            except Exception as exc:
                return {"name_en": name, "query": used_query, "error": f"name-only fallback failed: {exc}"}

        if not counter:
            return {
                "name_en": name,
                "query": used_query,
                "error": "no matching author found in top papers",
                "candidates": [],
            }

    # Top 3 candidates
    top = counter.most_common(3)
    candidates = []
    for aid, hits in top:
        try:
            details = _get_author_details(aid)
            time.sleep(2)  # respect rate limit
        except Exception as exc:
            details = {"error": str(exc)}
        candidates.append({
            "authorId": aid,
            "matched_name": name_for_id.get(aid, ""),
            "paper_hits_in_top25": hits,
            "paperCount": details.get("paperCount"),
            "hIndex": details.get("hIndex"),
            "affiliations": details.get("affiliations") or [],
            "homepage": details.get("homepage"),
        })

    # Pick best: prefer affiliation match, then highest paper_hits
    affiliation_lc = affiliation.lower()

    def affiliation_match(c: dict) -> int:
        affs = " ".join(c.get("affiliations") or []).lower()
        # match against all words in affiliation, plus PKU/THU shorthand
        keys = [affiliation_lc]
        if "tsinghua" in affiliation_lc:
            keys.append("tsinghua")
        if "peking" in affiliation_lc:
            keys.extend(["peking", "pku"])
        if "nanyang" in affiliation_lc:
            keys.extend(["nanyang", "ntu"])
        return 1 if any(k in affs for k in keys if k) else 0

    candidates.sort(
        key=lambda c: (affiliation_match(c), c.get("paper_hits_in_top25", 0), c.get("hIndex") or 0),
        reverse=True,
    )

    chosen = candidates[0]
    return {
        "name_en": name,
        "name_cn": prof.get("name_cn"),
        "affiliation": affiliation,
        "query": used_query,
        "chosen_author_id": chosen["authorId"],
        "candidates": candidates,
    }


def main() -> int:
    with _PROF_LIST.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    profs = data.get("profs") or []

    # Load existing results to skip already-resolved profs (saves API budget)
    prior: dict[str, dict] = {}
    if _OUT_JSON.exists():
        try:
            for r in json.loads(_OUT_JSON.read_text(encoding="utf-8")):
                if r.get("chosen_author_id"):
                    prior[r["name_en"]] = r
        except Exception:
            pass

    print(f"Resolving {len(profs)} profs via S2 paper search "
          f"({len(prior)} already resolved, will skip)...\n")

    # Pacing: with API key 1 req/sec is fine; without, go slower
    inter_prof_delay = 2 if _API_KEY else 5

    results = []
    for i, prof in enumerate(profs, 1):
        if prof["name_en"] in prior:
            print(f"[{i}/{len(profs)}] {prof['name_en']}: skip (already resolved -> {prior[prof['name_en']]['chosen_author_id']})")
            results.append(prior[prof["name_en"]])
            continue
        print(f"[{i}/{len(profs)}] {prof['name_en']} ({prof.get('affiliation','?')}) ...")
        res = resolve_prof(prof)
        results.append(res)
        time.sleep(inter_prof_delay)

        chosen = res.get("chosen_author_id")
        cands = res.get("candidates") or []
        if chosen:
            top = cands[0]
            affs = "; ".join(top.get("affiliations") or []) or "(no affiliation listed)"
            print(
                f"   -> {chosen}  hits={top.get('paper_hits_in_top25')}  "
                f"papers={top.get('paperCount')}  h={top.get('hIndex')}"
            )
            print(f"      affiliations: {affs[:120]}")
        else:
            print(f"   !! {res.get('error', 'unresolved')}")

    _OUT_JSON.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {_OUT_JSON}")

    # Print review table
    print("\n=== REVIEW TABLE ===")
    print(f"{'#':<3} {'Name':<22} {'Aff':<22} {'AuthorID':<12} {'h':<4} {'papers':<7}")
    for i, r in enumerate(results, 1):
        if r.get("chosen_author_id"):
            top = r["candidates"][0]
            affs = (top.get("affiliations") or ["?"])[0][:20]
            print(
                f"{i:<3} {r['name_en'][:21]:<22} {affs:<22} "
                f"{r['chosen_author_id']:<12} {str(top.get('hIndex','?')):<4} "
                f"{str(top.get('paperCount','?')):<7}"
            )
        else:
            print(f"{i:<3} {r['name_en'][:21]:<22} <UNRESOLVED: {r.get('error','?')[:60]}>")

    return 0


if __name__ == "__main__":
    sys.exit(main())
