"""
Tool registry for the MCP server.

Every tool is registered with a name, description, JSON-serialisable input
schema, and a callable.  The registry is the single source of truth for
all tools that agents can invoke.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class ToolDefinition:
    """Metadata + callable for one tool."""
    name: str
    description: str
    parameters: Dict[str, Any]  # JSON Schema for inputs
    func: Callable[..., Any]


class ToolRegistry:
    """In-process tool registry."""

    def __init__(self) -> None:
        self._tools: Dict[str, ToolDefinition] = {}

    def register(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        func: Callable[..., Any],
    ) -> None:
        self._tools[name] = ToolDefinition(
            name=name,
            description=description,
            parameters=parameters,
            func=func,
        )

    def list_tools(self) -> List[Dict[str, Any]]:
        """Return JSON-friendly list of tool schemas."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            }
            for t in self._tools.values()
        ]

    def get(self, name: str) -> Optional[ToolDefinition]:
        return self._tools.get(name)

    def invoke(self, name: str, arguments: Dict[str, Any]) -> Any:
        tool = self._tools.get(name)
        if tool is None:
            raise KeyError(f"Tool '{name}' not found in registry")
        return tool.func(**arguments)


# --------------- Build the default registry --------------------------------

def _build_default_registry() -> ToolRegistry:
    """Construct the registry with all built-in tools."""
    from tools.arxiv_tool import arxiv_search, arxiv_fetch_by_id
    from tools.github_tool import github_repo_info, github_read_file, github_list_files
    from tools.python_runner import python_execute
    from tools.filesystem_tool import filesystem_read, filesystem_list
    from tools.web_search_tool import web_search

    reg = ToolRegistry()

    reg.register(
        name="arxiv_search",
        description="Search arXiv for papers matching a query string.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "max_results": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
        func=lambda query, max_results=10: [
            p.to_dict() for p in arxiv_search(query, max_results=max_results)
        ],
    )

    reg.register(
        name="arxiv_fetch_by_id",
        description="Fetch a single arXiv paper by its ID.",
        parameters={
            "type": "object",
            "properties": {
                "paper_id": {"type": "string"},
            },
            "required": ["paper_id"],
        },
        func=lambda paper_id: (p.to_dict() if (p := arxiv_fetch_by_id(paper_id)) else None),
    )

    reg.register(
        name="github_repo_info",
        description="Get metadata for a public GitHub repository.",
        parameters={
            "type": "object",
            "properties": {
                "owner": {"type": "string"},
                "repo": {"type": "string"},
            },
            "required": ["owner", "repo"],
        },
        func=lambda owner, repo: (r.to_dict() if (r := github_repo_info(owner, repo)) else None),
    )

    reg.register(
        name="github_read_file",
        description="Read a file from a public GitHub repo.",
        parameters={
            "type": "object",
            "properties": {
                "owner": {"type": "string"},
                "repo": {"type": "string"},
                "path": {"type": "string"},
                "ref": {"type": "string", "default": "main"},
            },
            "required": ["owner", "repo", "path"],
        },
        func=github_read_file,
    )

    reg.register(
        name="github_list_files",
        description="List files in a GitHub repo directory.",
        parameters={
            "type": "object",
            "properties": {
                "owner": {"type": "string"},
                "repo": {"type": "string"},
                "path": {"type": "string", "default": ""},
            },
            "required": ["owner", "repo"],
        },
        func=github_list_files,
    )

    reg.register(
        name="python_executor",
        description="Execute a Python code snippet and return stdout/stderr.",
        parameters={
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python source code to run"},
                "timeout": {"type": "integer", "default": 60},
            },
            "required": ["code"],
        },
        func=lambda code, timeout=60: {
            "stdout": (r := python_execute(code, timeout)).stdout,
            "stderr": r.stderr,
            "return_code": r.return_code,
            "timed_out": r.timed_out,
        },
    )

    reg.register(
        name="filesystem_reader",
        description="Read a text file from the project data directory.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
            },
            "required": ["path"],
        },
        func=filesystem_read,
    )

    reg.register(
        name="filesystem_list",
        description="List files in the project data directory.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "default": ""},
            },
        },
        func=filesystem_list,
    )

    reg.register(
        name="web_search",
        description="Search the web via DuckDuckGo.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
        func=lambda query, max_results=5: [
            r.to_dict() for r in web_search(query, max_results=max_results)
        ],
    )

    return reg


# Module-level singleton
default_registry = _build_default_registry()
