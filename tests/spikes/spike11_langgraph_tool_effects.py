"""Spike 11 — LangGraph adapter effects classification (ADR-020 follow-up).

**Question:** Does Chronos's effects classifier produce correct tags on a
LangGraph run whose graph nodes have tool-function-shaped names
(``fetch_weather_api``, ``read_file``, ``query_db``)? And — conversely —
what happens when the user forgets to pass ``kind_map``?

This spike closes the loop ADR-020 left open: the ADR claims LangGraph
is "vacuously satisfied" by the three-segment `node_name` contract
because its graph-level node names are already function-shaped. That
claim was made from code-reading only. Spike 11 verifies it empirically
and documents the one real gotcha we found (``kind_map`` is not
optional for tool-kinded classification to fire).

**Method:** Build a 4-node ``StateGraph`` where node functions are
intentionally named to trip each effect-classifier group:

    plan          → pure FN / ROUTER (effect-free)
    fetch_weather_api  → tool (network)
    read_file          → tool (fs)
    query_db           → tool (db)

Run it twice through ``LangGraphRecorder``:

  - **Run A** — no ``kind_map``. Every node defaults to ``NodeKind.FN``.
    Classifier's ``kind == NodeKind.TOOL`` gate short-circuits, so every
    ``effects == []`` *regardless of how suggestive the name is*.
    This is a real usage trap worth documenting.
  - **Run B** — ``kind_map={"fetch_weather_api": TOOL, "read_file": TOOL,
    "query_db": TOOL}``. Classifier now runs keyword regex over the
    single-segment function name (exactly what ADR-020 says LangGraph
    already emits). Each tool node should pick up its expected tag.

**Findings (expected — spike confirms if so):**

  F1. LangGraph ``node_name`` is single-segment and equals the string
      the user passed to ``StateGraph.add_node(name, fn)`` (no prefix,
      no class suffix, no three-segment shape).
  F2. Without ``kind_map``, all tool-looking nodes get ``effects=[]``
      (classifier TOOL gate never fires). ⚠️ usage gotcha.
  F3. With ``kind_map`` declaring TOOL, classifier produces the right
      tags for each tool: ``["network"]``, ``["fs"]``, ``["db"]``.
  F4. LangGraph's node-name shape is already compatible with the
      classifier's regex patterns → **ADR-020's "vacuously satisfied"
      claim is true**. No three-segment surgery needed for LangGraph.

If F1..F4 all pass → update CONTEXT.md / ADR-020 Follow-ups to note the
audit is closed, and document the ``kind_map`` gotcha in the
``LangGraphRecorder`` docstring or a short research note.

Run:

    uv run python tests/spikes/spike11_langgraph_tool_effects.py

This spike uses NO real LLM — all node bodies are plain Python — so it
runs offline in <2 s.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from chronos.adapters.langgraph import LangGraphRecorder
from chronos.core.models import NodeKind
from chronos.store import SqliteStore

# ---------------------------------------------------------------------------
# A tiny LangGraph state + 4 nodes. Names chosen to trip each classifier
# group (NETWORK_PATTERNS, FS_PATTERNS, DB_PATTERNS) plus one pure node.
# ---------------------------------------------------------------------------


class State(TypedDict, total=False):
    task: str
    weather: str
    contents: str
    rows: str
    summary: str


def plan(state: State) -> State:
    """Pure planner — no side effect; classifier should NOT tag it."""
    return {"task": "fetch + read + query"}


def fetch_weather_api(state: State) -> State:
    """Tool node whose graph-level name matches NETWORK_PATTERNS."""
    return {"weather": "sunny 22C in Beijing"}


def read_file(state: State) -> State:
    """Tool node whose graph-level name matches FS_PATTERNS."""
    return {"contents": "(stub) file contents"}


def query_db(state: State) -> State:
    """Tool node whose graph-level name matches DB_PATTERNS."""
    return {"rows": "(stub) db rows"}


def _build_graph() -> StateGraph:
    g: StateGraph = StateGraph(State)
    g.add_node("plan", plan)
    g.add_node("fetch_weather_api", fetch_weather_api)
    g.add_node("read_file", read_file)
    g.add_node("query_db", query_db)
    g.add_edge(START, "plan")
    g.add_edge("plan", "fetch_weather_api")
    g.add_edge("fetch_weather_api", "read_file")
    g.add_edge("read_file", "query_db")
    g.add_edge("query_db", END)
    return g


def _run_once(
    *,
    chronos_db: Path,
    thread_id: str,
    kind_map: dict[str, NodeKind] | None,
) -> str:
    """Run the graph once; return the chronos run_id."""
    saver = InMemorySaver()
    compiled = _build_graph().compile(checkpointer=saver)

    with SqliteStore.open(chronos_db) as store:
        rec = LangGraphRecorder(store=store, kind_map=kind_map)
        cfg = {"configurable": {"thread_id": thread_id}}
        with rec.record(
            compiled,
            thread_id=thread_id,
            task_description=f"spike11 kind_map={'set' if kind_map else 'absent'}",
            tags=["spike", "spike11"],
        ) as run_ref:
            compiled.invoke({"task": "start"}, cfg)
    assert run_ref.run_id is not None
    return run_ref.run_id


def _dump(chronos_db: Path, run_id: str, label: str) -> list[tuple[str, str, list[str]]]:
    """Return [(node_name, kind, effects), ...] for a recorded run."""
    with SqliteStore.open(chronos_db) as store:
        nodes = store.get_nodes_for_run(run_id)
    print(f"\n=== {label}: run {run_id[:8]}… ({len(nodes)} nodes) ===")
    out: list[tuple[str, str, list[str]]] = []
    for n in nodes:
        effects = list(n.metadata.get("effects", []))
        print(
            f"  step={n.step_index}  kind={n.kind.value:<6}  "
            f"node_name={n.node_name!r:<26}  effects={effects}"
        )
        out.append((n.node_name, n.kind.value, effects))
    return out


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="spike11_"))
    chronos_db = tmp / "chronos.db"

    # ------------------------------------------------------------------
    # Run A — no kind_map (default FN). Shows the usage trap.
    # ------------------------------------------------------------------
    run_a = _run_once(
        chronos_db=chronos_db,
        thread_id="spike11-no-kindmap",
        kind_map=None,
    )
    rows_a = _dump(chronos_db, run_a, "Run A  (kind_map=None)")

    # ------------------------------------------------------------------
    # Run B — kind_map tags the three tool-shaped names as TOOL.
    # ------------------------------------------------------------------
    run_b = _run_once(
        chronos_db=chronos_db,
        thread_id="spike11-with-kindmap",
        kind_map={
            "fetch_weather_api": NodeKind.TOOL,
            "read_file": NodeKind.TOOL,
            "query_db": NodeKind.TOOL,
        },
    )
    rows_b = _dump(chronos_db, run_b, "Run B  (kind_map declares 3 TOOLs)")

    # ------------------------------------------------------------------
    # F1: LangGraph node_name is single-segment and equals the add_node key.
    # ------------------------------------------------------------------
    expected_names = {"plan", "fetch_weather_api", "read_file", "query_db"}
    seen_a = {name for name, _, _ in rows_a}
    if seen_a == expected_names and all(":" not in n for n in seen_a):
        print(
            f"\n[F1 ✅] LangGraph node_name is single-segment and function-shaped: {sorted(seen_a)}"
        )
    else:
        print(f"\n[F1 ❌] Unexpected node_name shape: {sorted(seen_a)}")
        return

    # ------------------------------------------------------------------
    # F2: Without kind_map → every node effects=[] (usage trap).
    # ------------------------------------------------------------------
    non_empty_a = [(n, e) for n, _k, e in rows_a if e]
    if not non_empty_a:
        print(
            "[F2 ✅] Without kind_map, every node effects=[] — confirms the "
            "classifier's TOOL-gate skips FN-defaulted nodes even when their "
            "name looks tool-shaped. ⚠️ LangGraph usage gotcha."
        )
    else:
        print(f"[F2 ❌] Expected all effects=[] without kind_map; got: {non_empty_a}")
        return

    # ------------------------------------------------------------------
    # F3: With kind_map → each tool node gets the right tag.
    # ------------------------------------------------------------------
    by_name_b = {n: (k, e) for n, k, e in rows_b}
    expected = {
        "fetch_weather_api": ("tool", ["network"]),
        "read_file": ("tool", ["fs"]),
        "query_db": ("tool", ["db"]),
        "plan": ("fn", []),  # plan is not in kind_map → FN → effects=[]
    }
    all_ok = True
    for name, (want_kind, want_effects) in expected.items():
        got_kind, got_effects = by_name_b.get(name, ("?", []))
        ok = got_kind == want_kind and got_effects == want_effects
        print(
            f"  - {name!r}: kind={got_kind} effects={got_effects} "
            f"(want kind={want_kind} effects={want_effects}) "
            f"{'✅' if ok else '❌'}"
        )
        all_ok = all_ok and ok
    if all_ok:
        print(
            "[F3 ✅] With kind_map declaring TOOL on function-named nodes, "
            "classifier returns correct effect tags."
        )
    else:
        print("[F3 ❌] At least one tool node got wrong effects — see per-row above.")
        return

    # ------------------------------------------------------------------
    # F4: LangGraph is vacuously ADR-020-compliant.
    # ------------------------------------------------------------------
    # ADR-020 requires: classifier's input contains the tool function name.
    # LangGraph's node_name IS the tool function name (by graph construction).
    # So the invariant holds without any three-segment surgery.
    tool_rows_b = [(n, e) for n, k, e in rows_b if k == "tool"]
    vacuous_ok = all(e for _, e in tool_rows_b) and len(tool_rows_b) == 3
    if vacuous_ok:
        print(
            "[F4 ✅] ADR-020 vacuously satisfied for LangGraph: "
            "node_name is single-segment function-shaped and the classifier "
            "sees the tool name directly. No three-segment surgery required."
        )
    else:
        print("[F4 ❌] Expected all 3 tool nodes to get non-empty effects — investigate.")
        return

    print()
    print("=" * 72)
    print("SPIKE 11 RESULT: LangGraph adapter is ADR-020-compliant (vacuous).")
    print("=" * 72)
    print("  - Confirms the code-reading claim in ADR-020 §'Graph-based adapters'.")
    print("  - Documents the kind_map usage gotcha for inclusion in research note.")
    print("  - No adapter code change needed for LangGraph.")


if __name__ == "__main__":
    main()
