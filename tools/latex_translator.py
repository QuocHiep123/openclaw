"""
LaTeX-aware paragraph-level translator (English -> Vietnamese).

Strategy: split .tex into paragraphs respecting \\begin{...}\\end{...} blocks,
skip math/code/bibliography environments, and translate each remaining
paragraph via LLM with a strict prompt that preserves every LaTeX command,
math, citation, and label.

Cheap path (~$0.005/paper with gpt-4o-mini for typical 30-page paper).
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Iterable

from langchain_core.messages import HumanMessage, SystemMessage

from config.environment import get_llm

logger = logging.getLogger(__name__)

# Environments whose contents must be passed through verbatim (math/code/bib)
_PRESERVE_ENVS = {
    "equation", "equation*", "align", "align*", "gather", "gather*",
    "multline", "multline*", "eqnarray", "eqnarray*", "math", "displaymath",
    "lstlisting", "verbatim", "verbatim*", "minted", "alltt",
    "thebibliography", "tikzpicture",
}

# Heuristic: paragraph is "translatable" if it has at least this many alnum chars
# of plain English (i.e. not all math/symbols).
_MIN_TEXT_CHARS = 25

# Cap on chunk size sent to LLM (chars). Long paragraphs split here.
_MAX_CHUNK_CHARS = 4000

_TRANSLATE_SYSTEM_PROMPT = """\
You translate LaTeX text from English to Vietnamese for academic papers.

CRITICAL RULES:
1. PRESERVE every LaTeX command EXACTLY: \\command{...}, \\begin{...}, \\end{...}, \\\\, &, etc.
2. PRESERVE all math regions EXACTLY: $...$, $$...$$, \\(...\\), \\[...\\], \\begin{equation}...\\end{equation}, etc.
3. PRESERVE all citations and references EXACTLY: \\cite{key}, \\ref{label}, \\label{...}, \\url{...}, \\autoref{...}.
4. PRESERVE comments (lines starting with %) EXACTLY.
5. Translate ONLY English natural-language text into Vietnamese. Use Vietnamese with full diacritics.
6. Keep technical terms in English when there is no widely-accepted Vietnamese term (e.g. transformer, embedding, LoRA, RLHF). Translate generic words.
7. Do NOT translate LaTeX environment names (e.g. equation, table, figure, lstlisting).
8. Do NOT add explanations, prefaces, or summaries. Output ONLY the translated LaTeX.
9. Output length should be similar to input length (translation only, no commentary).
"""


def _split_paragraphs(tex: str) -> list[str]:
    """
    Split text into paragraph-like blocks. Blank lines are paragraph separators,
    but blank lines inside \\begin{X}...\\end{X} do NOT split.
    """
    paragraphs: list[str] = []
    buf: list[str] = []
    env_stack: list[str] = []

    begin_re = re.compile(r"\\begin\{([^}]+)\}")
    end_re = re.compile(r"\\end\{([^}]+)\}")

    for line in tex.split("\n"):
        stripped = line.strip()

        # Update env stack based on this line
        for m in begin_re.finditer(line):
            env_stack.append(m.group(1))
        for m in end_re.finditer(line):
            if env_stack and env_stack[-1] == m.group(1):
                env_stack.pop()

        if not stripped and not env_stack:
            if buf:
                paragraphs.append("\n".join(buf))
                buf = []
        else:
            buf.append(line)

    if buf:
        paragraphs.append("\n".join(buf))
    return paragraphs


def _strip_commands_and_math(s: str) -> str:
    """Crude strip: remove \\command, math, args, keep plain text only (for length check)."""
    s = re.sub(r"%.*", "", s)  # comments
    s = re.sub(r"\$\$.*?\$\$", "", s, flags=re.DOTALL)
    s = re.sub(r"\$[^$]*\$", "", s)
    s = re.sub(r"\\\[.*?\\\]", "", s, flags=re.DOTALL)
    s = re.sub(r"\\\(.*?\\\)", "", s, flags=re.DOTALL)
    s = re.sub(r"\\[a-zA-Z@]+\*?(?:\[[^\]]*\])?(?:\{[^}]*\})*", "", s)
    s = re.sub(r"[{}\\]", "", s)
    return s


def _is_translatable(paragraph: str) -> bool:
    """Skip math-only, bib, code, or near-empty paragraphs."""
    p = paragraph.strip()
    if not p:
        return False
    # Whole-paragraph environment in skip list
    m = re.match(r"\\begin\{([^}]+)\}", p)
    if m and m.group(1) in _PRESERVE_ENVS:
        return False
    # bibitem-only
    if p.startswith("\\bibitem") or p.startswith("\\bibliography"):
        return False
    # Plain text length check
    plain = _strip_commands_and_math(p)
    plain_alnum = sum(1 for c in plain if c.isalpha())
    return plain_alnum >= _MIN_TEXT_CHARS


def _chunk_long_paragraph(paragraph: str, max_chars: int = _MAX_CHUNK_CHARS) -> list[str]:
    """Split a long paragraph into <= max_chars chunks at sentence boundaries when possible."""
    if len(paragraph) <= max_chars:
        return [paragraph]

    chunks: list[str] = []
    remaining = paragraph
    while len(remaining) > max_chars:
        # try sentence boundary
        cut = remaining.rfind(". ", 0, max_chars)
        if cut < max_chars // 2:
            cut = remaining.rfind("\n", 0, max_chars)
        if cut < max_chars // 2:
            cut = max_chars
        chunks.append(remaining[: cut + 1].rstrip())
        remaining = remaining[cut + 1 :].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


async def _translate_chunk(chunk: str, llm) -> str:
    user = f"Translate the following LaTeX content. Output the translated LaTeX only.\n\n{chunk}"
    try:
        resp = await llm.ainvoke([
            SystemMessage(content=_TRANSLATE_SYSTEM_PROMPT),
            HumanMessage(content=user),
        ])
        out = str(resp.content).strip()
        # Strip code-fence wrapping if model added any
        if out.startswith("```"):
            out = re.sub(r"^```[a-zA-Z]*\n?", "", out)
            out = re.sub(r"\n?```$", "", out)
        return out
    except Exception as exc:
        logger.warning("translate chunk failed (len=%d): %s", len(chunk), exc)
        return chunk  # graceful: leave English


async def translate_tex_string(tex: str, concurrency: int = 4) -> str:
    """Translate a single .tex string. Returns reassembled .tex."""
    llm = get_llm(temperature=0.2)
    paragraphs = _split_paragraphs(tex)

    # Build task list: (idx, paragraph) for translatables, mark others passthrough
    sem = asyncio.Semaphore(concurrency)

    async def maybe_translate(idx: int, p: str) -> tuple[int, str]:
        if not _is_translatable(p):
            return idx, p
        chunks = _chunk_long_paragraph(p)
        out_parts: list[str] = []
        for c in chunks:
            async with sem:
                out_parts.append(await _translate_chunk(c, llm))
        return idx, "\n".join(out_parts)

    tasks = [maybe_translate(i, p) for i, p in enumerate(paragraphs)]
    results = await asyncio.gather(*tasks)
    results.sort(key=lambda x: x[0])
    return "\n\n".join(p for _, p in results)


async def translate_tex_files(tex_files: dict[str, str]) -> dict[str, str]:
    """Translate all .tex files (typically just main + included sections)."""
    out: dict[str, str] = {}
    for name, content in tex_files.items():
        logger.info("translating %s (len=%d)", name, len(content))
        out[name] = await translate_tex_string(content)
    return out
