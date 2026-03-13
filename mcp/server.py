"""
MCP-compatible tool server — exposes the tool registry over HTTP (FastAPI).

Endpoints:
    GET  /tools          — list available tools
    POST /tools/invoke   — invoke a tool by name with JSON arguments
    GET  /health         — health check
"""
from __future__ import annotations

import json
import logging
import traceback
from typing import Any, Dict

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from mcp.tool_registry import default_registry
from config.settings import settings

logger = logging.getLogger(__name__)

app = FastAPI(title="AI-Lab MCP Tool Server", version="1.0.0")


# ---- Request / Response models -------------------------------------------

class InvokeRequest(BaseModel):
    name: str
    arguments: Dict[str, Any] = {}


class InvokeResponse(BaseModel):
    name: str
    result: Any
    error: str | None = None


# ---- Routes ---------------------------------------------------------------

@app.get("/")
async def root():
    return {
        "name": "AI-Lab MCP Tool Server",
        "version": "1.0.0",
        "endpoints": ["/health", "/tools", "/tools/invoke"],
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/tools")
async def list_tools():
    """Return the schema of every registered tool."""
    return {"tools": default_registry.list_tools()}


@app.post("/tools/invoke", response_model=InvokeResponse)
async def invoke_tool(req: InvokeRequest):
    """Invoke a tool by name and return the result."""
    try:
        result = default_registry.invoke(req.name, req.arguments)
        return InvokeResponse(name=req.name, result=result)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Tool '{req.name}' not found")
    except Exception as exc:
        logger.error("Tool invocation error: %s", traceback.format_exc())
        return InvokeResponse(name=req.name, result=None, error=str(exc))


# ---- Entry-point for `uvicorn mcp.server:app` ----------------------------

def start_server():
    """Convenience wrapper to start via `python -m mcp.server`."""
    import uvicorn

    uvicorn.run(
        "mcp.server:app",
        host=settings.mcp_host,
        port=settings.mcp_port,
        reload=False,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    start_server()
