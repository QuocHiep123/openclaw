"""
CLI interface — interactive command-line REPL for the AI Research Lab.

Usage:
    python -m interface.cli

Type any command (/paper, /experiment, /daily, /todo, /status)
or free-text to interact with the system.  Type 'exit' to quit.
"""
from __future__ import annotations

import asyncio
import logging

from rich.console import Console
from rich.markdown import Markdown

from orchestrator.graph import run_workflow

console = Console()
logger = logging.getLogger(__name__)


async def repl() -> None:
    console.print("[bold green]🔬 AI Research Lab — CLI[/bold green]")
    console.print("Type a command or free-text. Type [bold]exit[/bold] to quit.\n")

    while True:
        try:
            user_input = console.input("[bold cyan]>>> [/bold cyan]")
        except (EOFError, KeyboardInterrupt):
            break

        if user_input.strip().lower() in ("exit", "quit"):
            console.print("[dim]Goodbye![/dim]")
            break

        if not user_input.strip():
            continue

        with console.status("Thinking…"):
            try:
                result = await run_workflow(user_input)
            except Exception as exc:
                console.print(f"[red]Error: {exc}[/red]")
                continue

        console.print(Markdown(result))
        console.print()


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(name)s | %(message)s")
    asyncio.run(repl())


if __name__ == "__main__":
    main()
