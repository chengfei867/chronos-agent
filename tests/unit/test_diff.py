"""Tests for ``chronos.core.diff`` — ADR-006 alignment algorithm.

Mirrors the five canonical cases from ``tests/spikes/spike7_diff_alignment.py``
plus a fork-aware shortcut case. The algorithm is pure, so most tests use
duck-typed fake stores instead of a real SqliteStore.

Covered:
* ``align_nodes`` direct — 5 pure-alignment cases
* ``diff_runs`` with a fake store — fork-aware slicing on/off
* ``diff_runs`` with a real SqliteStore — end-to-end integration
* Error handling — missing run
* ``StateDiff`` key-level deltas
* ``DiffReport.to_dict`` schema shape
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from chronos.core.diff import (
    DiffEntry,
    DiffRunNotFoundError,
    StateDiff,
    align_nodes,
    diff_runs,
)
from chronos.core.models import Fork, Node, NodeKind, Run, RunStatus
from chronos.store.sqlite import SqliteStore

T0 = datetime(2026, 4, 23, 7, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers — build Node instances fast for alignment cases
# ---------------------------------------------------------------------------


def _mk_node(
    *,
    run_id: str,
    step: int,
    name: str,
    state: dict[str, Any] | None = None,
    nid: str | None = None,
) -> Node:
    return Node(
        id=nid or f"{run_id}-n-{step}",
        run_id=run_id,
        step_index=step,
        node_name=name,
        kind=NodeKind.FN,
        started_at=T0,
        ended_at=T0,
        state_after=state or {},
    )


class _FakeStore:
    """Duck-typed store satisfying ``_DiffStore`` protocol."""

    def __init__(
        self,
        runs: dict[str, Run],
        nodes: dict[str, list[Node]],
        forks: dict[str, Fork] | None = None,  # keyed by child_run_id
    ) -> None:
        self._runs = runs
        self._nodes = nodes
        self._forks = forks or {}

    def get_run(self, run_id: str) -> Run | None:
        return self._runs.get(run_id)

    def get_nodes_for_run(self, run_id: str) -> list[Node]:
        return list(self._nodes.get(run_id, []))

    def get_fork_for_child(self, child_run_id: str) -> Fork | None:
        return self._forks.get(child_run_id)


def _mk_run(run_id: str, task: str = "t") -> Run:
    return Run(
        id=run_id,
        adapter="langgraph",
        adapter_thread_id=f"thr-{run_id}",
        status=RunStatus.COMPLETED,
        started_at=T0,
        ended_at=T0,
        task_description=task,
    )


# ---------------------------------------------------------------------------
# align_nodes — pure alignment, mirrors spike7
# ---------------------------------------------------------------------------


def _tag_seq(entries: list[DiffEntry]) -> list[tuple[str, str]]:
    return [(e.tag, e.node_name) for e in entries]


def _summary(entries: list[DiffEntry]) -> dict[str, int]:
    s = {"equal": 0, "changed": 0, "added": 0, "removed": 0}
    for e in entries:
        s[e.tag] += 1
    return s


def test_align_identical_runs_all_equal() -> None:
    """Case 4 from spike7."""
    a = [
        _mk_node(run_id="A", step=0, name="ingest", state={"x": 1}),
        _mk_node(run_id="A", step=1, name="draft", state={"x": 2}),
        _mk_node(run_id="A", step=2, name="end", state={"x": 3}),
    ]
    b = [
        _mk_node(run_id="B", step=0, name="ingest", state={"x": 1}),
        _mk_node(run_id="B", step=1, name="draft", state={"x": 2}),
        _mk_node(run_id="B", step=2, name="end", state={"x": 3}),
    ]
    entries = align_nodes(a, b)
    assert _summary(entries) == {"equal": 3, "changed": 0, "added": 0, "removed": 0}
    # No changed nodes, so no state_diff payloads
    assert all(e.state_diff is None for e in entries)


def test_align_fork_child_common_tail() -> None:
    """Case 1 from spike7 — child runs downstream of fork point, states differ."""
    a = [
        _mk_node(run_id="A", step=0, name="ingest", state={"input": "X"}),
        _mk_node(run_id="A", step=1, name="research", state={"facts": ["a"]}),
        _mk_node(run_id="A", step=2, name="draft", state={"draft": "orig"}),
        _mk_node(run_id="A", step=3, name="end", state={"final": "orig"}),
    ]
    b = [
        _mk_node(run_id="B", step=1, name="research", state={"facts": ["a", "b"]}),
        _mk_node(run_id="B", step=2, name="draft", state={"draft": "alt"}),
        _mk_node(run_id="B", step=3, name="end", state={"final": "alt"}),
    ]
    entries = align_nodes(a, b)
    assert _tag_seq(entries) == [
        ("removed", "ingest"),
        ("changed", "research"),
        ("changed", "draft"),
        ("changed", "end"),
    ]


def test_align_early_exit() -> None:
    """Case 2 from spike7 — child exits earlier than parent."""
    a = [
        _mk_node(run_id="A", step=0, name="ingest", state={"x": 1}),
        _mk_node(run_id="A", step=1, name="research", state={"x": 2}),
        _mk_node(run_id="A", step=2, name="draft", state={"x": 3}),
        _mk_node(run_id="A", step=3, name="polish", state={"x": 4}),
        _mk_node(run_id="A", step=4, name="end", state={"x": 5}),
    ]
    b = [
        _mk_node(run_id="B", step=2, name="draft", state={"x": 999}),
        _mk_node(run_id="B", step=3, name="end", state={"x": 1000}),
    ]
    entries = align_nodes(a, b)
    s = _summary(entries)
    assert s == {"equal": 0, "changed": 2, "added": 0, "removed": 3}


def test_align_cycles_repeated_node_names() -> None:
    """Case 3 from spike7 — loops with repeated node_names pair by order."""
    a = [
        _mk_node(run_id="A", step=0, name="start"),
        _mk_node(run_id="A", step=1, name="router"),
        _mk_node(run_id="A", step=2, name="worker"),
        _mk_node(run_id="A", step=3, name="router"),
        _mk_node(run_id="A", step=4, name="worker"),
        _mk_node(run_id="A", step=5, name="router"),
        _mk_node(run_id="A", step=6, name="end"),
    ]
    # B runs one extra iteration
    b = [
        _mk_node(run_id="B", step=0, name="start"),
        _mk_node(run_id="B", step=1, name="router"),
        _mk_node(run_id="B", step=2, name="worker"),
        _mk_node(run_id="B", step=3, name="router"),
        _mk_node(run_id="B", step=4, name="worker"),
        _mk_node(run_id="B", step=5, name="router"),
        _mk_node(run_id="B", step=6, name="worker"),
        _mk_node(run_id="B", step=7, name="router"),
        _mk_node(run_id="B", step=8, name="end"),
    ]
    entries = align_nodes(a, b)
    s = _summary(entries)
    # 2 extra nodes in B → added=2; every other pair should be equal
    # (states default to {} so they're all equal)
    assert s["added"] == 2
    assert s["removed"] == 0
    # equal count = 7 - 0 removed = 7 (first 6 paired + `end` paired)
    assert s["equal"] == 7


def test_align_structural_mismatch() -> None:
    """Case 5 from spike7 — different prefixes, same suffix, state changed."""
    a = [
        _mk_node(run_id="A", step=0, name="prelude", state={"x": 0}),
        _mk_node(run_id="A", step=1, name="ingest", state={"x": 1}),
        _mk_node(run_id="A", step=2, name="draft", state={"x": 2}),
        _mk_node(run_id="A", step=3, name="end", state={"x": 3}),
    ]
    b = [
        _mk_node(run_id="B", step=2, name="draft", state={"x": 999}),
        _mk_node(run_id="B", step=3, name="end", state={"x": 999}),
    ]
    entries = align_nodes(a, b)
    assert _summary(entries) == {"equal": 0, "changed": 2, "added": 0, "removed": 2}


def test_align_both_empty() -> None:
    assert align_nodes([], []) == []


def test_align_a_empty_b_nonempty() -> None:
    b = [_mk_node(run_id="B", step=0, name="only", state={"x": 1})]
    entries = align_nodes([], b)
    assert _tag_seq(entries) == [("added", "only")]
    assert entries[0].b is b[0]
    assert entries[0].a is None


def test_align_a_nonempty_b_empty() -> None:
    a = [_mk_node(run_id="A", step=0, name="only", state={"x": 1})]
    entries = align_nodes(a, [])
    assert _tag_seq(entries) == [("removed", "only")]
    assert entries[0].a is a[0]


# ---------------------------------------------------------------------------
# StateDiff key-level behaviour
# ---------------------------------------------------------------------------


def test_state_diff_attached_only_when_changed() -> None:
    a = [_mk_node(run_id="A", step=0, name="n", state={"x": 1})]
    b = [_mk_node(run_id="B", step=0, name="n", state={"x": 2, "y": 3})]
    entries = align_nodes(a, b)
    assert len(entries) == 1
    e = entries[0]
    assert e.tag == "changed"
    assert e.state_diff is not None
    assert e.state_diff.added_keys == ["y"]
    assert e.state_diff.removed_keys == []
    assert e.state_diff.changed_keys == {"x": {"a": 1, "b": 2}}


def test_state_diff_removed_key() -> None:
    a = [_mk_node(run_id="A", step=0, name="n", state={"x": 1, "y": 2})]
    b = [_mk_node(run_id="B", step=0, name="n", state={"x": 1})]
    e = align_nodes(a, b)[0]
    assert e.tag == "changed"
    assert e.state_diff is not None
    assert e.state_diff.removed_keys == ["y"]
    assert e.state_diff.added_keys == []
    assert e.state_diff.changed_keys == {}


def test_state_diff_empty_when_dicts_equal() -> None:
    sd = StateDiff()
    assert sd.is_empty
    sd2 = StateDiff(added_keys=["k"])
    assert not sd2.is_empty


# ---------------------------------------------------------------------------
# diff_runs — fork-aware slicing
# ---------------------------------------------------------------------------


def _seed_fork_world(
    *, override_state: dict[str, Any] | None = None
) -> tuple[_FakeStore, str, str, str]:
    """Build parent (3 nodes) + child-of-fork (1 node) in a fake store."""
    parent_id = "run-A"
    child_id = "run-B"
    parent = _mk_run(parent_id, "original")
    child = _mk_run(child_id, "alt")

    # Fork point = parent step 1 ("draft"). Child re-runs "polish" only.
    p_nodes = [
        _mk_node(run_id=parent_id, step=0, name="plan", state={"s": 0}, nid="np0"),
        _mk_node(run_id=parent_id, step=1, name="draft", state={"s": 1}, nid="np1"),
        _mk_node(run_id=parent_id, step=2, name="polish", state={"s": 2}, nid="np2"),
    ]
    c_nodes = [
        _mk_node(
            run_id=child_id,
            step=2,
            name="polish",
            state=override_state or {"s": 999},
            nid="nc2",
        )
    ]
    fork = Fork(
        id="fork-1",
        parent_run_id=parent_id,
        parent_node_id="np1",
        child_run_id=child_id,
        created_at=T0,
        edited_fields={"draft": "alt"},
    )
    store = _FakeStore(
        runs={parent_id: parent, child_id: child},
        nodes={parent_id: p_nodes, child_id: c_nodes},
        forks={child_id: fork},
    )
    return store, parent_id, child_id, fork.id


def test_diff_runs_fork_aware_restricts_to_downstream() -> None:
    store, a, b, _ = _seed_fork_world()
    report = diff_runs(store, a, b)  # default restrict=True
    assert report.restricted_to_downstream is True
    assert report.fork is not None
    assert report.fork_point_node_name == "draft"
    # Only "polish" remains on A after slicing; B also has only "polish"
    # → 1 entry, CHANGED (state differs)
    assert len(report.entries) == 1
    assert report.entries[0].tag == "changed"
    assert report.entries[0].node_name == "polish"


def test_diff_runs_full_mode_shows_entire_a() -> None:
    store, a, b, _ = _seed_fork_world()
    report = diff_runs(store, a, b, restrict_to_downstream=False)
    assert report.restricted_to_downstream is False
    # full-run: 3 parent nodes vs 1 child node, aligned by name
    # plan REMOVED, draft REMOVED, polish CHANGED
    assert report.summary == {"equal": 0, "changed": 1, "added": 0, "removed": 2}


def test_diff_runs_fork_not_related_falls_through_to_full() -> None:
    """If B is forked from some OTHER run, don't slice A."""
    # Build a world where B is forked from a run C, not from A
    parent_id, other_id, child_id = "run-A", "run-C", "run-B"
    store = _FakeStore(
        runs={
            parent_id: _mk_run(parent_id),
            other_id: _mk_run(other_id),
            child_id: _mk_run(child_id),
        },
        nodes={
            parent_id: [
                _mk_node(run_id=parent_id, step=0, name="n1", state={"x": 1}),
            ],
            child_id: [
                _mk_node(run_id=child_id, step=1, name="n1", state={"x": 1}),
            ],
        },
        forks={
            child_id: Fork(
                id="fork-x",
                parent_run_id=other_id,  # NOT run_a
                parent_node_id="nx",
                child_run_id=child_id,
                created_at=T0,
            )
        },
    )
    report = diff_runs(store, parent_id, child_id)
    # Fork is not relevant to (A, B) → no slicing, no fork annotation
    assert report.fork is None
    assert report.restricted_to_downstream is False


def test_diff_runs_equal_states_across_fork_boundary() -> None:
    """Fork child happens to produce identical downstream state → equal, not changed."""
    store, a, b, _ = _seed_fork_world(override_state={"s": 2})  # matches parent polish
    report = diff_runs(store, a, b)
    assert report.entries[0].tag == "equal"


def test_diff_runs_missing_a_raises() -> None:
    store = _FakeStore(runs={"B": _mk_run("B")}, nodes={"B": []})
    with pytest.raises(DiffRunNotFoundError) as exc_info:
        diff_runs(store, "A", "B")
    assert exc_info.value.run_id == "A"


def test_diff_runs_missing_b_raises() -> None:
    store = _FakeStore(runs={"A": _mk_run("A")}, nodes={"A": []})
    with pytest.raises(DiffRunNotFoundError) as exc_info:
        diff_runs(store, "A", "B")
    assert exc_info.value.run_id == "B"


# ---------------------------------------------------------------------------
# to_dict serialisation contract (locks in ADR-006 §Decision 6 schema)
# ---------------------------------------------------------------------------


def test_diff_report_to_dict_schema() -> None:
    store, a, b, fork_id = _seed_fork_world()
    report = diff_runs(store, a, b)
    d = report.to_dict()
    assert set(d.keys()) == {
        "run_a",
        "run_b",
        "fork_of",
        "restricted_to_downstream",
        "entries",
        "summary",
    }
    assert d["fork_of"]["id"] == fork_id
    assert d["fork_of"]["parent_node_name"] == "draft"
    assert d["summary"]["changed"] == 1
    # Entry shape
    entry = d["entries"][0]
    assert set(entry.keys()) == {"tag", "node_name", "a", "b", "state_diff"}
    assert entry["tag"] == "changed"
    assert entry["a"]["node_name"] == "polish"
    assert entry["b"]["node_name"] == "polish"
    assert entry["state_diff"]["changed_keys"] == {"s": {"a": 2, "b": 999}}


def test_diff_report_to_dict_no_fork() -> None:
    store = _FakeStore(
        runs={"A": _mk_run("A"), "B": _mk_run("B")},
        nodes={"A": [], "B": []},
    )
    report = diff_runs(store, "A", "B")
    d = report.to_dict()
    assert d["fork_of"] is None
    assert d["restricted_to_downstream"] is False
    assert d["entries"] == []
    assert d["summary"] == {"equal": 0, "changed": 0, "added": 0, "removed": 0}


# ---------------------------------------------------------------------------
# Integration — real SqliteStore with a persisted fork
# ---------------------------------------------------------------------------


@pytest.fixture
def integration_db(tmp_path: Path) -> tuple[Path, str, str]:
    """Seed a real SqliteStore with a parent/child/fork triple."""
    db_path = tmp_path / "diff_int.db"
    parent_id = "int-A"
    child_id = "int-B"
    store = SqliteStore.open(db_path)
    try:
        store.put_run(_mk_run(parent_id, "original"))
        store.put_run(_mk_run(child_id, "alt"))
        store.put_node(_mk_node(run_id=parent_id, step=0, name="plan", state={"s": 0}, nid="ip0"))
        store.put_node(_mk_node(run_id=parent_id, step=1, name="draft", state={"s": 1}, nid="ip1"))
        store.put_node(_mk_node(run_id=parent_id, step=2, name="polish", state={"s": 2}, nid="ip2"))
        store.put_node(
            _mk_node(run_id=child_id, step=2, name="polish", state={"s": 777}, nid="ic2")
        )
        store.put_fork(
            Fork(
                id="int-fork",
                parent_run_id=parent_id,
                parent_node_id="ip1",
                child_run_id=child_id,
                created_at=T0,
                edited_fields={"draft": "alt"},
            )
        )
    finally:
        store.close()
    return db_path, parent_id, child_id


def test_diff_runs_with_real_sqlite_store(
    integration_db: tuple[Path, str, str],
) -> None:
    db_path, a, b = integration_db
    store = SqliteStore.open(db_path)
    try:
        report = diff_runs(store, a, b)
    finally:
        store.close()
    assert report.restricted_to_downstream is True
    assert report.fork_point_node_name == "draft"
    assert len(report.entries) == 1
    entry = report.entries[0]
    assert entry.tag == "changed"
    assert entry.state_diff is not None
    assert entry.state_diff.changed_keys == {"s": {"a": 2, "b": 777}}


def test_diff_runs_full_mode_with_real_sqlite_store(
    integration_db: tuple[Path, str, str],
) -> None:
    db_path, a, b = integration_db
    store = SqliteStore.open(db_path)
    try:
        report = diff_runs(store, a, b, restrict_to_downstream=False)
    finally:
        store.close()
    assert report.restricted_to_downstream is False
    # plan REMOVED, draft REMOVED, polish CHANGED
    assert report.summary == {"equal": 0, "changed": 1, "added": 0, "removed": 2}
