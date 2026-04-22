"""Standalone writer script for the fork-e2e integration test.

Invoked as a subprocess::

    python fork_writer.py <db_path>

1. Records a parent run on thread-A.
2. Forks at the "research" node, overriding the research value.
3. Lets LangGraph re-execute draft → critique → polish on thread-B.
4. Prints "parent_run_id child_run_id fork_id" on stdout.
"""

from __future__ import annotations

import itertools
import sys
from pathlib import Path

_SPIKES = Path(__file__).resolve().parent.parent / "spikes"
sys.path.insert(0, str(_SPIKES))

from fake_llm import FakeLLM  # noqa: E402
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from langgraph.graph import END, START, StateGraph  # noqa: E402
from typing_extensions import TypedDict  # noqa: E402

from chronos.adapters import LangGraphRecorder  # noqa: E402
from chronos.core.models import NodeKind  # noqa: E402
from chronos.store import SqliteStore  # noqa: E402

NODES = ["plan", "research", "draft", "critique", "polish"]


class State(TypedDict, total=False):
    task: str
    plan: str
    research: str
    draft: str
    critique: str
    final: str
    log: list


def _make_step(llm: FakeLLM, name: str):
    """Each node reads *all upstream state* so downstream is sensitive to
    upstream changes (essential for fork to produce divergent output)."""

    def fn(state: State) -> dict:
        upstream = "|".join(
            f"{k}={str(state.get(k, ''))[:20]}"
            for k in ("task", "plan", "research", "draft", "critique")
            if state.get(k)
        )
        resp = llm.call(
            system=f"You are the {name} agent.",
            user=f"Task: {state.get('task', '')} | ctx: {upstream}",
        )
        key = "final" if name == "polish" else name
        log = list(state.get("log", []))
        log.append({"node": name, "fp": resp.fingerprint})
        return {key: resp.content, "log": log}

    return fn


def run_record_and_fork(db_path: Path) -> tuple[str, str, str, str, str]:
    llm = FakeLLM()
    g: StateGraph = StateGraph(State)
    for n in NODES:
        g.add_node(n, _make_step(llm, n))
    g.add_edge(START, NODES[0])
    for a, b in itertools.pairwise(NODES):
        g.add_edge(a, b)
    g.add_edge(NODES[-1], END)
    graph = g.compile(checkpointer=InMemorySaver())

    cfg_a = {"configurable": {"thread_id": "parent-t"}}
    initial: State = {"task": "compose an ode about time-travel", "log": []}

    with SqliteStore.open(db_path) as store:
        recorder = LangGraphRecorder(
            store,
            kind_map={n: NodeKind.LLM for n in NODES},
        )

        # --- Parent run ---
        with recorder.record(
            graph,
            thread_id="parent-t",
            task_description=initial["task"],
        ) as parent_ref:
            result_a = graph.invoke(initial, cfg_a)

        assert parent_ref.run_id is not None
        parent_run_id = parent_ref.run_id

        # --- Find the research node to fork from ---
        nodes = store.get_nodes_for_run(parent_run_id)
        research_node = next(n for n in nodes if n.node_name == "research")

        # --- Fork at research with a hijacked research value ---
        with recorder.fork(
            graph,
            parent_run_id=parent_run_id,
            at_node_id=research_node.id,
            overrides={"research": "[FORKED] totally different research content"},
            child_thread_id="fork-t",
            reason="e2e-test fork at research",
            tags=["fork-e2e"],
        ) as fork_ref:
            result_b = graph.invoke(None, {"configurable": {"thread_id": "fork-t"}})

        assert fork_ref.child_run_id is not None
        assert fork_ref.fork_id is not None
        return (
            parent_run_id,
            fork_ref.child_run_id,
            fork_ref.fork_id,
            result_a["final"],
            result_b["final"],
        )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: fork_writer.py <db_path>", file=sys.stderr)
        sys.exit(2)
    db = Path(sys.argv[1])
    parent_id, child_id, fork_id, final_a, final_b = run_record_and_fork(db)
    # Use a separator unlikely to appear in FakeLLM content
    print(f"{parent_id}|{child_id}|{fork_id}|{final_a[:40]}|{final_b[:40]}")
