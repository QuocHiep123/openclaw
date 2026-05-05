"""
Download and unpack arXiv LaTeX source (e-print).

arXiv exposes LaTeX source at https://arxiv.org/e-print/{id}. The response is
typically a gzipped tarball, sometimes a bare gzipped .tex. ~95% of cs.CL
papers ship source; for the rest, this returns None and the caller should
fall back (e.g., translate the abstract only or skip).
"""
from __future__ import annotations

import gzip
import io
import logging
import shutil
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)

EPRINT_URL = "https://arxiv.org/e-print/{}"
USER_AGENT = "openclaw-ailab/0.1 (mailto:dangquochiep2908@gmail.com)"
HTTP_TIMEOUT = 60


@dataclass
class ArxivSource:
    arxiv_id: str
    extract_dir: Path
    main_tex: str  # filename relative to extract_dir
    tex_files: dict[str, str]  # filename -> contents (utf-8 best-effort)
    other_files: list[str]  # non-.tex files (figures, .bbl, etc.) in extract_dir

    def cleanup(self) -> None:
        if self.extract_dir.exists():
            shutil.rmtree(self.extract_dir, ignore_errors=True)


def _read_text_best_effort(path: Path) -> str:
    for encoding in ("utf-8", "latin-1", "cp1252"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_bytes().decode("utf-8", errors="replace")


def _detect_main_tex(extract_dir: Path) -> Optional[str]:
    """Pick the .tex file containing \\documentclass; prefer 'main.tex' if multiple."""
    candidates: list[tuple[int, str]] = []
    for tex in extract_dir.glob("*.tex"):
        content = _read_text_best_effort(tex)
        if "\\documentclass" in content:
            score = 0
            if tex.stem.lower() == "main":
                score += 100
            if tex.stem.lower() in {"paper", "ms", "manuscript"}:
                score += 50
            score += len(content)  # tiebreaker: longest doc wins
            candidates.append((score, tex.name))

    if not candidates:
        return None

    candidates.sort(reverse=True)
    return candidates[0][1]


def _try_extract(payload: bytes, extract_dir: Path) -> bool:
    """Attempt to extract payload as tar.gz, gz (single file), or raw .tex. Return success."""
    # tar.gz (most common)
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as tf:
            tf.extractall(extract_dir, filter="data")
        return True
    except (tarfile.TarError, EOFError, OSError):
        pass

    # gzipped single file (usually .tex)
    try:
        decompressed = gzip.decompress(payload)
        head = decompressed[:200].decode("utf-8", errors="replace")
        if "\\documentclass" in head or "\\begin{document}" in decompressed[:5000].decode(
            "utf-8", errors="replace"
        ):
            (extract_dir / "main.tex").write_bytes(decompressed)
            return True
    except (OSError, gzip.BadGzipFile):
        pass

    # raw text (rare)
    head = payload[:200].decode("utf-8", errors="replace")
    if "\\documentclass" in head:
        (extract_dir / "main.tex").write_bytes(payload)
        return True

    return False


def download_eprint(arxiv_id: str) -> Optional[ArxivSource]:
    """
    Download e-print source for arxiv_id and return parsed ArxivSource, or None
    if no source is available.

    Caller should call .cleanup() when done.
    """
    url = EPRINT_URL.format(arxiv_id)
    try:
        resp = requests.get(
            url,
            timeout=HTTP_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
            allow_redirects=True,
        )
    except requests.RequestException as exc:
        logger.warning("eprint download failed for %s: %s", arxiv_id, exc)
        return None

    if resp.status_code != 200:
        logger.warning("eprint %s returned HTTP %d", arxiv_id, resp.status_code)
        return None

    if not resp.content:
        return None

    extract_dir = Path(tempfile.mkdtemp(prefix=f"arxiv_{arxiv_id.replace('/', '_')}_"))
    try:
        if not _try_extract(resp.content, extract_dir):
            logger.warning("could not extract source for %s", arxiv_id)
            shutil.rmtree(extract_dir, ignore_errors=True)
            return None

        main_tex = _detect_main_tex(extract_dir)
        if not main_tex:
            logger.warning("no main .tex (with \\documentclass) found for %s", arxiv_id)
            shutil.rmtree(extract_dir, ignore_errors=True)
            return None

        tex_files: dict[str, str] = {}
        other_files: list[str] = []
        for path in extract_dir.rglob("*"):
            if path.is_dir():
                continue
            rel = path.relative_to(extract_dir).as_posix()
            if path.suffix.lower() == ".tex":
                tex_files[rel] = _read_text_best_effort(path)
            else:
                other_files.append(rel)

        return ArxivSource(
            arxiv_id=arxiv_id,
            extract_dir=extract_dir,
            main_tex=main_tex,
            tex_files=tex_files,
            other_files=other_files,
        )
    except Exception:
        shutil.rmtree(extract_dir, ignore_errors=True)
        raise
