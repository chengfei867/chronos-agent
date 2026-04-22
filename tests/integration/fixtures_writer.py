"""Standalone writer script for the SQLite + adapter integration test.

Invoked by test_sqlite_e2e.py as a subprocess::

    python fixtures_writer.py <db_path>

Runs the spike1 5-node LangGraph pipeline with FakeLLM and records it via
the ``LangGraphRecorder`` adapter (zero hand-reshape), then prints the run_id
on stdout.

**Before Round 4**: this file had ~40 lines of hand-written reshape code
mapping final_state + log → Node rows. After Round 4 (M1.4) the adapter
does that automatically; the code below is what every real Chronos user
will write.
"""

from __future__ import annotations

import itertools
import sys
from pathlib import Path

# Make the spikes dir importable for fake_llm
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
    """Build a graph step closure. Kept pure for easier reasoning."""

    def fn(state: State) -> dict:
        resp = llm.call(
            system=f"You are the {name} agent.",
            user=f"Task: {state.get('task', '')}",
        )
        key = "final" if name == "polish" else name
        tok = int(resp.fingerprint, 16) % 200 + 10
        log = list(state.get("log", []))
        log.append({"node": name, "tokens": tok})
        return {key: resp.content, "log": log}

    return fn


def run_pipeline_and_persist(db_path: Path) -> str:
    """Run the 5-node spike1 pipeline via the adapter; return run_id."""
    llm = FakeLLM()

    g: StateGraph = StateGraph(State)
    for n in NODES:
        g.add_node(n, _make_step(llm, n))
    g.add_edge(START, NODES[0])
    for a, b in itertools.pairwise(NODES):
        g.add_edge(a, b)
    g.add_edge(NODES[-1], END)

    graph = g.compile(checkpointer=InMemorySaver())
    cfg = {"configurable": {"thread_id": "t1"}}
    initial: State = {"task": "write a haiku about rain", "log": []}

    with SqliteStore.open(db_path) as store:
        recorder = LangGraphRecorder(
            store,
            kind_map={n: NodeKind.LLM for n in NODES},
        )
        with recorder.record(
            graph,
            thread_id="t1",
            task_description=initial["task"],
        ) as ref:
            graph.invoke(initial, cfg)

        assert ref.run_id is not None, "adapter failed to persist"
        return ref.run_id


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: fixtures_writer.py <db_path>", file=sys.stderr)
        sys.exit(2)
    db = Path(sys.argv[1])
    run_id = run_pipeline_and_persist(db)
    print(run_id)
