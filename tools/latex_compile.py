"""
Compile LaTeX source to PDF using xelatex.

Strategy:
- Write translated .tex content back to the extract_dir (preserving paths).
- Inject `\\usepackage{fontspec}\\setmainfont{TeX Gyre Termes}` into the
  preamble of main.tex so Vietnamese diacritics render. fontspec forces
  xelatex (it errors under pdflatex) — this is fine because we always run
  xelatex.
- Run xelatex twice (refs/labels resolve on 2nd pass).
- Use `-interaction=nonstopmode` (no `-halt-on-error`) so messy arxiv source
  still produces *some* PDF rather than nothing.

Returns the path to the produced PDF, or None if no PDF was produced (e.g.
catastrophic font/runtime failure).
"""
from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

XELATEX = "xelatex"
COMPILE_TIMEOUT = 240  # seconds per pass

_FONT_INJECTION = (
    "\n% openclaw-ailab: forced xelatex font setup for Vietnamese\n"
    "\\usepackage{fontspec}\n"
    "\\setmainfont{TeX Gyre Termes}\n"
)


def _strip_pdflatex_only_packages(tex: str) -> str:
    """Remove packages that conflict with xelatex: fontenc[T1] and inputenc[*]."""
    tex = re.sub(
        r"\\usepackage(\[[^\]]*\])?\{(inputenc|fontenc)\}\s*\n?",
        "",
        tex,
    )
    return tex


def _inject_font_setup(tex: str) -> str:
    """Insert fontspec setup right before \\begin{document}."""
    if "\\setmainfont" in tex:
        return tex  # already configured
    if "\\begin{document}" not in tex:
        # No document begin — append at top, may not compile but at least try
        return _FONT_INJECTION + tex
    return tex.replace("\\begin{document}", _FONT_INJECTION + "\\begin{document}", 1)


def _write_translated_files(extract_dir: Path, translated: dict[str, str]) -> None:
    for rel, content in translated.items():
        path = extract_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def _run_xelatex(extract_dir: Path, main_tex: str) -> tuple[int, str]:
    """Run a single xelatex pass. Returns (returncode, tail of log)."""
    cmd = [
        XELATEX,
        "-interaction=nonstopmode",
        "-no-shell-escape",
        main_tex,
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(extract_dir),
            capture_output=True,
            timeout=COMPILE_TIMEOUT,
            text=True,
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        logger.warning("xelatex timed out (cwd=%s, main=%s)", extract_dir, main_tex)
        return -1, "TIMEOUT"
    except FileNotFoundError:
        logger.error("xelatex not found in PATH")
        return -2, "XELATEX_NOT_FOUND"

    tail = (proc.stdout or "")[-2000:]
    return proc.returncode, tail


def compile_translated_paper(
    extract_dir: Path,
    main_tex: str,
    translated_tex_files: dict[str, str],
) -> Optional[Path]:
    """
    Compile the translated LaTeX back into a PDF inside `extract_dir`.

    On success, returns Path to the produced .pdf (typically named after the
    main .tex file). On failure, returns None.
    """
    # Apply translations + xelatex prep to main.tex
    if main_tex in translated_tex_files:
        prepped = _strip_pdflatex_only_packages(translated_tex_files[main_tex])
        prepped = _inject_font_setup(prepped)
        translated_tex_files = dict(translated_tex_files)
        translated_tex_files[main_tex] = prepped
    else:
        logger.warning("main_tex %s missing from translated_tex_files", main_tex)

    _write_translated_files(extract_dir, translated_tex_files)

    main_path = extract_dir / main_tex
    if not main_path.exists():
        logger.error("main tex %s does not exist after write", main_path)
        return None

    # Two passes for refs/labels
    last_tail = ""
    for i in (1, 2):
        rc, tail = _run_xelatex(extract_dir, main_tex)
        last_tail = tail
        if rc < 0:
            logger.error("xelatex pass %d aborted: %s", i, tail)
            break
        logger.info("xelatex pass %d rc=%d", i, rc)

    pdf_path = main_path.with_suffix(".pdf")
    if pdf_path.exists() and pdf_path.stat().st_size > 0:
        return pdf_path

    logger.error(
        "xelatex did not produce a PDF (cwd=%s main=%s). Log tail: %s",
        extract_dir, main_tex, last_tail[-500:],
    )
    return None
