"""
Sandboxed Python code executor.

Runs user-supplied Python snippets inside a subprocess with a timeout.
Output (stdout + stderr) is captured and returned.

Security measures:
- Code length is capped at 15,000 chars.
- Hard timeout prevents runaway processes.
- Dangerous imports and operations are blocked.
- Network access is restricted by blocking common networking modules.
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ExecutionResult:
    stdout: str
    stderr: str
    return_code: int
    timed_out: bool

    @property
    def success(self) -> bool:
        return self.return_code == 0 and not self.timed_out


# Maximum allowed characters in a code snippet
_MAX_CODE_LENGTH = 15_000
# Hard timeout in seconds
_TIMEOUT_SECONDS = 60

# Dangerous patterns to block
_BLOCKED_PATTERNS = [
    r"\bos\.system\b",
    r"\bsubprocess\b",
    r"\b__import__\b",
    r"\beval\b\s*\(",
    r"\bexec\b\s*\(",
    r"\bopen\b\s*\([^)]*['\"]/(etc|proc|sys|var|usr|boot|root)",
    r"\bshutil\.(rmtree|move|copy)",
    r"\bos\.(remove|unlink|rmdir|rename|makedirs)\b",
    r"\bsocket\b",
    r"\brequests\b",
    r"\burllib\b",
    r"\bhttpx\b",
    r"\bparamiko\b",
    r"\bftplib\b",
]

_BLOCKED_RE = re.compile("|".join(_BLOCKED_PATTERNS), re.IGNORECASE)


def _check_safety(code: str) -> str | None:
    """Return an error message if the code contains dangerous patterns, else None."""
    match = _BLOCKED_RE.search(code)
    if match:
        return f"Blocked: code contains forbidden pattern '{match.group()}'"
    return None


def python_execute(code: str, timeout: int = _TIMEOUT_SECONDS) -> ExecutionResult:
    """
    Execute a Python code snippet in an isolated subprocess.

    Security notes:
    - Runs in a fresh subprocess (no shared memory with host).
    - Hard timeout prevents runaway processes.
    - Code length is capped.
    - Dangerous imports and operations are blocked.

    Args:
        code: Python source code to execute.
        timeout: Maximum execution time in seconds.

    Returns:
        ExecutionResult with captured output.
    """
    if len(code) > _MAX_CODE_LENGTH:
        return ExecutionResult(
            stdout="",
            stderr=f"Code exceeds maximum length ({_MAX_CODE_LENGTH} chars).",
            return_code=1,
            timed_out=False,
        )

    # Safety check
    safety_error = _check_safety(code)
    if safety_error:
        return ExecutionResult(
            stdout="",
            stderr=safety_error,
            return_code=1,
            timed_out=False,
        )

    # Write code to a temp file (avoids shell escaping issues)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(code)
        tmp_path = Path(tmp.name)

    try:
        result = subprocess.run(
            [sys.executable, str(tmp_path)],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=tempfile.gettempdir(),
        )
        return ExecutionResult(
            stdout=result.stdout[:10_000],
            stderr=result.stderr[:5_000],
            return_code=result.returncode,
            timed_out=False,
        )
    except subprocess.TimeoutExpired:
        return ExecutionResult(
            stdout="",
            stderr=f"Execution timed out after {timeout}s.",
            return_code=1,
            timed_out=True,
        )
    finally:
        tmp_path.unlink(missing_ok=True)
