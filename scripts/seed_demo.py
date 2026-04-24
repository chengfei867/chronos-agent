"""Minimal seed script — inserts demo runs/nodes so the viewer has data to show
in smoke tests. Not shipped as part of the public package.
"""

from __future__ import annotations

import argparse
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from chronos.core.models import Fork, Node, NodeKind, Run, RunStatus, Usage
from chronos.store.sqlite import SqliteStore


def _now(offset_sec: float = 0.0) -> datetime:
    return datetime.now(UTC) + timedelta(seconds=offset_sec)


def seed(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    store = SqliteStore.open(db_path)

    # --- Run 1: completed LangGraph task with 5 nodes ---
    run1 = Run(
        id=f"run_{uuid.uuid4().hex[:12]}",
        adapter="langgraph",
        adapter_thread_id="thread_demo_1",
        status=RunStatus.COMPLETED,
        started_at=_now(-600),
        ended_at=_now(-420),
        task_description="Plan a weekend trip to Tokyo",
        initial_state={"destination": "Tokyo", "days": 3},
        final_state={"itinerary": ["Shibuya", "Asakusa", "Akihabara"]},
        tags=["demo", "travel"],
        metadata={},
    )
    store.put_run(run1)

    node_specs: list[tuple[NodeKind, str, str | None]] = [
        (NodeKind.LLM, "plan_agent", "gpt-4o"),
        (NodeKind.TOOL, "search_places", None),
        (NodeKind.LLM, "summarize_results", "gpt-4o"),
        (NodeKind.ROUTER, "decide_next", None),
        (NodeKind.END, "finish", None),
    ]
    parent_id: str | None = None
    for i, (kind, name, model) in enumerate(node_specs):
        nid = f"node_{uuid.uuid4().hex[:12]}"
        node = Node(
            id=nid,
            run_id=run1.id,
            step_index=i,
            node_name=name,
            kind=kind,
            parent_node_id=parent_id,
            started_at=_now(-600 + i * 30),
            ended_at=_now(-600 + i * 30 + 20),
            state_after={"step": i, "last": name},
            model_name=model,
            usage=(
                Usage(prompt_tokens=120 + i * 20, completion_tokens=80, total_tokens=200 + i * 20)
                if model
                else None
            ),
            cost_usd_cents=(8 + i * 2) if model else None,
            tool_name="places_api" if kind == NodeKind.TOOL else None,
            tool_input={"query": "things to do in tokyo"} if kind == NodeKind.TOOL else None,
            tool_output={"results": ["Shibuya", "Asakusa"]} if kind == NodeKind.TOOL else None,
            error_message=None,
            metadata={},
        )
        store.put_node(node)
        parent_id = nid

    # --- Run 2: failed AutoGen run ---
    run2 = Run(
        id=f"run_{uuid.uuid4().hex[:12]}",
        adapter="autogen",
        adapter_thread_id="thread_demo_2",
        status=RunStatus.FAILED,
        started_at=_now(-300),
        ended_at=_now(-290),
        task_description="Scrape a login-gated page",
        initial_state={"url": "https://example.com/private"},
        final_state=None,
        tags=["demo"],
        metadata={},
    )
    store.put_run(run2)
    fail_specs: list[tuple[NodeKind, str, str | None]] = [
        (NodeKind.TOOL, "fetch_page", None),
        (NodeKind.LLM, "classify_error", None),
        (NodeKind.END, "fail", "401 Unauthorized"),
    ]
    parent_id = None
    for i, (kind, name, err) in enumerate(fail_specs):
        nid = f"node_{uuid.uuid4().hex[:12]}"
        node = Node(
            id=nid,
            run_id=run2.id,
            step_index=i,
            node_name=name,
            kind=kind,
            parent_node_id=parent_id,
            started_at=_now(-300 + i * 3),
            ended_at=_now(-300 + i * 3 + 2),
            state_after={"step": i},
            error_message=err,
        )
        store.put_node(node)
        parent_id = nid

    # --- Run 3: running linear ---
    run3 = Run(
        id=f"run_{uuid.uuid4().hex[:12]}",
        adapter="linear",
        adapter_thread_id="thread_demo_3",
        status=RunStatus.RUNNING,
        started_at=_now(-60),
        ended_at=None,
        task_description="Generate a weekly status report",
        initial_state={"team": "eng"},
        final_state=None,
        tags=["demo", "report"],
        metadata={},
    )
    store.put_run(run3)

    # --- Run 4: fork of run 1 at the search_places node with a revised query.
    # Demonstrates the "time-travel branching" story: same head, divergent
    # continuation after editing a single step's input.
    run1_nodes = store.get_nodes_for_run(run1.id)
    fork_parent_node_id: str = next(n.id for n in run1_nodes if n.node_name == "search_places")

    run4 = Run(
        id=f"run_{uuid.uuid4().hex[:12]}",
        adapter="langgraph",
        adapter_thread_id="thread_demo_4",
        status=RunStatus.COMPLETED,
        started_at=_now(-400),
        ended_at=_now(-300),
        task_description="Re-plan Tokyo trip with 5 days instead of 3",
        initial_state={"destination": "Tokyo", "days": 5},
        final_state={"itinerary": ["Shibuya", "Asakusa", "Akihabara", "Ueno", "Odaiba"]},
        tags=["demo", "travel", "fork"],
        metadata={},
    )
    store.put_run(run4)

    fork_specs_4: list[tuple[NodeKind, str, str | None]] = [
        (NodeKind.TOOL, "search_places_wider", None),
        (NodeKind.LLM, "summarize_with_5days", "gpt-4o"),
        (NodeKind.ROUTER, "decide_next_v2", None),
        (NodeKind.END, "finish", None),
    ]
    parent_id = fork_parent_node_id
    run4_router_node_id: str | None = None
    for i, (kind, name, model) in enumerate(fork_specs_4):
        nid = f"node_{uuid.uuid4().hex[:12]}"
        if i == 0:
            pass
        if kind == NodeKind.ROUTER:
            run4_router_node_id = nid
        node = Node(
            id=nid,
            run_id=run4.id,
            step_index=i,
            node_name=name,
            kind=kind,
            parent_node_id=parent_id,
            started_at=_now(-400 + i * 25),
            ended_at=_now(-400 + i * 25 + 18),
            state_after={"step": i, "days": 5, "last": name},
            model_name=model,
            usage=(
                Usage(prompt_tokens=140 + i * 15, completion_tokens=90, total_tokens=230 + i * 15)
                if model
                else None
            ),
            cost_usd_cents=(9 + i * 2) if model else None,
            metadata={},
        )
        store.put_node(node)
        parent_id = nid

    store.put_fork(
        Fork(
            id=f"fork_{uuid.uuid4().hex[:12]}",
            parent_run_id=run1.id,
            parent_node_id=fork_parent_node_id,
            child_run_id=run4.id,
            created_at=_now(-400),
            edited_fields={"days": 5, "query": "things to do in tokyo 5 days"},
            reason="Traveler has 5 days, not 3",
        )
    )

    # --- Run 5: fork of run 4 at the router node — cheaper model variant.
    # Creates a 3-generation tree: run1 → run4 → run5.
    assert run4_router_node_id is not None
    run5 = Run(
        id=f"run_{uuid.uuid4().hex[:12]}",
        adapter="langgraph",
        adapter_thread_id="thread_demo_5",
        status=RunStatus.COMPLETED,
        started_at=_now(-200),
        ended_at=_now(-150),
        task_description="Same 5-day plan, re-ranked with a cheaper model",
        initial_state={"destination": "Tokyo", "days": 5, "model": "gpt-4o-mini"},
        final_state={"itinerary": ["Shibuya", "Ueno", "Odaiba", "Asakusa", "Akihabara"]},
        tags=["demo", "travel", "fork", "cheap"],
        metadata={},
    )
    store.put_run(run5)

    fork_specs_5: list[tuple[NodeKind, str, str | None]] = [
        (NodeKind.LLM, "rerank_cheap", "gpt-4o-mini"),
        (NodeKind.END, "finish", None),
    ]
    parent_id = run4_router_node_id
    for i, (kind, name, model) in enumerate(fork_specs_5):
        nid = f"node_{uuid.uuid4().hex[:12]}"
        if i == 0:
            pass
        store.put_node(
            Node(
                id=nid,
                run_id=run5.id,
                step_index=i,
                node_name=name,
                kind=kind,
                parent_node_id=parent_id,
                started_at=_now(-200 + i * 15),
                ended_at=_now(-200 + i * 15 + 10),
                state_after={"step": i, "last": name},
                model_name=model,
                usage=(
                    Usage(prompt_tokens=160, completion_tokens=70, total_tokens=230)
                    if model
                    else None
                ),
                cost_usd_cents=3 if model else None,
                metadata={},
            )
        )
        parent_id = nid

    store.put_fork(
        Fork(
            id=f"fork_{uuid.uuid4().hex[:12]}",
            parent_run_id=run4.id,
            parent_node_id=run4_router_node_id,
            child_run_id=run5.id,
            created_at=_now(-200),
            edited_fields={"model": "gpt-4o-mini"},
            reason="Test cheaper model for reranking",
        )
    )

    store.close()
    print(f"Seeded 5 runs into {db_path}")
    print(f"  Run 1 (completed, langgraph, fork root): {run1.id}")
    print(f"  Run 2 (failed, autogen):                  {run2.id}")
    print(f"  Run 3 (running, linear):                  {run3.id}")
    print(f"  Run 4 (fork of run 1, +2 days):           {run4.id}")
    print(f"  Run 5 (fork of run 4, cheap model):       {run5.id}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="/tmp/chronos-demo.db", type=Path)
    args = parser.parse_args()
    seed(args.db)
