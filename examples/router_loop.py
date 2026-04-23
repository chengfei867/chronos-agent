"""Chronos example 2 — router + tool loop (non-linear graph).

Scenario:
    A "planner" LLM decides up to N times whether the task is "done"
    or needs one more "research" round. This is the classic agent
    pattern (think ReAct): the same node name (``research``) appears
    multiple times in the trace, and the fork shortens or lengthens
    the loop.

This example exercises the diff aligner on repeated node names —
exactly the case that Spike 7 / ADR-006 validated. In particular, a
fork that forces the loop to exit one iteration early produces a
trace where ``research`` appears fewer times in the child; the diff
aligner (``difflib.SequenceMatcher``) must pair loop iterations in
order, not conflate them.

Run:
    uv run python examples/router_loop.py

Then inspect:
    chronos runs list --db examples/chronos.db
    chronos diff <parent> <fork_child> --db examples/chronos.db

No API key required — uses the deterministic ``FakeLLM``.
"""

from __future__ import annotations

import sys
from operator import add
from pathlib import Path
from typing import Annotated

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from chronos.adapters import LangGraphRecorder
from chronos.adapters.langgraph_usage import UsageContext, UsageResult
from chronos.core.models import NodeKind
from chronos.store import SqliteStore
from examples._fake_llm import FakeLLM

# How many research rounds the baseline run does before the planner
# decides the task is done. Picked to make the diff visually
# interesting but not overwhelming.
MAX_ROUNDS = 3


class LoopState(TypedDict):
    task: str
    rounds: int
    notes: Annotated[list[str], add]
    decision: str
    answer: str


_LLM = FakeLLM(seed="router-loop")


def node_plan(state: LoopState) -> dict[str, object]:
    resp = _LLM.call("You are a planner.", state["task"])
    return {"notes": [f"plan:{resp.fingerprint}"]}


def node_research(state: LoopState) -> dict[str, object]:
    rounds = state.get("rounds", 0) + 1
    resp = _LLM.call(
        "You are a researcher.",
        f"round={rounds} task={state['task']}",
    )
    return {
        "rounds": rounds,
        "notes": [f"research:{rounds}:{resp.fingerprint}"],
    }


def node_router(state: LoopState) -> dict[str, object]:
    """Planner decides: keep researching, or finalize?"""
    decision = "finalize" if state.get("rounds", 0) >= MAX_ROUNDS else "research"
    return {
        "decision": decision,
        "notes": [f"router:{decision}"],
    }


def node_finalize(state: LoopState) -> dict[str, object]:
    resp = _LLM.call("You are an editor.", "\n".join(state["notes"]))
    return {
        "answer": resp.content,
        "notes": [f"finalize:{resp.fingerprint}"],
    }


def _route(state: LoopState) -> str:
    return state["decision"]


def build_graph() -> StateGraph:
    g = StateGraph(LoopState)
    g.add_node("plan", node_plan)
    g.add_node("research", node_research)
    g.add_node("router", node_router)
    g.add_node("finalize", node_finalize)
    g.add_edge(START, "plan")
    g.add_edge("plan", "research")
    g.add_edge("research", "router")
    g.add_conditional_edges(
        "router",
        _route,
        {"research": "research", "finalize": "finalize"},
    )
    g.add_edge("finalize", END)
    return g


NODE_KIND_MAP = {
    "plan": NodeKind.LLM,
    "research": NodeKind.LLM,
    "router": NodeKind.ROUTER,
    "finalize": NodeKind.LLM,
}


# Demo usage extractor (ADR-009) — routers are rule-based so we skip them,
# while LLM nodes get toy token + cost numbers proportional to state size.
# Real projects read AIMessage.usage_metadata instead.
_TOKENS_PER_NODE = {"plan": 120, "research": 450, "finalize": 300}


def _demo_usage_extractor(ctx: UsageContext) -> UsageResult | None:
    if ctx.node_name == "router":
        # Rule-based node — no LLM call, no usage.
        return None
    base = _TOKENS_PER_NODE.get(ctx.node_name, 100)
    prompt = base
    completion = max(1, base // 3)
    # Pretend $3/1M prompt + $15/1M completion, rounded to cents.
    cost_cents = round((prompt * 3 + completion * 15) / 10_000)
    return UsageResult(
        prompt_tokens=prompt,
        completion_tokens=completion,
        cost_usd_cents=cost_cents,
        model_name="fake-llm-v1",
    )


def run_demo(db_path: Path) -> tuple[str, str]:
    """Record a 3-round baseline, fork after round 1 forcing early exit.

    The fork overrides ``rounds`` at the router snapshot to
    ``MAX_ROUNDS`` so the router immediately routes to ``finalize``
    instead of looping another time. The child run's trace is
    noticeably shorter — the aligner should report two iterations of
    ``research`` and one ``router`` as REMOVED relative to the
    parent.
    """
    saver = InMemorySaver()
    graph = build_graph().compile(checkpointer=saver)

    initial: LoopState = {
        "task": "Write a two-sentence summary of why time-travel debugging matters.",
        "rounds": 0,
        "notes": [],
        "decision": "",
        "answer": "",
    }

    with SqliteStore.open(db_path) as store:
        recorder = LangGraphRecorder(
            store,
            kind_map=NODE_KIND_MAP,
            usage_extractor=_demo_usage_extractor,  # ADR-009
        )

        # --- Parent run (3 research rounds) ---
        with recorder.record(
            graph,
            thread_id="loop-parent",
            task_description=initial["task"],
            tags=["example", "router-loop", "parent"],
        ) as parent_ref:
            graph.invoke(initial, {"configurable": {"thread_id": "loop-parent"}})
        parent_run_id = parent_ref.run_id
        assert parent_run_id is not None

        # Find the FIRST research snapshot. We fork after the first
        # research round, bumping ``rounds`` to MAX_ROUNDS so the
        # next router evaluation routes to ``finalize`` instead of
        # looping for two more research rounds.
        #
        # Forking at the research node (not the router node) avoids
        # a LangGraph subtlety: if you fork exactly at a conditional-
        # edge node, LangGraph re-evaluates the edge on ``update_state``
        # using the seeded state — so any override you apply has to
        # be ready for that immediate re-evaluation.
        nodes = store.get_nodes_for_run(parent_run_id)
        first_research = next(n for n in nodes if n.node_name == "research")

        # --- Fork: bump ``rounds`` so the router exits early ---
        with recorder.fork(
            graph,
            parent_run_id=parent_run_id,
            at_node_id=first_research.id,
            overrides={
                # Pretend we've already done MAX_ROUNDS of research.
                "rounds": MAX_ROUNDS,
                # Clear downstream so re-execution fills fresh.
                "decision": "",
                "answer": "",
            },
            child_thread_id="loop-fork",
            reason="bump rounds to force router early-exit",
            tags=["example", "router-loop", "fork", "early-exit"],
        ) as fork_ref:
            graph.invoke(None, {"configurable": {"thread_id": "loop-fork"}})
        child_run_id = fork_ref.child_run_id
        assert child_run_id is not None

    return parent_run_id, child_run_id


def _print_next_steps(db_path: Path, parent_id: str, child_id: str) -> None:
    print()
    print("=" * 72)
    print("Chronos router-loop example — demo complete ✅")
    print("=" * 72)
    print()
    print(f"DB            : {db_path}")
    print(f"Parent run    : {parent_id}  (3 research rounds)")
    print(f"Fork child run: {child_id}  (forced early exit after round 1)")
    print()
    print("Try these commands (note the REMOVED loop iterations in the diff):")
    print()
    print(f"  chronos runs list --db {db_path}")
    print(f"  chronos runs list --db {db_path} --with-usage")
    print(f"  chronos runs show {parent_id} --db {db_path}")
    print(f"  chronos replay {parent_id} --db {db_path} --no-interactive")
    print(f"  chronos diff {parent_id} {child_id} --db {db_path}")
    print(f"  chronos diff {parent_id} {child_id} --db {db_path} --show-usage")
    print(f"  chronos diff {parent_id} {child_id} --db {db_path} --full")
    print(
        f"  chronos fork plan {parent_id} --at-index 0 --allow-new-keys "
        f"--reason demo --out /tmp/router_fork_plan.json --db {db_path}"
    )
    print()


if __name__ == "__main__":
    here = Path(__file__).resolve().parent
    db = here / "chronos.db"
    if db.exists():
        db.unlink()
    parent, child = run_demo(db)
    _print_next_steps(db, parent, child)
