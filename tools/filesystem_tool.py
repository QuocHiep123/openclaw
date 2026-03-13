"""
Filesystem reader tool.

Provides safe, read-only access to files within an allowed base directory.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

from config.settings import settings

# Only files under the project data directory are readable
_ALLOWED_BASE = settings.data_dir


def _validate_path(path: str) -> Path:
    """Resolve *path* and ensure it stays inside the allowed base."""
    resolved = Path(path).resolve()
    allowed = _ALLOWED_BASE.resolve()
    if not str(resolved).startswith(str(allowed)):
        raise PermissionError(
            f"Access denied: path must be under {allowed}"
        )
    return resolved


def filesystem_read(path: str, max_bytes: int = 50_000) -> Optional[str]:
    """
    Read a text file from the allowed data directory.

    Args:
        path: Absolute or relative path (resolved against data dir).
        max_bytes: Read at most this many bytes.

    Returns:
        File contents as a string, or None if not found.
    """
    try:
        full = _validate_path(path)
    except PermissionError as exc:
        return f"[ERROR] {exc}"

    if not full.is_file():
        return None
    return full.read_text(encoding="utf-8", errors="replace")[:max_bytes]


def filesystem_list(path: str = "") -> List[str]:
    """List files and directories under the allowed data directory."""
    target = _ALLOWED_BASE / path if path else _ALLOWED_BASE
    try:
        target = _validate_path(str(target))
    except PermissionError as exc:
        return [f"[ERROR] {exc}"]

    if not target.is_dir():
        return []
    entries = []
    for item in sorted(target.iterdir()):
        suffix = "/" if item.is_dir() else ""
        entries.append(item.name + suffix)
    return entries
