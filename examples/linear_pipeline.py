"""Chronos example 1 — linear pipeline (plan → research → draft → review → finalize).

Scenario:
    You wrote a 5-step LangGraph agent. It works. Then a product
    manager says "can you make the 'research' step more thorough?"
    Instead of editing blindly and praying, you want to:

        1. RECORD a known-good run as a baseline
        2. FORK that run at the research node with the new (longer)
           prompt applied
        3. DIFF parent vs fork to see exactly what downstream nodes
           changed

This is the canonical Alex story from ``docs/design/user-stories.md``.

Run:
    uv run python examples/linear_pipeline.py

Then inspect:
    chronos runs list --db examples/chronos.db
    chronos diff <parent_id> <fork_child_id> --db examples/chronos.db

The LangGraph agent uses a deterministic ``FakeLLM`` (no API key
required). The fork swaps in a seed labelled ``"v2-thorough"`` for
the research step so the downstream nodes see visibly different
context and the diff has something to show.
"""

from __future__ import annotations

import sys
from operator import add
from pathlib import Path
from typing import Annotated

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

# Make ``examples/`` importable whether invoked from repo root or elsewhere.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from chronos.adapters import LangGraphRecorder
from chronos.core.models import NodeKind
from chronos.store import SqliteStore
from examples._fake_llm import FakeLLM


class PipelineState(TypedDict):
    task: str
    plan: str
    research: str
    draft: str
    review: str
    final: str
    log: Annotated[list[str], add]


# The two "LLM personas": the baseline run uses ``baseline``; the fork
# swaps the research node to ``v2-thorough`` so its output (and every
# downstream node's output that depends on ``research``) changes.
_LLM_BASE = FakeLLM(seed="baseline")
_LLM_V2 = FakeLLM(seed="v2-thorough")


def _make_nodes(researcher: FakeLLM) -> dict[str, object]:
    """Return node functions closed over the chosen researcher LLM.

    The only node that switches LLM between parent / fork is
    ``research``. Every other node always uses the baseline — this
    way, any diff we see downstream of ``research`` is *caused* by
    the researcher swap.
    """

    def node_plan(state: PipelineState) -> dict[str, object]:
        resp = _LLM_BASE.call("You are a planner.", state["task"])
        return {"plan": resp.content, "log": [f"plan:{resp.fingerprint}"]}

    def node_research(state: PipelineState) -> dict[str, object]:
        resp = researcher.call("You are a researcher.", state["plan"])
        return {"research": resp.content, "log": [f"research:{resp.fingerprint}"]}

    def node_draft(state: PipelineState) -> dict[str, object]:
        resp = _LLM_BASE.call("You are a writer.", state["research"])
        return {"draft": resp.content, "log": [f"draft:{resp.fingerprint}"]}

    def node_review(state: PipelineState) -> dict[str, object]:
        resp = _LLM_BASE.call("You are a critic.", state["draft"])
        return {"review": resp.content, "log": [f"review:{resp.fingerprint}"]}

    def node_finalize(state: PipelineState) -> dict[str, object]:
        resp = _LLM_BASE.call("You are an editor.", state["review"])
        return {"final": resp.content, "log": [f"finalize:{resp.fingerprint}"]}

    return {
        "plan": node_plan,
        "research": node_research,
        "draft": node_draft,
        "review": node_review,
        "finalize": node_finalize,
    }


def build_graph(researcher: FakeLLM) -> StateGraph:
    nodes = _make_nodes(researcher)
    g = StateGraph(PipelineState)
    for name, fn in nodes.items():
        g.add_node(name, fn)
    g.add_edge(START, "plan")
    g.add_edge("plan", "research")
    g.add_edge("research", "draft")
    g.add_edge("draft", "review")
    g.add_edge("review", "finalize")
    g.add_edge("finalize", END)
    return g


NODE_KIND_MAP = {
    "plan": NodeKind.LLM,
    "research": NodeKind.LLM,
    "draft": NodeKind.LLM,
    "review": NodeKind.LLM,
    "finalize": NodeKind.LLM,
}


def run_demo(db_path: Path) -> tuple[str, str]:
    """Execute the full record → fork → diff demo.

    Returns ``(parent_run_id, fork_child_run_id)`` so the caller can
    print CLI invocations pointing at them.
    """
    # The same compiled graph is reused for both the parent and fork
    # runs — the checkpointer is what separates them (different
    # ``thread_id``).
    saver = InMemorySaver()
    graph = build_graph(_LLM_BASE).compile(checkpointer=saver)

    initial: PipelineState = {
        "task": "Compose a tweet about chronos-agent.",
        "plan": "",
        "research": "",
        "draft": "",
        "review": "",
        "final": "",
        "log": [],
    }

    with SqliteStore.open(db_path) as store:
        recorder = LangGraphRecorder(store, kind_map=NODE_KIND_MAP)

        # --- Step 1: RECORD the baseline run ---
        with recorder.record(
            graph,
            thread_id="linear-parent",
            task_description=initial["task"],
            tags=["example", "linear-pipeline", "parent"],
        ) as parent_ref:
            graph.invoke(initial, {"configurable": {"thread_id": "linear-parent"}})
        parent_run_id = parent_ref.run_id
        assert parent_run_id is not None

        # Find the node we want to fork from (research).
        nodes = store.get_nodes_for_run(parent_run_id)
        research_node = next(n for n in nodes if n.node_name == "research")

        # --- Step 2: FORK at research with the v2-thorough researcher ---
        # Re-compile the graph with the alternative researcher LLM so
        # that downstream re-execution uses it. We reuse the same
        # checkpointer so LangGraph can pick up the seeded child state.
        fork_graph = build_graph(_LLM_V2).compile(checkpointer=saver)

        # Compute the post-swap "research" value deterministically so
        # we can inject it as the fork's override — this is exactly
        # what a real user would do when swapping a prompt / model.
        forked_research = _LLM_V2.call(
            "You are a researcher.",
            # The parent's plan output — read from the stored state.
            research_node.state_after["plan"],  # type: ignore[index]
        ).content

        with recorder.fork(
            fork_graph,
            parent_run_id=parent_run_id,
            at_node_id=research_node.id,
            overrides={
                "research": forked_research,
                # Reset downstream so we see full re-execution on the diff.
                "draft": "",
                "review": "",
                "final": "",
                "log": list(research_node.state_after.get("log", [])),  # type: ignore[union-attr]
            },
            child_thread_id="linear-fork",
            reason="swap researcher to v2-thorough prompt",
            tags=["example", "linear-pipeline", "fork"],
        ) as fork_ref:
            fork_graph.invoke(None, {"configurable": {"thread_id": "linear-fork"}})
        child_run_id = fork_ref.child_run_id
        assert child_run_id is not None

    return parent_run_id, child_run_id


def _print_next_steps(db_path: Path, parent_id: str, child_id: str) -> None:
    print()
    print("=" * 72)
    print("Chronos linear-pipeline example — demo complete ✅")
    print("=" * 72)
    print()
    print(f"DB            : {db_path}")
    print(f"Parent run    : {parent_id}")
    print(f"Fork child run: {child_id}")
    print()
    print("Try these commands:")
    print()
    print(f"  chronos runs list --db {db_path}")
    print(f"  chronos runs show {parent_id} --db {db_path}")
    print(f"  chronos diff {parent_id} {child_id} --db {db_path}")
    print(f"  chronos diff {parent_id} {child_id} --db {db_path} --verbose")
    print(f"  chronos diff {parent_id} {child_id} --db {db_path} --full")
    print(f"  chronos diff {parent_id} {child_id} --db {db_path} --json")
    print()


if __name__ == "__main__":
    here = Path(__file__).resolve().parent
    db = here / "chronos.db"
    # Fresh run every time — examples are demos, not long-lived state.
    if db.exists():
        db.unlink()
    parent, child = run_demo(db)
    _print_next_steps(db, parent, child)
