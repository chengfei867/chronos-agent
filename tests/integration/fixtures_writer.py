"""Standalone writer script for the SQLite integration test.

Invoked by test_sqlite_e2e.py as a subprocess::

    python fixtures_writer.py <db_path>

Runs the spike1 5-node LangGraph pipeline with FakeLLM, reshapes every step
into canonical Chronos Run/Node pydantic objects, persists to SQLite, then
prints the run_id on stdout.

Kept as a plain .py file (not an inline string) so f-string escaping doesn't
bite us and so we get real syntax highlighting / linting / type checks.
"""

from __future__ import annotations

import itertools
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

# Make the spikes dir importable for fake_llm
_SPIKES = Path(__file__).resolve().parent.parent / "spikes"
sys.path.insert(0, str(_SPIKES))

from fake_llm import FakeLLM  # noqa: E402
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from langgraph.graph import END, START, StateGraph  # noqa: E402
from typing_extensions import TypedDict  # noqa: E402

from chronos.core.models import Node, NodeKind, Run, RunStatus, Usage  # noqa: E402
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
    """Build a graph step closure. Keeps logic pure for easier reasoning."""

    def fn(state: State) -> dict:
        resp = llm.call(
            system=f"You are the {name} agent.",
            user=f"Task: {state.get('task', '')}",
        )
        key = "final" if name == "polish" else name
        # Deterministic per-step token count derived from fingerprint
        tok = int(resp.fingerprint, 16) % 200 + 10
        log = list(state.get("log", []))
        log.append({"node": name, "tokens": tok})
        return {key: resp.content, "log": log}

    return fn


def run_pipeline_and_persist(db_path: Path) -> str:
    """Run the 5-node spike1 pipeline, persist to chronos.db, return run_id."""
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
    final_state = graph.invoke(initial, cfg)

    # --- Reshape into Chronos canonical model ---
    run_id = str(uuid.uuid4())
    started = datetime.now(UTC)
    run = Run(
        id=run_id,
        adapter="langgraph",
        adapter_thread_id="t1",
        status=RunStatus.COMPLETED,
        started_at=started,
        ended_at=datetime.now(UTC),
        task_description=initial["task"],
        initial_state=dict(initial),
        final_state=dict(final_state),
    )

    node_rows: list[Node] = []
    prev_node_id: str | None = None
    for i, (name, log_entry) in enumerate(zip(NODES, final_state["log"], strict=False)):
        key = "final" if name == "polish" else name
        state_after = {"task": final_state["task"], key: final_state[key]}
        tokens = log_entry["tokens"]
        node = Node(
            id=str(uuid.uuid4()),
            run_id=run_id,
            step_index=i,
            node_name=name,
            kind=NodeKind.LLM,
            parent_node_id=prev_node_id,
            state_after=state_after,
            model_name="fake-llm-v0",
            usage=Usage(
                prompt_tokens=tokens // 2,
                completion_tokens=tokens - tokens // 2,
            ),
            cost_usd_cents=tokens,  # toy pricing
        )
        node_rows.append(node)
        prev_node_id = node.id

    with SqliteStore.open(db_path) as store, store.transaction():
        store.put_run(run)
        for node in node_rows:
            store.put_node(node)

    return run_id


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: fixtures_writer.py <db_path>", file=sys.stderr)
        sys.exit(2)
    db = Path(sys.argv[1])
    run_id = run_pipeline_and_persist(db)
    print(run_id)
