"""Spike 5 — probe the StateSnapshot history shape on a FORKED thread.

Motivation
----------
Round 4 built `LangGraphRecorder._persist_from_history` on two empirical
facts about the *original* thread:

1. `get_state_history(cfg)[-1]` (oldest) has `metadata["source"] == "input"`
   — the placeholder snapshot for the initial state.
2. Snapshots are `N + 2` for N executed nodes.

The adapter asserts (1) or raises `AdapterError`. For M1.5 "fork" we need
to re-record the forked thread. Before writing code we verify whether a
thread seeded by `update_state(as_node=X)` + `invoke(None)` yields the
same structure or a different one.

Expected risks (to confirm / refute):
  R1. The forked thread's history might NOT start with `source='input'`
      because no fresh input was ever given — state was "implanted" via
      `update_state`. If so the Round 4 adapter rejects the thread.
  R2. The forked thread's step numbering might be `N+1, N+2, ...` (global)
      or `0, 1, ...` (thread-local). We don't know.
  R3. `metadata["source"]` values: we know "input" (first) and "loop"
      (per-node) from spike 4. A seeded state is plausibly "update" — we
      need to see it.
  R4. `snapshot.tasks[0].name` on the first pre-execution snapshot of B
      — does LangGraph know the next pending node, or is it empty?

What this spike prints
----------------------
For both the original and the forked thread:
  - count of snapshots
  - for each snapshot: (index, source, step, next, tasks[*].name, values-keys)
  - the raw `metadata` dict of each snapshot

Also asserts the user-visible invariant (fork produced divergent final)
so a regression here fails loudly.

Run with:  uv run pytest tests/spikes/spike5_probe_fork_history.py -s -v
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from tests.spikes.test_spike1_capture import AgentState, build_graph


def _dump_snap(idx: int, snap: Any) -> dict[str, Any]:
    md = dict(snap.metadata) if isinstance(snap.metadata, dict) else {}
    # metadata may contain un-JSON-able objects; stringify as a fallback
    try:
        md_json: Any = json.loads(json.dumps(md, default=str))
    except Exception:
        md_json = {k: str(v) for k, v in md.items()}
    return {
        "idx": idx,
        "source": md.get("source"),
        "step": md.get("step"),
        "writes_is_none": md.get("writes") is None,
        "next": tuple(snap.next) if snap.next else (),
        "tasks": [getattr(t, "name", None) for t in (snap.tasks or [])],
        "values_keys": sorted((snap.values or {}).keys())
        if isinstance(snap.values, dict)
        else "<non-dict>",
        "checkpoint_id_tail": (
            (snap.config or {}).get("configurable", {}).get("checkpoint_id", "")
        )[-8:],
        "metadata": md_json,
    }


@pytest.mark.spike
def test_spike5_fork_history_shape() -> None:
    saver = InMemorySaver()
    graph = build_graph().compile(checkpointer=saver)

    # --- Run A: the original ---
    cfg_a = {"configurable": {"thread_id": "spike5-orig"}}
    initial: AgentState = {
        "task": "Write a haiku about chronos.",
        "plan": "",
        "research": "",
        "draft": "",
        "review": "",
        "final": "",
        "log": [],
    }
    result_a = graph.invoke(initial, cfg_a)
    assert result_a["final"]

    hist_a_newest_first = list(graph.get_state_history(cfg_a))
    hist_a = list(reversed(hist_a_newest_first))  # oldest-first, for reading

    # Pick fork point: right after 'research' completed (draft pending)
    fork_snap = next(s for s in hist_a if s.next == ("draft",))

    # --- Fork: seed thread B, invoke(None) ---
    cfg_b = {"configurable": {"thread_id": "spike5-fork"}}
    forked_state = dict(fork_snap.values)
    forked_state["research"] = "[HIJACKED-spike5] alt research"
    forked_state["log"] = [*fork_snap.values["log"], "FORK:spike5"]

    graph.update_state(cfg_b, forked_state, as_node="research")
    result_b = graph.invoke(None, cfg_b)
    assert result_b["final"]
    assert result_b["final"] != result_a["final"]

    hist_b_newest_first = list(graph.get_state_history(cfg_b))
    hist_b = list(reversed(hist_b_newest_first))

    # --- Dump both ---
    print("\n=== THREAD A (original) ===")
    print(f"snapshots: {len(hist_a)}")
    for i, s in enumerate(hist_a):
        print(json.dumps(_dump_snap(i, s), indent=2, default=str))

    print("\n=== THREAD B (forked) ===")
    print(f"snapshots: {len(hist_b)}")
    for i, s in enumerate(hist_b):
        print(json.dumps(_dump_snap(i, s), indent=2, default=str))

    # --- Structural recordings for the ADR ---
    a_sources = [
        (s.metadata or {}).get("source") if isinstance(s.metadata, dict) else None
        for s in hist_a
    ]
    b_sources = [
        (s.metadata or {}).get("source") if isinstance(s.metadata, dict) else None
        for s in hist_b
    ]
    a_steps = [
        (s.metadata or {}).get("step") if isinstance(s.metadata, dict) else None
        for s in hist_a
    ]
    b_steps = [
        (s.metadata or {}).get("step") if isinstance(s.metadata, dict) else None
        for s in hist_b
    ]
    print(f"\nA sources: {a_sources}")
    print(f"B sources: {b_sources}")
    print(f"A steps:   {a_steps}")
    print(f"B steps:   {b_steps}")

    # --- Claims we want to verify for ADR-005 ---
    # Claim 1: A still starts with source='input' (regression check for R4 invariant)
    assert a_sources[0] == "input", f"A first source = {a_sources[0]!r}"

    # Claim 2: B's first snapshot source — record whatever it is for ADR.
    first_b_source = b_sources[0]
    print(f"\n>>> FORKED THREAD FIRST SOURCE = {first_b_source!r} <<<")
    # We intentionally do NOT assert == 'input'. This is the question the
    # spike is answering. If it's different, adapter.fork() must handle it.

    # Claim 3: record whether fork thread's steps restart at 0 or continue
    print(f">>> B step sequence = {b_steps}")

    # Claim 4: the final node name sequence reconstructible from pre-snapshots
    def pre_node_names(hist: list[Any]) -> list[str]:
        out = []
        for i in range(1, len(hist) - 1):
            tasks = hist[i].tasks or []
            if tasks:
                out.append(getattr(tasks[0], "name", None))
        return out

    a_nodes = pre_node_names(hist_a)
    b_nodes = pre_node_names(hist_b)
    print(f">>> A pre-node-names = {a_nodes}")
    print(f">>> B pre-node-names = {b_nodes}")

    # Final outputs
    print(f"\nFinal A: {result_a['final']!r}")
    print(f"Final B: {result_b['final']!r}")
