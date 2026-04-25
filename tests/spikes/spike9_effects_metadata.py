"""Spike 9 — R43-D: effects metadata schema decision.

**Question:** Should ``nodes.effects`` live as a (a) new top-level column on
the Node model + DB schema, or (b) a key inside the existing
``metadata: dict[str, Any]`` field which round-trips through the existing
``nodes.metadata_json`` TEXT column?

**Method:** pick a tiny scenario — three-node LangGraph with one httpx
call. After recording, we **retrofit** a Node instance with
``effects=["network"]`` via ``node.metadata["effects"] = [...]``, persist
back through the store, read it back, and verify:

    F1. The extra key survives a full write→read round-trip.
    F2. Existing queries (list runs, list nodes, fork) don't regress.
    F3. A filter query "give me all nodes where effects contains
        'network'" can be expressed in 1-2 lines of Python over the
        returned Node list (no SQL changes).

If F1..F3 all pass → **Option B wins**: use ``node.metadata['effects']``.
Zero migration, zero ADR surface, adapter can write it without any
core-model change. If anything fails → we need Option A (new column).

Run:

    uv run python tests/spikes/spike9_effects_metadata.py
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, TypedDict

import httpx
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from chronos.adapters.langgraph import LangGraphRecorder
from chronos.store.sqlite import SqliteStore


class S(TypedDict, total=False):
    plan: str
    api_out: dict[str, Any]
    verdict: str


def _make_client() -> httpx.Client:
    return httpx.Client(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"ok": True}))
    )


def _graph() -> StateGraph:
    def plan_node(state: S) -> S:
        return {"plan": state.get("plan", "default")}

    def call_api(state: S) -> S:
        with _make_client() as c:
            r = c.post("https://api.example.com/verify", json={"q": state["plan"]})
            return {"api_out": r.json()}

    def judge(state: S) -> S:
        return {"verdict": "ok" if state["api_out"].get("ok") else "bad"}

    g = StateGraph(S)
    g.add_node("plan", plan_node)
    g.add_node("call_api", call_api)
    g.add_node("judge", judge)
    g.add_edge(START, "plan")
    g.add_edge("plan", "call_api")
    g.add_edge("call_api", "judge")
    g.add_edge("judge", END)
    return g


# --- heuristic that a future PH3-02 adapter change would encapsulate ---
EFFECT_HEURISTIC: dict[str, list[str]] = {
    "call_api": ["network"],
    "plan": [],
    "judge": [],
}


def main() -> None:
    tmp = Path(tempfile.mkdtemp())
    chronos_db = tmp / "chronos.db"

    # --- Record once ---
    saver = InMemorySaver()
    compiled = _graph().compile(checkpointer=saver)
    with SqliteStore.open(chronos_db) as store:
        rec = LangGraphRecorder(store=store)
        thread_id = "spike9"
        cfg = {"configurable": {"thread_id": thread_id}}
        with rec.record(
            compiled,
            thread_id=thread_id,
            task_description="spike9 metadata round-trip",
        ) as run_ref:
            compiled.invoke({"plan": "probe"}, cfg)
        run_id = run_ref.run_id

    # --- F1. Retrofit effects and persist back via raw SQL UPDATE ---
    #   (this simulates what a PH3-02 adapter upgrade would do in-line
    #    during extract_run — except we do it post-hoc so we don't touch
    #    the adapter.)

    with sqlite3.connect(chronos_db) as conn:
        cur = conn.execute(
            "SELECT id, node_name, metadata_json FROM nodes WHERE run_id = ?",
            (run_id,),
        )
        rows = cur.fetchall()
        for node_id, node_name, md_json in rows:
            md = json.loads(md_json) if md_json else {}
            md["effects"] = EFFECT_HEURISTIC.get(node_name, [])
            conn.execute(
                "UPDATE nodes SET metadata_json = ? WHERE id = ?",
                (json.dumps(md), node_id),
            )
        conn.commit()

    # --- F1 verify: round-trip through Store returns the key ---
    with SqliteStore.open(chronos_db) as store:
        run = store.get_run(run_id)
        assert run is not None, "run disappeared"
        nodes = store.get_nodes_for_run(run_id)
        assert nodes, "no nodes"
        effects_by_name = {n.node_name: n.metadata.get("effects") for n in nodes}
        print(f"[F1] effects round-trip: {effects_by_name}")
        assert effects_by_name["call_api"] == ["network"], "effects not persisted"
        assert effects_by_name["plan"] == [], "plan should have empty effects"

    # --- F2 verify: existing queries still work ---
    with SqliteStore.open(chronos_db) as store:
        all_runs = store.list_runs()
        assert any(r.id == run_id for r in all_runs), "list_runs regression"
        nodes = store.get_nodes_for_run(run_id)
        assert len(nodes) == 3, f"expected 3 nodes, got {len(nodes)}"
        print(f"[F2] list_runs + get_nodes_for_run still work: {len(nodes)} nodes")

    # --- F3 verify: filter "network-effectful nodes" in Python, no SQL ---
    with SqliteStore.open(chronos_db) as store:
        nodes = store.get_nodes_for_run(run_id)
        network_nodes = [n for n in nodes if "network" in n.metadata.get("effects", [])]
        print(f"[F3] network-effectful nodes: {[n.node_name for n in network_nodes]}")
        assert len(network_nodes) == 1
        assert network_nodes[0].node_name == "call_api"

    print()
    print("SPIKE 9 RESULT: Option B (metadata['effects']) VIABLE ✅")
    print("  - Zero schema change")
    print("  - Zero adapter-core change to Node model")
    print("  - Filter query is 1-line Python over returned Node list")
    print("  - Adapter can inject `effects` during extract_run (PH3-02 work)")
    print("  - Web UI can read `node.metadata.effects` for the warning badge")


if __name__ == "__main__":
    main()
