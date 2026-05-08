"""Shared synthetic fixtures for N-run compare tests (R58, Arc A).

These helpers build three (or more) runs + their DiffReport(pivot, other)
without touching a real store. They exist as a dedicated module because
R58 (``merge_pivot_reports``), R59 (CLI + API wrappers), and R61
(dogfood scripts) all need the same shape.

Design doc reference: ``docs/design/n-run-compare.md`` §4, §5.1, §7.1.

The fixtures are intentionally tiny — a 3- or 5-step pivot and a handful
of others. The point is algorithm correctness on each edge case, not
performance.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from chronos.core.diff import DiffEntry, DiffReport, StateDiff
from chronos.core.models import Node, NodeKind, Run, RunStatus

T0 = datetime(2026, 5, 9, 3, 0, 0, tzinfo=UTC)


def mk_node(
    *,
    run_id: str,
    step: int,
    name: str,
    state: dict[str, Any] | None = None,
    nid: str | None = None,
    kind: NodeKind = NodeKind.FN,
) -> Node:
    """Build a ``Node`` with deterministic ids."""
    return Node(
        id=nid or f"{run_id}-n-{step}",
        run_id=run_id,
        step_index=step,
        node_name=name,
        kind=kind,
        started_at=T0,
        ended_at=T0,
        state_after=state or {},
    )


def mk_run(run_id: str, *, adapter: str = "langgraph", task: str = "t") -> Run:
    """Build a ``Run`` instance mirroring the pattern used in test_diff.py."""
    return Run(
        id=run_id,
        adapter=adapter,
        adapter_thread_id=f"thr-{run_id}",
        status=RunStatus.COMPLETED,
        started_at=T0,
        ended_at=T0,
        task_description=task,
    )


def _equal_entry(a: Node, b: Node) -> DiffEntry:
    return DiffEntry(tag="equal", node_name=a.node_name, a=a, b=b, state_diff=None)


def _changed_entry(a: Node, b: Node, state_diff: StateDiff | None = None) -> DiffEntry:
    if state_diff is None:
        state_diff = StateDiff(changed_keys={"x": {"a": a.state_after, "b": b.state_after}})
    return DiffEntry(tag="changed", node_name=a.node_name, a=a, b=b, state_diff=state_diff)


def _removed_entry(a: Node) -> DiffEntry:
    return DiffEntry(tag="removed", node_name=a.node_name, a=a, b=None)


def _added_entry(b: Node) -> DiffEntry:
    return DiffEntry(tag="added", node_name=b.node_name, a=None, b=b)


# ---------------------------------------------------------------------------
# Canonical 3-run pivot fixture generators
# ---------------------------------------------------------------------------


def three_run_all_equal() -> tuple[Run, list[Run], list[DiffReport]]:
    """Three identical langgraph runs; every diff entry is equal.

    Pivot has 3 steps: start / plan / draft.
    """
    pivot = mk_run("P")
    b = mk_run("B")
    c = mk_run("C")

    # Build per-run nodes (states are identical).
    p_nodes = [
        mk_node(run_id="P", step=0, name="start", state={"x": 0}),
        mk_node(run_id="P", step=1, name="plan", state={"x": 1}),
        mk_node(run_id="P", step=2, name="draft", state={"x": 2}),
    ]
    b_nodes = [
        mk_node(run_id="B", step=0, name="start", state={"x": 0}),
        mk_node(run_id="B", step=1, name="plan", state={"x": 1}),
        mk_node(run_id="B", step=2, name="draft", state={"x": 2}),
    ]
    c_nodes = [
        mk_node(run_id="C", step=0, name="start", state={"x": 0}),
        mk_node(run_id="C", step=1, name="plan", state={"x": 1}),
        mk_node(run_id="C", step=2, name="draft", state={"x": 2}),
    ]

    rep_b = DiffReport(
        run_a=pivot,
        run_b=b,
        entries=[_equal_entry(p_nodes[i], b_nodes[i]) for i in range(3)],
    )
    rep_c = DiffReport(
        run_a=pivot,
        run_b=c,
        entries=[_equal_entry(p_nodes[i], c_nodes[i]) for i in range(3)],
    )
    return pivot, [b, c], [rep_b, rep_c]


def three_run_b_changed_step2_c_changed_step3() -> tuple[Run, list[Run], list[DiffReport]]:
    """4-step pivot (start/plan/draft/refine). B diverges at step 2
    (draft); C diverges at step 3 (refine).
    """
    pivot = mk_run("P")
    b = mk_run("B")
    c = mk_run("C")

    p_nodes = [
        mk_node(run_id="P", step=0, name="start", state={"x": 0}),
        mk_node(run_id="P", step=1, name="plan", state={"x": 1}),
        mk_node(run_id="P", step=2, name="draft", state={"x": 2}),
        mk_node(run_id="P", step=3, name="refine", state={"x": 3}),
    ]
    b_nodes = [
        mk_node(run_id="B", step=0, name="start", state={"x": 0}),
        mk_node(run_id="B", step=1, name="plan", state={"x": 1}),
        mk_node(run_id="B", step=2, name="draft", state={"x": 99}),  # changed
        mk_node(run_id="B", step=3, name="refine", state={"x": 3}),
    ]
    c_nodes = [
        mk_node(run_id="C", step=0, name="start", state={"x": 0}),
        mk_node(run_id="C", step=1, name="plan", state={"x": 1}),
        mk_node(run_id="C", step=2, name="draft", state={"x": 2}),
        mk_node(run_id="C", step=3, name="refine", state={"x": 42}),  # changed
    ]

    rep_b = DiffReport(
        run_a=pivot,
        run_b=b,
        entries=[
            _equal_entry(p_nodes[0], b_nodes[0]),
            _equal_entry(p_nodes[1], b_nodes[1]),
            _changed_entry(p_nodes[2], b_nodes[2]),
            _equal_entry(p_nodes[3], b_nodes[3]),
        ],
    )
    rep_c = DiffReport(
        run_a=pivot,
        run_b=c,
        entries=[
            _equal_entry(p_nodes[0], c_nodes[0]),
            _equal_entry(p_nodes[1], c_nodes[1]),
            _equal_entry(p_nodes[2], c_nodes[2]),
            _changed_entry(p_nodes[3], c_nodes[3]),
        ],
    )
    return pivot, [b, c], [rep_b, rep_c]


def three_run_b_and_c_both_insert_same_position() -> tuple[
    Run, list[Run], list[DiffReport]
]:
    """Pivot has 3 steps. Both B and C add a ``refine`` step between
    pivot step 1 and step 2. These inserts should merge into a single
    alignment row.
    """
    pivot = mk_run("P")
    b = mk_run("B")
    c = mk_run("C")

    p_nodes = [
        mk_node(run_id="P", step=0, name="start", state={"x": 0}),
        mk_node(run_id="P", step=1, name="plan", state={"x": 1}),
        mk_node(run_id="P", step=2, name="draft", state={"x": 2}),
    ]
    b_nodes = [
        mk_node(run_id="B", step=0, name="start", state={"x": 0}),
        mk_node(run_id="B", step=1, name="plan", state={"x": 1}),
        mk_node(run_id="B", step=2, name="refine", state={"x": 50}),  # inserted
        mk_node(run_id="B", step=3, name="draft", state={"x": 2}),
    ]
    c_nodes = [
        mk_node(run_id="C", step=0, name="start", state={"x": 0}),
        mk_node(run_id="C", step=1, name="plan", state={"x": 1}),
        mk_node(run_id="C", step=2, name="refine", state={"x": 51}),  # inserted
        mk_node(run_id="C", step=3, name="draft", state={"x": 2}),
    ]

    rep_b = DiffReport(
        run_a=pivot,
        run_b=b,
        entries=[
            _equal_entry(p_nodes[0], b_nodes[0]),
            _equal_entry(p_nodes[1], b_nodes[1]),
            _added_entry(b_nodes[2]),
            _equal_entry(p_nodes[2], b_nodes[3]),
        ],
    )
    rep_c = DiffReport(
        run_a=pivot,
        run_b=c,
        entries=[
            _equal_entry(p_nodes[0], c_nodes[0]),
            _equal_entry(p_nodes[1], c_nodes[1]),
            _added_entry(c_nodes[2]),
            _equal_entry(p_nodes[2], c_nodes[3]),
        ],
    )
    return pivot, [b, c], [rep_b, rep_c]


def three_run_b_removed_step2() -> tuple[Run, list[Run], list[DiffReport]]:
    """Pivot has 3 steps. B removes the middle step; C is identical."""
    pivot = mk_run("P")
    b = mk_run("B")
    c = mk_run("C")

    p_nodes = [
        mk_node(run_id="P", step=0, name="start", state={"x": 0}),
        mk_node(run_id="P", step=1, name="plan", state={"x": 1}),
        mk_node(run_id="P", step=2, name="draft", state={"x": 2}),
    ]
    b_nodes = [
        mk_node(run_id="B", step=0, name="start", state={"x": 0}),
        mk_node(run_id="B", step=1, name="draft", state={"x": 2}),
    ]
    c_nodes = [
        mk_node(run_id="C", step=0, name="start", state={"x": 0}),
        mk_node(run_id="C", step=1, name="plan", state={"x": 1}),
        mk_node(run_id="C", step=2, name="draft", state={"x": 2}),
    ]

    rep_b = DiffReport(
        run_a=pivot,
        run_b=b,
        entries=[
            _equal_entry(p_nodes[0], b_nodes[0]),
            _removed_entry(p_nodes[1]),
            _equal_entry(p_nodes[2], b_nodes[1]),
        ],
    )
    rep_c = DiffReport(
        run_a=pivot,
        run_b=c,
        entries=[
            _equal_entry(p_nodes[0], c_nodes[0]),
            _equal_entry(p_nodes[1], c_nodes[1]),
            _equal_entry(p_nodes[2], c_nodes[2]),
        ],
    )
    return pivot, [b, c], [rep_b, rep_c]


def three_run_adapter_mismatch() -> tuple[Run, list[Run], list[DiffReport]]:
    """Pivot=langgraph; B=langgraph (matching); C=crewai (mismatched)."""
    pivot = mk_run("P", adapter="langgraph")
    b = mk_run("B", adapter="langgraph")
    c = mk_run("C", adapter="crewai")

    p_nodes = [mk_node(run_id="P", step=0, name="start", state={"x": 0})]
    b_nodes = [mk_node(run_id="B", step=0, name="start", state={"x": 0})]
    c_nodes = [mk_node(run_id="C", step=0, name="kickoff", state={"x": 0})]

    rep_b = DiffReport(
        run_a=pivot,
        run_b=b,
        entries=[_equal_entry(p_nodes[0], b_nodes[0])],
    )
    rep_c = DiffReport(
        run_a=pivot,
        run_b=c,
        entries=[
            _removed_entry(p_nodes[0]),
            _added_entry(c_nodes[0]),
        ],
    )
    return pivot, [b, c], [rep_b, rep_c]


def n_run_all_equal(n: int) -> tuple[Run, list[Run], list[DiffReport]]:
    """Generic N-run all-equal fixture; pivot has 5 steps."""
    if n < 2:
        raise ValueError("n must be >= 2")
    pivot = mk_run("P")
    others = [mk_run(f"O{i}") for i in range(n - 1)]
    p_nodes = [
        mk_node(run_id="P", step=i, name=f"step{i}", state={"x": i}) for i in range(5)
    ]
    reports: list[DiffReport] = []
    for o in others:
        o_nodes = [
            mk_node(run_id=o.id, step=i, name=f"step{i}", state={"x": i}) for i in range(5)
        ]
        reports.append(
            DiffReport(
                run_a=pivot,
                run_b=o,
                entries=[_equal_entry(p_nodes[i], o_nodes[i]) for i in range(5)],
            )
        )
    return pivot, others, reports


def two_run_wrap(
    fixture_fn: Any,
) -> tuple[Run, list[Run], list[DiffReport]]:
    """Take a 3-run fixture and keep only the first other run (N=2 case)."""
    pivot, others, reports = fixture_fn()
    return pivot, others[:1], reports[:1]


__all__ = [
    "mk_node",
    "mk_run",
    "n_run_all_equal",
    "three_run_adapter_mismatch",
    "three_run_all_equal",
    "three_run_b_and_c_both_insert_same_position",
    "three_run_b_changed_step2_c_changed_step3",
    "three_run_b_removed_step2",
    "two_run_wrap",
]
