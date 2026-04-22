"""Spike 1 — LangGraph checkpointer state capture.

Proves: a 5-node LangGraph agent can have its state snapshot-captured
at every step via the checkpointer, and those snapshots contain enough
information for us to later list/inspect nodes.

This is the foundation — if we can't reliably snapshot state, there is
no fork capability.

Exit criterion: test passes; we print the captured state history.
"""

from __future__ import annotations

from operator import add
from typing import Annotated

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from tests.spikes.fake_llm import FakeLLM


class AgentState(TypedDict):
    """Minimal 5-step pipeline state."""

    task: str
    plan: str
    research: str
    draft: str
    review: str
    final: str
    # log accumulates one entry per node — used to verify order
    log: Annotated[list[str], add]


# --- Node functions (5 of them) -------------------------------------------------

_LLM = FakeLLM(seed="spike1")


def node_plan(state: AgentState) -> dict[str, object]:
    resp = _LLM.call("You are a planner.", state["task"])
    return {"plan": resp.content, "log": [f"plan:{resp.fingerprint}"]}


def node_research(state: AgentState) -> dict[str, object]:
    resp = _LLM.call("You are a researcher.", state["plan"])
    return {"research": resp.content, "log": [f"research:{resp.fingerprint}"]}


def node_draft(state: AgentState) -> dict[str, object]:
    resp = _LLM.call("You are a writer.", state["research"])
    return {"draft": resp.content, "log": [f"draft:{resp.fingerprint}"]}


def node_review(state: AgentState) -> dict[str, object]:
    resp = _LLM.call("You are a critic.", state["draft"])
    return {"review": resp.content, "log": [f"review:{resp.fingerprint}"]}


def node_finalize(state: AgentState) -> dict[str, object]:
    resp = _LLM.call("You are an editor.", state["review"])
    return {"final": resp.content, "log": [f"finalize:{resp.fingerprint}"]}


def build_graph() -> StateGraph:
    g = StateGraph(AgentState)
    g.add_node("plan", node_plan)
    g.add_node("research", node_research)
    g.add_node("draft", node_draft)
    g.add_node("review", node_review)
    g.add_node("finalize", node_finalize)
    g.add_edge(START, "plan")
    g.add_edge("plan", "research")
    g.add_edge("research", "draft")
    g.add_edge("draft", "review")
    g.add_edge("review", "finalize")
    g.add_edge("finalize", END)
    return g


@pytest.mark.spike
def test_spike1_capture_all_5_steps() -> None:
    """Run a 5-node graph; verify checkpointer captured all intermediate states."""
    saver = InMemorySaver()
    graph = build_graph().compile(checkpointer=saver)

    config = {"configurable": {"thread_id": "spike1-thread-1"}}
    initial: AgentState = {
        "task": "Write a short haiku about time-travel debugging.",
        "plan": "",
        "research": "",
        "draft": "",
        "review": "",
        "final": "",
        "log": [],
    }

    result = graph.invoke(initial, config)

    # --- Assertions: execution completed fully ---
    assert result["final"], "final node never ran"
    assert len(result["log"]) == 5, f"expected 5 log entries, got {result['log']}"
    expected_order = ["plan", "research", "draft", "review", "finalize"]
    actual_order = [entry.split(":")[0] for entry in result["log"]]
    assert actual_order == expected_order

    # --- Assertions: checkpointer captured history ---
    history = list(graph.get_state_history(config))
    # History contains: 1 pre-input snapshot + 5 post-node snapshots = 6
    assert len(history) >= 6, (
        f"expected >=6 snapshots (1 pre-input + 5 post-step), got {len(history)}"
    )

    # The most recent snapshot (history[0]) should have the final result
    latest = history[0]
    assert latest.values["final"], "latest checkpoint missing final value"

    # --- Inspectability: post-input snapshots all contain the task field ---
    # LangGraph checkpointer behavior (v1.1): produces 1 snapshot BEFORE each
    # node execution (step=N, values=pre-node) + 1 post-finalize snapshot.
    # For a 5-node graph: steps = 0,1,2,3,4,5 → 6 post-input snapshots.
    post_input_snaps = [s for s in history if s.metadata.get("step", -999) >= 0]
    assert len(post_input_snaps) >= 5, (
        f"expected >=5 post-input snapshots (1 per node), got {len(post_input_snaps)}"
    )
    for snap in post_input_snaps:
        assert isinstance(snap.values, dict)
        assert "task" in snap.values
        assert snap.values["task"]  # non-empty

    print(f"\n✅ Spike 1 PASS — captured {len(history)} snapshots")
    print(f"   Final: {result['final']!r}")
    print(f"   Log order: {actual_order}")
