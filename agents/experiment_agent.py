"""
Experiment Agent — designs, executes, and analyses ML experiments.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

from langchain_core.messages import HumanMessage, SystemMessage

from config.environment import get_llm
from config.settings import settings
from memory.research_memory import research_memory
from tools.python_runner import python_execute

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "experiment_prompt.md"
_SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")

_LANG_SUFFIX = {
    "vi": "\n\nHãy trả lời bằng tiếng Việt.",
    "en": "",
}


class ExperimentAgent:
    """Agent that generates experiment configs, runs code, and analyses results."""

    name = "ExperimentAgent"

    def __init__(self):
        self.llm = get_llm(temperature=0.3)

    async def run(self, task: str, chat_history: list = None) -> str:
        """
        Execute an experiment task.

        Args:
            task: Experiment description (e.g. "ppo_attention").
            chat_history: Previous conversation messages.

        Returns:
            Markdown report with config, execution output, and analysis.
        """
        logger.info("[ExperimentAgent] Starting task: %s", task)

        # Pull related experiments from memory for context
        prior = research_memory.search_experiments(task, n=3)
        prior_text = ""
        if prior:
            prior_text = "Previous related experiments:\n"
            for item in prior:
                prior_text += f"- {item['metadata'].get('name', '?')}: {item['document'][:300]}\n"

        # Build messages with chat history
        lang = _LANG_SUFFIX.get(settings.bot_language, "")
        messages = [
            SystemMessage(content=_SYSTEM_PROMPT + lang),
        ]
        if chat_history:
            for msg in chat_history[-4:]:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role == "user":
                    messages.append(HumanMessage(content=content))
                else:
                    from langchain_core.messages import AIMessage
                    messages.append(AIMessage(content=content))

        messages.append(
            HumanMessage(
                content=(
                    f"Design and run an experiment for: **{task}**\n\n"
                    f"{prior_text}\n"
                    "Steps:\n"
                    "1. Describe the experiment plan.\n"
                    "2. Provide a complete, self-contained Python script that "
                    "prints JSON results to stdout (e.g. {\"loss\": 0.5, \"accuracy\": 0.9}).\n"
                    "3. I will execute the script and give you the output.\n\n"
                    "Wrap the Python script in a ```python code block."
                )
            ),
        )

        design_response = await self.llm.ainvoke(messages)
        design_text = design_response.content

        # Extract the code block
        code = self._extract_code(design_text)

        exec_output = ""
        if code:
            result = python_execute(code, timeout=120)
            exec_output = (
                f"\n\n### Execution Output\n"
                f"**Return code:** {result.return_code}\n"
                f"```\n{result.stdout}\n```\n"
            )
            if result.stderr:
                exec_output += f"**Stderr:**\n```\n{result.stderr}\n```\n"

            # Store results in memory
            research_memory.store_experiment(
                name=task.replace(" ", "_")[:50],
                config={"task": task},
                results={"stdout": result.stdout[:2000], "return_code": result.return_code},
            )

        # Ask LLM to analyse execution output
        if exec_output:
            analysis_msgs = [
                SystemMessage(content=_SYSTEM_PROMPT + lang),
                HumanMessage(
                    content=(
                        f"Here is the experiment design and execution results:\n\n"
                        f"{design_text}\n{exec_output}\n\n"
                        "Please analyse the results and suggest next steps."
                    )
                ),
            ]
            analysis_response = await self.llm.ainvoke(analysis_msgs)
            return f"{design_text}{exec_output}\n\n### Analysis\n{analysis_response.content}"

        return design_text

    # ---- helpers ----------------------------------------------------------

    @staticmethod
    def _extract_code(text: str) -> str:
        """Extract the first ```python ... ``` block from text."""
        marker = "```python"
        start = text.find(marker)
        if start == -1:
            return ""
        start += len(marker)
        end = text.find("```", start)
        if end == -1:
            return text[start:].strip()
        return text[start:end].strip()
