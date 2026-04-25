"""Spike 8 — Side-effect behavior on a LangGraph fork.

Motivation
----------
Phase 3 roadmap item #1 says "side-effectful tool sandboxing (E2B or Modal)".
ADR-013 (R21) froze fork auto-execution: Chronos itself does not execute
forks — the user invokes their graph with the ForkPlan's overrides.

Before we spend 10-20 rounds building sandboxing, we need to empirically
answer:

  Q1. When a user re-invokes the graph on a forked checkpoint via
      `graph.invoke(None, cfg_child)`, does LangGraph re-execute nodes
      BEFORE the fork point? (If yes, side effects before the fork get
      replayed on every fork — disaster.)

  Q2. When forking at node N, do downstream nodes (N+1, N+2, ...) run
      exactly once? Any silent retries?

  Q3. What is the actual UX cost for the user of mitigating side effects
      today, given that Chronos does not sandbox? 1 line, 20 lines, or
      fundamentally impossible?

Method
------
3-node LangGraph: plan → post → final. Node `post` does
`httpx.post("https://example.com")`. We use `httpx.MockTransport` to
count calls. Then we fork at `plan` (BEFORE `post`) and re-invoke.
If LangGraph re-runs `plan` + `post` during the fork, the counter
climbs to 2. If it only runs nodes from the fork point forward, it
climbs to 2 as well — but the interesting case is forking AFTER `post`
(fork at `post` with override), where the counter should stay at 1.

Run
---
  uv run python tests/spikes/spike8_fork_sideeffect.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from chronos.adapters.langgraph import LangGraphRecorder
from chronos.store.sqlite import SqliteStore

# ---------------------------------------------------------------------------
# Tiny agent state + side-effect instrumentation
# ---------------------------------------------------------------------------


class S(TypedDict, total=False):
    task: str
    plan: str
    post_result: str
    final: str


CALL_COUNTER: dict[str, int] = {"count": 0}


def _mock_handler(request: httpx.Request) -> httpx.Response:
    CALL_COUNTER["count"] += 1
    return httpx.Response(
        200, json={"ok": True, "seen": CALL_COUNTER["count"], "url": str(request.url)}
    )


TRANSPORT = httpx.MockTransport(_mock_handler)
CLIENT = httpx.Client(transport=TRANSPORT)


# ---------------------------------------------------------------------------
# Graph: plan → post (side-effecting) → final
# ---------------------------------------------------------------------------


def plan_node(state: S) -> S:
    return {"plan": f"plan for {state['task']!r}"}


def post_node(state: S) -> S:
    resp = CLIENT.post("https://example.com/action", json={"plan": state["plan"]})
    data = resp.json()
    return {"post_result": f"sent (seen={data['seen']})"}


def final_node(state: S) -> S:
    return {"final": f"done: {state['post_result']}"}


def build_graph() -> Any:
    g: StateGraph = StateGraph(S)
    g.add_node("plan", plan_node)
    g.add_node("post", post_node)
    g.add_node("final", final_node)
    g.add_edge(START, "plan")
    g.add_edge("plan", "post")
    g.add_edge("post", "final")
    g.add_edge("final", END)
    return g


# ---------------------------------------------------------------------------
# Experiment driver
# ---------------------------------------------------------------------------


def run_experiment(db_path: Path) -> None:
    saver = InMemorySaver()
    compiled = build_graph().compile(checkpointer=saver)

    # ---- Phase 1: initial recorded run ----
    CALL_COUNTER["count"] = 0
    with SqliteStore.open(db_path) as store:
        recorder = LangGraphRecorder(store=store)

        parent_cfg = {"configurable": {"thread_id": "spike8-parent"}}
        with recorder.record(
            compiled,
            thread_id="spike8-parent",
            task_description="spike8 initial run",
        ) as run_ref:
            compiled.invoke({"task": "test side effects"}, parent_cfg)

        initial_calls = CALL_COUNTER["count"]
        parent_run_id = run_ref.run_id
        parent_nodes = store.get_nodes_for_run(parent_run_id)

    print("[Phase 1] Initial run finished.")
    print(f"  httpx calls during initial:  {initial_calls}  (expected 1)")
    print(f"  parent run_id:               {parent_run_id}")
    print(f"  parent nodes recorded:       {[n.node_name for n in parent_nodes]}")

    post_node_row = next(n for n in parent_nodes if n.node_name == "post")

    # ---- Phase 2: fork AFTER the side-effect node ("post") ----
    # Fork at 'post' means we override post's state_after, then LangGraph
    # resumes from the next node ('final'). If the checkpointer does NOT
    # re-run 'plan' or 'post', counter stays at 1.
    CALL_COUNTER["count"] = 0
    with SqliteStore.open(db_path) as store:
        recorder = LangGraphRecorder(store=store)
        with recorder.fork(
            compiled,
            parent_run_id=parent_run_id,
            at_node_id=post_node_row.id,
            overrides={"post_result": "OVERRIDDEN: pretend we sent it"},
            child_thread_id="spike8-child-after-post",
            reason="spike8: fork AFTER side-effect node",
        ) as fork_ref:
            child_cfg = {"configurable": {"thread_id": "spike8-child-after-post"}}
            child_result = compiled.invoke(None, child_cfg)

        fork_after_calls = CALL_COUNTER["count"]
        child_run_id = fork_ref.child_run_id
        child_nodes = store.get_nodes_for_run(child_run_id)

    print("\n[Phase 2] Fork AFTER 'post' (the side-effecting node)")
    print(f"  httpx calls during fork:     {fork_after_calls}  (expected 0)")
    print(f"  child final state:           {child_result}")
    print(f"  child run_id:                {child_run_id}")
    print(f"  child nodes recorded:        {[n.node_name for n in child_nodes]}")

    # ---- Phase 3: fork BEFORE the side-effect node ("plan") ----
    CALL_COUNTER["count"] = 0
    plan_node_row = next(n for n in parent_nodes if n.node_name == "plan")
    with SqliteStore.open(db_path) as store:
        recorder = LangGraphRecorder(store=store)
        with recorder.fork(
            compiled,
            parent_run_id=parent_run_id,
            at_node_id=plan_node_row.id,
            overrides={"plan": "OVERRIDDEN plan — should trigger fresh post"},
            child_thread_id="spike8-child-before-post",
            reason="spike8: fork BEFORE side-effect node",
        ) as _fork_ref2:
            child_cfg2 = {"configurable": {"thread_id": "spike8-child-before-post"}}
            child_result2 = compiled.invoke(None, child_cfg2)

        fork_before_calls = CALL_COUNTER["count"]

    print("\n[Phase 3] Fork BEFORE 'post' (i.e. at 'plan' with plan override)")
    print(f"  httpx calls during fork:     {fork_before_calls}  (expected 1 — fresh post)")
    print(f"  child final state:           {child_result2}")

    # ---- Summary ----
    print("\n" + "=" * 72)
    print("FINDINGS")
    print("=" * 72)
    print(
        f"  F1  Initial run triggers side effect exactly once:  "
        f"{'✅' if initial_calls == 1 else '❌ got ' + str(initial_calls)}"
    )
    print(
        f"  F2  Fork AFTER 'post' re-runs 'post' side effect:   "
        f"{'❌ ' + str(fork_after_calls) + ' extra calls' if fork_after_calls else '✅ no replay'}"
    )
    print(
        f"  F3  Fork BEFORE 'post' re-runs 'post' fresh:        "
        f"{'✅' if fork_before_calls == 1 else '❌ got ' + str(fork_before_calls)}"
    )
    print()
    print("INTERPRETATION")
    print("-" * 72)
    if fork_after_calls == 0 and fork_before_calls == 1:
        print("  LangGraph's checkpointer behaves exactly as ADR-005 assumes:")
        print("    - Forking at/after a node does not re-trigger its side effects.")
        print("    - Forking before a node re-executes it (by design, that's the point).")
        print()
        print("  Phase 3 roadmap implication:")
        print("    The 'side-effectful tool sandboxing (E2B / Modal)' milestone")
        print("    is only relevant for DOWNSTREAM side effects inside the NEW")
        print("    branch — which only exist if CHRONOS executes forks itself.")
        print("    ADR-013 says it doesn't. Therefore this milestone is either:")
        print("      (a) Redundant (user owns their own sandbox), OR")
        print("      (b) A signal that Phase 3 implicitly reopens ADR-013.")
        print("    If (b), the spike should be 'reopen ADR-013?', not 'pick E2B")
        print("    vs Modal'.")
    else:
        print("  Unexpected behavior — write an ADR before touching anything.")


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "spike8.db"
        print(f"spike db: {db_path}\n")
        run_experiment(db_path)


if __name__ == "__main__":
    main()
