"""Tests for ``chronos.core.auto_pivot`` (Phase 4 Arc A slice 4, R62).

Covers:

* :func:`compute_distance` boundary behaviour (identical, fully divergent,
  symmetry under added/removed swap, empty report).
* :func:`pairwise_distances` shape / symmetry / determinism + input
  validation.
* :func:`select_centroid` algorithmic correctness (clear centroid, outlier
  detection, lexicographic tie-break, N=2 degenerate).
* :func:`auto_pivot_compare` end-to-end: N=2 contract compatibility with
  :func:`merge_pivot_reports`, N=3 / N=4 with known expected centroid,
  metadata shape, and duplicate / under-sized input rejection.

Per R59 invariant "new fixture new scenario": this module builds its own
:class:`_FakeStore` + ``_build_run`` helpers rather than reusing
``tests/unit/fixtures/three_run_pivot.py`` (whose fixtures return
prebuilt ``DiffReport``\\ s rather than a store, since R58's
``merge_pivot_reports`` operated on reports directly). Here we need a
**store** because ``auto_pivot_compare`` calls ``diff_runs`` internally.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from chronos.core.auto_pivot import (
    METRIC_VERSION,
    AutoPivotReport,
    auto_pivot_compare,
    compute_distance,
    pairwise_distances,
    select_centroid,
)
from chronos.core.diff import DiffEntry, DiffReport, DiffRunNotFoundError, merge_pivot_reports
from chronos.core.models import Fork, Node, NodeKind, Run, RunStatus

T0 = datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers: a minimal in-memory store implementing the ``_AutoPivotStore``
# protocol so we can drive ``auto_pivot_compare`` without SQLite / ORM.
# ---------------------------------------------------------------------------


def _mk_run(run_id: str, adapter: str = "langgraph") -> Run:
    return Run(
        id=run_id,
        adapter=adapter,
        adapter_thread_id=f"thr-{run_id}",
        status=RunStatus.COMPLETED,
        started_at=T0,
        ended_at=T0,
        task_description="t",
    )


def _mk_node(run_id: str, step: int, name: str, state: dict[str, Any] | None = None) -> Node:
    return Node(
        id=f"{run_id}-n-{step}",
        run_id=run_id,
        step_index=step,
        node_name=name,
        kind=NodeKind.FN,
        started_at=T0,
        ended_at=T0,
        state_after=state or {},
    )


class _FakeStore:
    """In-memory store with the minimum surface ``diff_runs`` needs."""

    def __init__(self, runs: dict[str, Run], nodes: dict[str, list[Node]]) -> None:
        self._runs = runs
        self._nodes = nodes

    def get_run(self, run_id: str) -> Run | None:
        return self._runs.get(run_id)

    def get_nodes_for_run(self, run_id: str) -> list[Node]:
        return list(self._nodes.get(run_id, []))

    def get_fork_for_child(self, child_run_id: str) -> Fork | None:
        # No forks in these fixtures — every run is independent.
        return None


def _build_uniform_run(run_id: str, values: list[int]) -> tuple[Run, list[Node]]:
    """Build a run with steps ``start``, ``plan``, ``draft``, ... and
    ``state={'x': values[i]}`` at each step. Node names are shared across
    runs (so alignment matches structurally) but ``state_after`` varies.
    """
    # Generic ``step{i}`` names keep the fixture unbounded in N while still
    # aligning structurally across runs (SequenceMatcher matches by name).
    nodes = [
        _mk_node(run_id=run_id, step=i, name=f"step{i}", state={"x": v})
        for i, v in enumerate(values)
    ]
    return _mk_run(run_id), nodes


def _build_store(*run_specs: tuple[str, list[int]]) -> _FakeStore:
    runs: dict[str, Run] = {}
    nodes: dict[str, list[Node]] = {}
    for rid, values in run_specs:
        r, ns = _build_uniform_run(rid, values)
        runs[rid] = r
        nodes[rid] = ns
    return _FakeStore(runs, nodes)


# ---------------------------------------------------------------------------
# compute_distance
# ---------------------------------------------------------------------------


def _mk_equal_report(n: int) -> DiffReport:
    run_a, nodes_a = _build_uniform_run("A", [0] * n)
    run_b, nodes_b = _build_uniform_run("B", [0] * n)
    entries = [
        DiffEntry(tag="equal", node_name=na.node_name, a=na, b=nb)
        for na, nb in zip(nodes_a, nodes_b, strict=True)
    ]
    return DiffReport(run_a=run_a, run_b=run_b, entries=entries)


def _mk_all_changed_report(n: int) -> DiffReport:
    run_a, nodes_a = _build_uniform_run("A", [0] * n)
    run_b, nodes_b = _build_uniform_run("B", [99] * n)
    entries = [
        DiffEntry(tag="changed", node_name=na.node_name, a=na, b=nb)
        for na, nb in zip(nodes_a, nodes_b, strict=True)
    ]
    return DiffReport(run_a=run_a, run_b=run_b, entries=entries)


def test_compute_distance_identical_is_zero() -> None:
    report = _mk_equal_report(5)
    assert compute_distance(report) == 0.0


def test_compute_distance_fully_changed_is_one() -> None:
    report = _mk_all_changed_report(4)
    assert compute_distance(report) == 1.0


def test_compute_distance_empty_report_is_zero() -> None:
    # Empty alignment returns 0.0, not a ZeroDivisionError. Matches the
    # "no information" semantic documented in the docstring.
    run_a = _mk_run("A")
    run_b = _mk_run("B")
    report = DiffReport(run_a=run_a, run_b=run_b, entries=[])
    assert compute_distance(report) == 0.0


def test_compute_distance_half_and_half_is_point_five() -> None:
    run_a, nodes_a = _build_uniform_run("A", [0, 0, 0, 0])
    run_b, nodes_b = _build_uniform_run("B", [0, 99, 0, 99])
    entries = [
        DiffEntry(
            tag="equal" if nodes_a[i].state_after == nodes_b[i].state_after else "changed",
            node_name=nodes_a[i].node_name,
            a=nodes_a[i],
            b=nodes_b[i],
        )
        for i in range(4)
    ]
    report = DiffReport(run_a=run_a, run_b=run_b, entries=entries)
    assert compute_distance(report) == 0.5


def test_compute_distance_bounded_in_zero_one() -> None:
    # Every tag combination stays in [0, 1].
    for n in range(1, 10):
        for k in range(n + 1):
            # k disagreeing out of n.
            run_a, nodes_a = _build_uniform_run("A", [0] * n)
            run_b, nodes_b = _build_uniform_run("B", [0] * n)
            entries = [
                DiffEntry(
                    tag="changed" if i < k else "equal",
                    node_name=nodes_a[i].node_name,
                    a=nodes_a[i],
                    b=nodes_b[i],
                )
                for i in range(n)
            ]
            report = DiffReport(run_a=run_a, run_b=run_b, entries=entries)
            d = compute_distance(report)
            assert 0.0 <= d <= 1.0
            assert d == k / n


# ---------------------------------------------------------------------------
# pairwise_distances
# ---------------------------------------------------------------------------


def test_pairwise_distances_shape_n3() -> None:
    # Three identical runs: all pair distances = 0.
    store = _build_store(
        ("A", [0, 1, 2]),
        ("B", [0, 1, 2]),
        ("C", [0, 1, 2]),
    )
    d = pairwise_distances(["A", "B", "C"], store)
    assert set(d.keys()) == {("A", "B"), ("A", "C"), ("B", "C")}
    for v in d.values():
        assert v == 0.0


def test_pairwise_distances_keys_use_min_max_ordering() -> None:
    # Even if caller passes run_ids in non-sorted order, keys are sorted.
    store = _build_store(
        ("B", [0, 1, 2]),
        ("A", [0, 1, 2]),
        ("C", [0, 1, 2]),
    )
    d = pairwise_distances(["B", "A", "C"], store)
    for a, b in d:
        assert a < b, f"key must be (min, max): got ({a!r}, {b!r})"


def test_pairwise_distances_symmetric_under_flip() -> None:
    # Report (A, B) and (B, A) via SequenceMatcher must yield the same
    # structural distance under metric v1 (both count non-equal tags).
    store = _build_store(
        ("A", [0, 1, 2]),
        ("B", [0, 99, 2]),
    )
    forward = pairwise_distances(["A", "B"], store)
    backward = pairwise_distances(["B", "A"], store)
    # Same key convention, so both maps should be numerically identical.
    assert forward == backward


def test_pairwise_distances_rejects_single_id() -> None:
    store = _build_store(("A", [0, 1]))
    with pytest.raises(ValueError, match="at least 2"):
        pairwise_distances(["A"], store)


def test_pairwise_distances_rejects_duplicates() -> None:
    store = _build_store(("A", [0, 1]), ("B", [0, 1]))
    with pytest.raises(ValueError, match="duplicate"):
        pairwise_distances(["A", "A", "B"], store)


def test_pairwise_distances_propagates_missing_run() -> None:
    store = _build_store(("A", [0, 1]))
    with pytest.raises(DiffRunNotFoundError):
        pairwise_distances(["A", "missing"], store)


# ---------------------------------------------------------------------------
# select_centroid
# ---------------------------------------------------------------------------


def test_select_centroid_clear_winner() -> None:
    # A and B are close, C is far from both. Centroid is argmin mean — the
    # one closest to everyone else is A or B; in fact mean(A) = mean(B) < mean(C).
    distances = {
        ("A", "B"): 0.1,
        ("A", "C"): 0.8,
        ("B", "C"): 0.8,
    }
    # means: A = 0.45, B = 0.45, C = 0.8 → tie between A and B → lex tie-break → A.
    assert select_centroid(["A", "B", "C"], distances) == "A"


def test_select_centroid_unique_minimum() -> None:
    # A sits between B and C; B and C are far apart. A is the unique centroid.
    distances = {
        ("A", "B"): 0.2,
        ("A", "C"): 0.2,
        ("B", "C"): 0.9,
    }
    # means: A = 0.2, B = 0.55, C = 0.55 → A wins outright.
    assert select_centroid(["A", "B", "C"], distances) == "A"


def test_select_centroid_lex_tiebreak_four_runs() -> None:
    # All-equal distances → all means equal → lex tie-break on run_ids.
    distances = {
        ("A", "B"): 0.3,
        ("A", "C"): 0.3,
        ("A", "D"): 0.3,
        ("B", "C"): 0.3,
        ("B", "D"): 0.3,
        ("C", "D"): 0.3,
    }
    assert select_centroid(["D", "C", "B", "A"], distances) == "A"
    # Permutation invariance — same result regardless of argument order.
    assert select_centroid(["A", "B", "C", "D"], distances) == "A"


def test_select_centroid_n2_lex_tiebreak() -> None:
    # N=2: mean-distance is identical for both runs (one pair). Lex wins.
    distances = {("A", "B"): 0.7}
    assert select_centroid(["A", "B"], distances) == "A"
    assert select_centroid(["B", "A"], distances) == "A"


def test_select_centroid_rejects_single_id() -> None:
    with pytest.raises(ValueError, match="at least 2"):
        select_centroid(["A"], {})


def test_select_centroid_rejects_duplicates() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        select_centroid(["A", "A"], {("A", "A"): 0.0})


# ---------------------------------------------------------------------------
# auto_pivot_compare — orchestration
# ---------------------------------------------------------------------------


def test_auto_pivot_compare_n2_matches_merge_pivot_reports_directly() -> None:
    # N=2 contract: auto-pivot picks the lex-smallest id, then the merged
    # result equals merge_pivot_reports(pivot=that_id, others=[other]).
    from chronos.core.diff import diff_runs

    store = _build_store(
        ("A", [0, 1, 2]),
        ("B", [0, 99, 2]),
    )
    report = auto_pivot_compare(["A", "B"], store)

    assert report.centroid_run_id == "A"
    assert report.pivot_selection == "auto-centroid"
    assert report.metric_version == METRIC_VERSION
    assert report.metric_version == 1
    assert report.input_run_ids == ["A", "B"]
    assert set(report.distance_matrix.keys()) == {("A", "B")}

    # Direct call: same pivot, same other, same restrict default.
    direct = merge_pivot_reports(
        pivot_run_id="A",
        other_run_ids=["B"],
        reports=[diff_runs(store, "A", "B", restrict_to_downstream=True)],
    )
    # Numerical content equality (alignment + summary).
    assert report.merged.to_dict() == direct.to_dict()


def test_auto_pivot_compare_n2_caller_order_does_not_matter() -> None:
    # Passing ["B", "A"] still picks "A" as centroid due to lex tie-break.
    store = _build_store(
        ("A", [0, 1, 2]),
        ("B", [0, 99, 2]),
    )
    report_ba = auto_pivot_compare(["B", "A"], store)
    report_ab = auto_pivot_compare(["A", "B"], store)
    assert report_ba.centroid_run_id == "A"
    assert report_ab.centroid_run_id == "A"
    # input_run_ids preserves caller order.
    assert report_ba.input_run_ids == ["B", "A"]
    assert report_ab.input_run_ids == ["A", "B"]
    # Merged payload identical regardless of caller order.
    assert report_ba.merged.to_dict() == report_ab.merged.to_dict()


def test_auto_pivot_compare_n3_picks_outlier_inside_cluster() -> None:
    # A and B are identical. C is quite different from both.
    # Expected: centroid is either A or B (tie → lex → A).
    store = _build_store(
        ("A", [0, 1, 2, 3]),
        ("B", [0, 1, 2, 3]),
        ("C", [0, 99, 98, 97]),
    )
    report = auto_pivot_compare(["A", "B", "C"], store)
    assert report.centroid_run_id == "A"
    # A and B are identical → d(A, B) = 0.
    assert report.distance_matrix[("A", "B")] == 0.0
    # A-C and B-C are the "far" edges, > 0.5 given 3 of 4 steps changed.
    assert report.distance_matrix[("A", "C")] > 0.5
    assert report.distance_matrix[("B", "C")] > 0.5
    # Merged report has A as pivot, B and C as others.
    assert report.merged.pivot_run_id == "A"
    assert set(report.merged.other_run_ids) == {"B", "C"}


def test_auto_pivot_compare_n4_distance_matrix_shape() -> None:
    store = _build_store(
        ("A", [0, 1, 2]),
        ("B", [0, 1, 2]),
        ("C", [0, 1, 2]),
        ("D", [0, 1, 2]),
    )
    report = auto_pivot_compare(["A", "B", "C", "D"], store)
    # N=4 → N(N-1)/2 = 6 unordered pairs.
    assert len(report.distance_matrix) == 6
    expected_keys = {("A", "B"), ("A", "C"), ("A", "D"), ("B", "C"), ("B", "D"), ("C", "D")}
    assert set(report.distance_matrix.keys()) == expected_keys
    # All identical → all distances 0 → tie → lex → centroid = A.
    assert report.centroid_run_id == "A"
    assert all(v == 0.0 for v in report.distance_matrix.values())


def test_auto_pivot_compare_rejects_single_id() -> None:
    store = _build_store(("A", [0, 1]))
    with pytest.raises(ValueError, match="at least 2"):
        auto_pivot_compare(["A"], store)


def test_auto_pivot_compare_rejects_empty() -> None:
    store = _build_store(("A", [0, 1]))
    with pytest.raises(ValueError, match="at least 2"):
        auto_pivot_compare([], store)


def test_auto_pivot_compare_rejects_duplicates() -> None:
    store = _build_store(("A", [0, 1]), ("B", [0, 1]))
    with pytest.raises(ValueError, match="duplicate"):
        auto_pivot_compare(["A", "A", "B"], store)


def test_auto_pivot_compare_propagates_missing_run() -> None:
    store = _build_store(("A", [0, 1]))
    with pytest.raises(DiffRunNotFoundError):
        auto_pivot_compare(["A", "missing"], store)


# ---------------------------------------------------------------------------
# AutoPivotReport.to_dict
# ---------------------------------------------------------------------------


def test_auto_pivot_report_to_dict_shape() -> None:
    store = _build_store(
        ("A", [0, 1, 2]),
        ("B", [0, 99, 2]),
    )
    report = auto_pivot_compare(["A", "B"], store)
    d = report.to_dict()
    assert d["centroid_run_id"] == "A"
    assert d["pivot_selection"] == "auto-centroid"
    assert d["metric_version"] == 1
    assert d["input_run_ids"] == ["A", "B"]
    # Flattened distance-matrix keys are "a|b" strings; one entry for N=2.
    assert list(d["distance_matrix"].keys()) == ["A|B"]
    # Merged payload is the same shape as MergedPivotAlignment.to_dict().
    assert set(d["merged"].keys()) >= {"pivot_id", "other_ids", "alignment", "summary", "warnings"}
    assert d["merged"]["pivot_id"] == "A"
    assert d["merged"]["other_ids"] == ["B"]


def test_auto_pivot_report_is_instance_of_class() -> None:
    store = _build_store(("A", [0, 1]), ("B", [0, 1]))
    report = auto_pivot_compare(["A", "B"], store)
    assert isinstance(report, AutoPivotReport)
