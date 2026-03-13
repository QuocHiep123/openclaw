"""
GitHub repository reader tool.

Fetches repository metadata and file contents via the GitHub REST API
(no authentication required for public repos).
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import List, Optional

import httpx

_GH_API = "https://api.github.com"
_TIMEOUT = 15


@dataclass
class RepoInfo:
    full_name: str
    description: str
    stars: int
    language: str
    topics: List[str]
    html_url: str

    def to_dict(self) -> dict:
        return asdict(self)


def github_repo_info(owner: str, repo: str) -> Optional[RepoInfo]:
    """Return high-level metadata for a public GitHub repository."""
    url = f"{_GH_API}/repos/{owner}/{repo}"
    resp = httpx.get(url, timeout=_TIMEOUT)
    if resp.status_code != 200:
        return None
    data = resp.json()
    return RepoInfo(
        full_name=data.get("full_name", ""),
        description=data.get("description", "") or "",
        stars=data.get("stargazers_count", 0),
        language=data.get("language", "") or "",
        topics=data.get("topics", []),
        html_url=data.get("html_url", ""),
    )


def github_read_file(owner: str, repo: str, path: str, ref: str = "main") -> Optional[str]:
    """Read a single file from a public GitHub repo (max ~1 MB)."""
    url = f"{_GH_API}/repos/{owner}/{repo}/contents/{path}"
    resp = httpx.get(url, params={"ref": ref}, timeout=_TIMEOUT)
    if resp.status_code != 200:
        return None
    data = resp.json()
    if data.get("encoding") == "base64":
        import base64
        return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
    return data.get("content")


def github_list_files(owner: str, repo: str, path: str = "", ref: str = "main") -> List[str]:
    """List files/dirs at *path* in a public GitHub repo."""
    url = f"{_GH_API}/repos/{owner}/{repo}/contents/{path}"
    resp = httpx.get(url, params={"ref": ref}, timeout=_TIMEOUT)
    if resp.status_code != 200:
        return []
    data = resp.json()
    if isinstance(data, list):
        return [item["path"] for item in data]
    return []
