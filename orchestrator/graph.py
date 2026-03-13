"""
LangGraph orchestration graph.

Workflow:
    START → Orchestrator (route) → Agent → MemoryUpdate → END

The orchestrator node classifies the user's intent and routes to the
correct agent.  After the agent completes, MemoryUpdate persists any
side-effects.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from langgraph.graph import StateGraph, END

from orchestrator.router import AgentTarget, route_by_command, route_by_llm

logger = logging.getLogger(__name__)


# ---- Graph State ----------------------------------------------------------

@dataclass
class LabState:
    """Shared state flowing through the graph."""
    user_input: str = ""
    user_id: int = 0
    chat_history: List[Dict[str, str]] = field(default_factory=list)
    target: Optional[str] = None
    agent_payload: str = ""  # text passed to the agent
    agent_output: str = ""
    error: str = ""


# ---- Cached agent instances -----------------------------------------------

_agent_cache: Dict[str, Any] = {}


def _get_agent(name: str):
    """Return a cached agent instance (singleton per agent type)."""
    if name not in _agent_cache:
        if name == "research":
            from agents.research_agent import ResearchAgent
            _agent_cache[name] = ResearchAgent()
        elif name == "experiment":
            from agents.experiment_agent import ExperimentAgent
            _agent_cache[name] = ExperimentAgent()
        elif name == "automation":
            from agents.automation_agent import AutomationAgent
            _agent_cache[name] = AutomationAgent()
        elif name == "productivity":
            from agents.productivity_agent import ProductivityAgent
            _agent_cache[name] = ProductivityAgent()
    return _agent_cache[name]


# ---- Node implementations ------------------------------------------------

async def orchestrator_node(state: LabState) -> Dict[str, Any]:
    """Classify user input and decide which agent to invoke."""
    target, payload = route_by_command(state.user_input)
    if target is None:
        target = await route_by_llm(state.user_input)
        payload = state.user_input
    logger.info("Orchestrator routed to %s", target)
    return {"target": target.value, "agent_payload": payload}


async def research_node(state: LabState) -> Dict[str, Any]:
    agent = _get_agent("research")
    output = await agent.run(state.agent_payload or state.user_input, chat_history=state.chat_history)
    return {"agent_output": output}


async def experiment_node(state: LabState) -> Dict[str, Any]:
    agent = _get_agent("experiment")
    output = await agent.run(state.agent_payload or state.user_input, chat_history=state.chat_history)
    return {"agent_output": output}


async def automation_node(state: LabState) -> Dict[str, Any]:
    agent = _get_agent("automation")
    output = await agent.run(state.agent_payload or state.user_input, chat_history=state.chat_history)
    return {"agent_output": output}


async def productivity_node(state: LabState) -> Dict[str, Any]:
    agent = _get_agent("productivity")
    output = await agent.run(state.agent_payload or state.user_input, chat_history=state.chat_history)
    return {"agent_output": output}


async def memory_update_node(state: LabState) -> Dict[str, Any]:
    """Post-agent hook — store chat messages in memory."""
    from memory.research_memory import research_memory

    if state.user_id:
        research_memory.store_chat_message(state.user_id, "user", state.user_input)
        if state.agent_output:
            research_memory.store_chat_message(state.user_id, "assistant", state.agent_output[:2000])

    logger.info("MemoryUpdate: agent finished, output length=%d", len(state.agent_output))
    return {}


# ---- Conditional edge ----------------------------------------------------

def route_to_agent(state: LabState) -> str:
    mapping = {
        AgentTarget.RESEARCH.value: "research",
        AgentTarget.EXPERIMENT.value: "experiment",
        AgentTarget.AUTOMATION.value: "automation",
        AgentTarget.PRODUCTIVITY.value: "productivity",
    }
    return mapping.get(state.target, "research")


# ---- Build the graph -----------------------------------------------------

def build_graph() -> StateGraph:
    """Construct and compile the LangGraph workflow."""
    graph = StateGraph(LabState)

    # Add nodes
    graph.add_node("orchestrator", orchestrator_node)
    graph.add_node("research", research_node)
    graph.add_node("experiment", experiment_node)
    graph.add_node("automation", automation_node)
    graph.add_node("productivity", productivity_node)
    graph.add_node("memory_update", memory_update_node)

    # Entry point
    graph.set_entry_point("orchestrator")

    # Conditional routing from orchestrator to the right agent
    graph.add_conditional_edges(
        "orchestrator",
        route_to_agent,
        {
            "research": "research",
            "experiment": "experiment",
            "automation": "automation",
            "productivity": "productivity",
        },
    )

    # All agents converge to memory_update → END
    for agent_name in ["research", "experiment", "automation", "productivity"]:
        graph.add_edge(agent_name, "memory_update")
    graph.add_edge("memory_update", END)

    return graph.compile()


# Module-level compiled graph
lab_graph = build_graph()


async def run_workflow(user_input: str, user_id: int = 0, chat_history: list = None) -> str:
    """
    Convenience function: invoke the graph with a user message and return
    the agent's output string.
    """
    initial_state = LabState(
        user_input=user_input,
        user_id=user_id,
        chat_history=chat_history or [],
    )
    final_state = await lab_graph.ainvoke(initial_state)
    return final_state.get("agent_output", "No output from agent.")
