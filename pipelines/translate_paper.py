"""
Translate an arXiv paper to Vietnamese and compile a PDF.

Pipeline:
1. Download e-print source for the given arxiv_id (gzipped tarball or .tex)
2. Translate every translatable .tex file paragraph-by-paragraph (math/cite preserved)
3. Inject xelatex font setup, compile twice with xelatex
4. Return the resulting PDF path; caller is responsible for sending + cleanup

Used by the Telegram `/translate <arxiv_id>` command and CLI for manual use.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from tools.arxiv_source_tool import ArxivSource, download_eprint
from tools.latex_compile import compile_translated_paper
from tools.latex_translator import translate_tex_files

logger = logging.getLogger(__name__)

_ARXIV_ID_RE = re.compile(r"^(\d{4}\.\d{4,5}|[a-z\-]+/\d{7})$")


@dataclass
class TranslateResult:
    arxiv_id: str
    pdf_path: Optional[Path]
    source: Optional[ArxivSource]  # caller .cleanup() when done
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.pdf_path is not None and self.pdf_path.exists()


def _normalise_arxiv_id(raw: str) -> Optional[str]:
    raw = (raw or "").strip().strip("/")
    raw = re.sub(r"^arxiv:", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"v\d+$", "", raw)
    if _ARXIV_ID_RE.match(raw):
        return raw
    return None


async def translate_arxiv_paper(arxiv_id: str) -> TranslateResult:
    """
    Run the full translate-to-PDF pipeline. Async because translation uses an
    async LLM client. Compile + download remain synchronous.
    """
    norm = _normalise_arxiv_id(arxiv_id)
    if not norm:
        return TranslateResult(arxiv_id=arxiv_id, pdf_path=None, source=None,
                               error=f"invalid arxiv id: {arxiv_id!r}")

    logger.info("[translate] downloading e-print %s", norm)
    src = download_eprint(norm)
    if src is None:
        return TranslateResult(arxiv_id=norm, pdf_path=None, source=None,
                               error="no LaTeX source available on arxiv (some papers ship PDF only)")

    logger.info(
        "[translate] %s: %d tex files, main=%s",
        norm, len(src.tex_files), src.main_tex,
    )
    try:
        translated = await translate_tex_files(src.tex_files)
    except Exception as exc:
        logger.exception("translation failed for %s", norm)
        return TranslateResult(arxiv_id=norm, pdf_path=None, source=src,
                               error=f"translation failed: {exc}")

    logger.info("[translate] compiling with xelatex")
    pdf = compile_translated_paper(src.extract_dir, src.main_tex, translated)
    if pdf is None:
        return TranslateResult(arxiv_id=norm, pdf_path=None, source=src,
                               error="xelatex did not produce a PDF (see logs)")

    return TranslateResult(arxiv_id=norm, pdf_path=pdf, source=src)
