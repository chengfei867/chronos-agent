"""Smoke tests for the scripts under ``examples/``.

These are cheap: each ``run_demo`` uses the deterministic FakeLLM and
an in-memory saver, so they execute in well under a second. The goal
is not to re-validate the adapter internals (that's what
``tests/unit/test_adapter_*`` does) but to catch regressions where a
cosmetic CLI change breaks a public-facing example.
"""

from __future__ import annotations

from pathlib import Path

from examples import linear_pipeline, router_loop

from chronos.core.diff import diff_runs
from chronos.store.sqlite import SqliteStore


def test_linear_pipeline_records_and_forks(tmp_path: Path) -> None:
    """End-to-end: record → fork → diff on the linear pipeline example."""
    db = tmp_path / "chronos.db"
    parent_id, child_id = linear_pipeline.run_demo(db)

    assert parent_id
    assert child_id
    assert parent_id != child_id

    with SqliteStore.open(db) as store:
        parent_nodes = store.get_nodes_for_run(parent_id)
        child_nodes = store.get_nodes_for_run(child_id)

        # Baseline: 5 nodes (plan, research, draft, review, finalize).
        assert [n.node_name for n in parent_nodes] == [
            "plan",
            "research",
            "draft",
            "review",
            "finalize",
        ]
        # Fork child re-executes from research onwards.
        # We accept either 5 (re-walk from plan seed) or 4 (post-research)
        # depending on how LangGraph threads the seeded state back through
        # the graph; the important invariant is the last node is finalize.
        assert child_nodes, "fork child should have at least one node"
        assert child_nodes[-1].node_name == "finalize"

        # Diff: fork-aware slicing should find at least one CHANGED node.
        report = diff_runs(store, parent_id, child_id)
        changed = [e for e in report.entries if e.tag == "changed"]
        assert changed, (
            f"expected fork diff to find CHANGED nodes, got {report.summary!r}"
        )


def test_router_loop_records_and_forks(tmp_path: Path) -> None:
    """End-to-end: record → fork (early-exit) → diff on the router-loop example."""
    db = tmp_path / "chronos.db"
    parent_id, child_id = router_loop.run_demo(db)

    assert parent_id
    assert child_id

    with SqliteStore.open(db) as store:
        parent_nodes = store.get_nodes_for_run(parent_id)
        child_nodes = store.get_nodes_for_run(child_id)

        # Parent loops the research→router pair MAX_ROUNDS times. Child
        # forces early exit, so the child trace must be shorter.
        assert len(child_nodes) < len(parent_nodes), (
            f"child ({len(child_nodes)}) should be shorter than parent "
            f"({len(parent_nodes)}) after forced early exit"
        )
        # Both runs must still end at finalize.
        assert parent_nodes[-1].node_name == "finalize"
        assert child_nodes[-1].node_name == "finalize"

        # Diff: expect at least one REMOVED node (the dropped loop iterations).
        report = diff_runs(store, parent_id, child_id)
        removed = [e for e in report.entries if e.tag == "removed"]
        assert removed, (
            f"expected fork diff to find REMOVED nodes (loop iterations "
            f"dropped by early exit), got {report.summary!r}"
        )
