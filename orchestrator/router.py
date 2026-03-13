"""
Router — classifies user commands / messages into the correct agent.
"""
from __future__ import annotations

import logging
from enum import Enum

from langchain_core.messages import HumanMessage, SystemMessage

from config.environment import get_llm

logger = logging.getLogger(__name__)


class AgentTarget(str, Enum):
    RESEARCH = "research"
    EXPERIMENT = "experiment"
    AUTOMATION = "automation"
    PRODUCTIVITY = "productivity"


# Explicit command → agent mapping
_COMMAND_MAP = {
    "/paper": AgentTarget.RESEARCH,
    "/research": AgentTarget.RESEARCH,
    "/experiment": AgentTarget.EXPERIMENT,
    "/run_experiment": AgentTarget.EXPERIMENT,
    "/daily": AgentTarget.AUTOMATION,
    "/status": AgentTarget.AUTOMATION,
    "/todo": AgentTarget.PRODUCTIVITY,
    "/report": AgentTarget.PRODUCTIVITY,
    "/tasks": AgentTarget.PRODUCTIVITY,
}


def route_by_command(text: str) -> tuple[AgentTarget | None, str]:
    """
    If *text* starts with a known slash-command, return (target, remaining_text).
    Otherwise return (None, text).
    """
    text = text.strip()
    for cmd, target in _COMMAND_MAP.items():
        if text.lower().startswith(cmd):
            remainder = text[len(cmd):].strip()
            return target, remainder
    return None, text


async def route_by_llm(text: str) -> AgentTarget:
    """
    Use the LLM to classify free-text into one of the agent targets.
    """
    llm = get_llm(temperature=0.0)
    messages = [
        SystemMessage(
            content=(
                "You are a task classifier. Given a user message, respond with "
                "exactly one word: research, experiment, automation, or productivity.\n"
                "- research: papers, literature, arXiv, surveys\n"
                "- experiment: training, running code, ML experiments, benchmarks\n"
                "- automation: pipelines, scheduling, daily runs, system status\n"
                "- productivity: tasks, TODOs, notes, reports, progress\n"
            )
        ),
        HumanMessage(content=text),
    ]
    response = await llm.ainvoke(messages)
    word = response.content.strip().lower()

    for target in AgentTarget:
        if target.value in word:
            return target

    # Default fallback
    logger.warning("Router: could not classify '%s', defaulting to research", text)
    return AgentTarget.RESEARCH
