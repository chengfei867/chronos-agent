"""Exploration spike: what's actually in LangGraph's StateSnapshot?

This is NOT a test (doesn't assert correctness) — it's a guided tour that
prints the shape of every field we might want to harvest for Chronos.

Run with: ``uv run python tests/spikes/spike4_probe_snapshot.py``

Output is logged to stdout and inspected by eye; findings get written into
ADR-004 if they surprise us.
"""
# ruff: noqa: N806, RUF007  -- exploration script, readability > lint purity

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Reuse the deterministic fake LLM
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fake_llm import FakeLLM
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict


class S(TypedDict, total=False):
    task: str
    plan: str
    research: str
    draft: str
    final: str
    log: list


def _pretty(obj: Any, max_len: int = 200) -> str:
    try:
        s = json.dumps(obj, default=str, ensure_ascii=False)
    except Exception:
        s = repr(obj)
    return s if len(s) <= max_len else s[:max_len] + "…"


def main() -> None:
    llm = FakeLLM()
    NODES = ["plan", "research", "draft", "polish"]

    def step(name: str):
        def fn(state: S) -> dict:
            resp = llm.call(system=f"{name} agent.", user=state.get("task", ""))
            key = "final" if name == "polish" else name
            log = list(state.get("log", []))
            log.append({"node": name, "fp": resp.fingerprint})
            return {key: resp.content, "log": log}

        return fn

    g: StateGraph = StateGraph(S)
    for n in NODES:
        g.add_node(n, step(n))
    g.add_edge(START, NODES[0])
    for a, b in zip(NODES, NODES[1:], strict=False):
        g.add_edge(a, b)
    g.add_edge(NODES[-1], END)

    saver = InMemorySaver()
    graph = g.compile(checkpointer=saver)
    cfg = {"configurable": {"thread_id": "probe-1"}}
    initial = {"task": "explain why the sky is blue", "log": []}

    print("=" * 70)
    print("INVOKING GRAPH…")
    final = graph.invoke(initial, cfg)
    print("final_state keys:", list(final.keys()))
    print()

    # ---------- Explore get_state() (single snapshot) ----------
    print("=" * 70)
    print("get_state(cfg) — the LATEST snapshot:")
    latest = graph.get_state(cfg)
    print(f"  type       : {type(latest).__name__}")
    print(f"  fields     : {list(latest._fields) if hasattr(latest, '_fields') else dir(latest)}")
    print(f"  values     : {_pretty(latest.values)}")
    print(f"  next       : {latest.next!r}")
    print(f"  config     : {_pretty(latest.config)}")
    print(f"  metadata   : {_pretty(latest.metadata)}")
    print(f"  created_at : {latest.created_at!r}")
    print(f"  parent_cfg : {_pretty(latest.parent_config)}")
    print(f"  tasks      : {_pretty(latest.tasks)}")
    print()

    # ---------- Explore get_state_history() (full chain) ----------
    print("=" * 70)
    print("get_state_history(cfg) — full chain (newest-first):")
    history = list(graph.get_state_history(cfg))
    print(f"  total snapshots: {len(history)}")
    print(f"  (expected: len(NODES)+1 = {len(NODES) + 1})")
    print()

    for i, snap in enumerate(history):
        md = snap.metadata or {}
        writes = md.get("writes") if isinstance(md, dict) else None
        source = md.get("source") if isinstance(md, dict) else None
        step = md.get("step") if isinstance(md, dict) else None
        print(f"--- snapshot[{i}] ---")
        print(f"    metadata.source : {source!r}")
        print(f"    metadata.step   : {step}")
        print(f"    metadata.writes : {_pretty(writes)}")
        print(f"    next            : {snap.next!r}")
        print(
            f"    values (keys)   : {list(snap.values.keys()) if isinstance(snap.values, dict) else type(snap.values).__name__}"
        )
        print(
            f"    values (log)    : {_pretty(snap.values.get('log', [])) if isinstance(snap.values, dict) else '-'}"
        )
        ckpt = (snap.config or {}).get("configurable", {}).get("checkpoint_id")
        print(f"    checkpoint_id   : {ckpt}")
        parent_ckpt = (
            (snap.parent_config or {}).get("configurable", {}).get("checkpoint_id")
            if snap.parent_config
            else None
        )
        print(f"    parent_ckpt_id  : {parent_ckpt}")
        print(
            f"    tasks           : {[(t.name, t.id, getattr(t, 'result', None)) for t in snap.tasks]}"
        )
        print(f"    created_at      : {snap.created_at}")
        print()

    print("=" * 70)
    print("END OF PROBE.")


if __name__ == "__main__":
    main()
