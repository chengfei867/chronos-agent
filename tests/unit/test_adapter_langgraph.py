"""Unit tests for the LangGraph recorder adapter.

We use hand-crafted fake snapshot objects (NOT real LangGraph) so these
tests are fast and pinned to the contract documented in ADR-004. Integration
with real LangGraph is covered by ``tests/integration/test_adapter_e2e.py``.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field

import pytest

from chronos.adapters.langgraph import AdapterError, LangGraphRecorder
from chronos.core.models import NodeKind, RunStatus
from chronos.store import SqliteStore

# ---------------------------------------------------------------------------
# Minimal fake StateSnapshot / CompiledStateGraph — enough to satisfy the
# adapter's contract documented in ADR-004.
# ---------------------------------------------------------------------------


@dataclass
class FakeTask:
    name: str
    id: str = "fake-task-id"


@dataclass
class FakeSnapshot:
    values: dict
    next: tuple[str, ...]
    config: dict
    metadata: dict
    created_at: str
    tasks: list[FakeTask] = field(default_factory=list)


class FakeGraph:
    """Emulates just the ``get_state_history()`` method we depend on."""

    def __init__(self, snapshots_newest_first: list[FakeSnapshot]) -> None:
        self._history = list(snapshots_newest_first)

    def get_state_history(self, config: dict) -> list[FakeSnapshot]:
        return list(self._history)


# ---------------------------------------------------------------------------
# Builders for readable test fixtures
# ---------------------------------------------------------------------------


def _ckpt(id_: str, parent: str | None = None) -> dict:
    return {"configurable": {"thread_id": "t1", "checkpoint_ns": "", "checkpoint_id": id_}}


def build_4node_history() -> list[FakeSnapshot]:
    """Mimic the shape spike4 observed: 4 executed nodes → 6 snapshots,
    returned NEWEST-FIRST (LangGraph's convention)."""
    nodes = ["plan", "research", "draft", "polish"]
    base_time = "2026-04-22T16:00:00"

    # Build oldest-first for clarity, then reverse at return.
    oldest_first: list[FakeSnapshot] = []

    # step=-1: input placeholder
    oldest_first.append(
        FakeSnapshot(
            values={},
            next=("__start__",),
            config=_ckpt("c-1"),
            metadata={"source": "input", "step": -1, "parents": {}},
            created_at=f"{base_time}.000+00:00",
            tasks=[FakeTask(name="__start__", id="start")],
        )
    )

    # step=0..3: pre-execution snapshots, each with tasks[0]=about-to-run node
    cumulative_values: dict = {"task": "hello", "log": []}
    for i, node_name in enumerate(nodes):
        # This is the snapshot BEFORE node_name runs
        oldest_first.append(
            FakeSnapshot(
                values=dict(cumulative_values),
                next=(node_name,),
                config=_ckpt(f"c{i}", parent=f"c{i - 1}" if i > 0 else "c-1"),
                metadata={"source": "loop", "step": i, "parents": {}},
                created_at=f"{base_time}.{i + 1:03d}+00:00",
                tasks=[FakeTask(name=node_name, id=f"task-{node_name}")],
            )
        )
        # Now node_name "runs" and writes into cumulative_values
        key = "final" if node_name == "polish" else node_name
        cumulative_values[key] = f"output-of-{node_name}"
        cumulative_values["log"] = [*cumulative_values["log"], {"node": node_name}]

    # step=4: terminal snapshot (next=(), tasks=[])
    oldest_first.append(
        FakeSnapshot(
            values=dict(cumulative_values),
            next=(),
            config=_ckpt("c4", parent="c3"),
            metadata={"source": "loop", "step": len(nodes), "parents": {}},
            created_at=f"{base_time}.999+00:00",
            tasks=[],
        )
    )

    # LangGraph returns newest-first
    return list(reversed(oldest_first))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_records_run_with_correct_top_level_fields(tmp_path):
    db = tmp_path / "a.db"
    with SqliteStore.open(db) as store:
        recorder = LangGraphRecorder(store)
        graph = FakeGraph(build_4node_history())

        with recorder.record(graph, thread_id="t1", task_description="smoke") as ref:
            pass  # user would invoke here; history is already populated

        assert ref.run_id is not None
        assert len(ref.node_ids) == 4  # one per executed node, NOT 6

        run = store.get_run(ref.run_id)
        assert run is not None
        assert run.adapter == "langgraph"
        assert run.adapter_thread_id == "t1"
        assert run.status == RunStatus.COMPLETED
        assert run.task_description == "smoke"
        assert run.initial_state == {"task": "hello", "log": []}
        assert run.final_state["final"] == "output-of-polish"
        assert run.metadata["num_snapshots"] == 6


def test_records_one_node_per_executed_step_in_order(tmp_path):
    db = tmp_path / "b.db"
    with SqliteStore.open(db) as store:
        recorder = LangGraphRecorder(store)
        graph = FakeGraph(build_4node_history())

        with recorder.record(graph, thread_id="t1") as ref:
            pass

        nodes = store.get_nodes_for_run(ref.run_id)
        assert [n.node_name for n in nodes] == ["plan", "research", "draft", "polish"]
        assert [n.step_index for n in nodes] == [0, 1, 2, 3]


def test_parent_chain_is_linear(tmp_path):
    db = tmp_path / "c.db"
    with SqliteStore.open(db) as store:
        recorder = LangGraphRecorder(store)
        graph = FakeGraph(build_4node_history())

        with recorder.record(graph, thread_id="t1") as ref:
            pass

        nodes = store.get_nodes_for_run(ref.run_id)
        # step 0 has no parent; each subsequent node points to the previous one
        assert nodes[0].parent_node_id is None
        for prev, cur in itertools.pairwise(nodes):
            assert cur.parent_node_id == prev.id


def test_state_after_accumulates_correctly(tmp_path):
    """The state_after of node N should include every field written up to N."""
    db = tmp_path / "d.db"
    with SqliteStore.open(db) as store:
        recorder = LangGraphRecorder(store)
        graph = FakeGraph(build_4node_history())

        with recorder.record(graph, thread_id="t1") as ref:
            pass

        nodes = store.get_nodes_for_run(ref.run_id)
        # After "plan" ran, state_after should contain the "plan" key
        assert "plan" in nodes[0].state_after
        # After "polish" ran, state_after should contain "final" (plus all prior)
        assert "final" in nodes[3].state_after
        assert set(nodes[3].state_after.keys()) >= {
            "task",
            "plan",
            "research",
            "draft",
            "final",
            "log",
        }


def test_kind_map_is_honoured(tmp_path):
    db = tmp_path / "e.db"
    with SqliteStore.open(db) as store:
        recorder = LangGraphRecorder(
            store,
            kind_map={"plan": NodeKind.LLM, "research": NodeKind.TOOL},
        )
        graph = FakeGraph(build_4node_history())

        with recorder.record(graph, thread_id="t1") as ref:
            pass

        nodes = store.get_nodes_for_run(ref.run_id)
        kinds = {n.node_name: n.kind for n in nodes}
        assert kinds["plan"] == NodeKind.LLM
        assert kinds["research"] == NodeKind.TOOL
        assert kinds["draft"] == NodeKind.FN  # default
        assert kinds["polish"] == NodeKind.FN  # default


def test_checkpoint_ids_in_metadata(tmp_path):
    db = tmp_path / "f.db"
    with SqliteStore.open(db) as store:
        recorder = LangGraphRecorder(store)
        graph = FakeGraph(build_4node_history())

        with recorder.record(graph, thread_id="t1") as ref:
            pass

        nodes = store.get_nodes_for_run(ref.run_id)
        # The first node ran between ckpt c0 (pre) and c1 (post)
        assert nodes[0].metadata["parent_checkpoint_id"] == "c0"
        assert nodes[0].metadata["checkpoint_id"] == "c1"
        # Last node: pre=c3, post=c4
        assert nodes[3].metadata["parent_checkpoint_id"] == "c3"
        assert nodes[3].metadata["checkpoint_id"] == "c4"


def test_failed_run_is_marked_failed(tmp_path):
    db = tmp_path / "g.db"
    with SqliteStore.open(db) as store:
        recorder = LangGraphRecorder(store)
        graph = FakeGraph(build_4node_history())

        with pytest.raises(ValueError, match="boom"), recorder.record(graph, thread_id="t1") as ref:
            raise ValueError("boom")

        # The run should still have been persisted (with FAILED status)
        assert ref.run_id is not None
        run = store.get_run(ref.run_id)
        assert run is not None
        assert run.status == RunStatus.FAILED


def test_empty_history_is_noop(tmp_path):
    """If user enters the context but doesn't invoke, we emit nothing.
    This prevents polluting the DB with orphan rows."""
    db = tmp_path / "h.db"
    with SqliteStore.open(db) as store:
        recorder = LangGraphRecorder(store)
        graph = FakeGraph([])  # no snapshots

        with recorder.record(graph, thread_id="t1") as ref:
            pass

        assert ref.run_id is None
        assert ref.node_ids == []


def test_missing_input_placeholder_raises(tmp_path):
    """Defensive: if LangGraph ever changes source='input' convention,
    we fail loud instead of silently producing garbage."""
    db = tmp_path / "i.db"
    with SqliteStore.open(db) as store:
        recorder = LangGraphRecorder(store)

        # Build a history whose first (oldest) snapshot is NOT a source=input placeholder
        bad = [
            FakeSnapshot(
                values={"task": "x"},
                next=("plan",),
                config=_ckpt("c0"),
                metadata={"source": "loop", "step": 0, "parents": {}},
                created_at="2026-04-22T16:00:00.000+00:00",
                tasks=[FakeTask(name="plan")],
            )
        ]
        # reversed (newest-first); only 1 item so reversed == same
        graph = FakeGraph(bad)

        with (
            pytest.raises(AdapterError, match="source='input'"),
            recorder.record(graph, thread_id="t1"),
        ):
            pass


def test_single_node_graph(tmp_path):
    """Edge case: a 1-node graph produces exactly 1 Node, no parent."""
    db = tmp_path / "j.db"
    oldest_first = [
        FakeSnapshot(
            values={},
            next=("__start__",),
            config=_ckpt("c-1"),
            metadata={"source": "input", "step": -1, "parents": {}},
            created_at="2026-04-22T16:00:00.000+00:00",
            tasks=[FakeTask(name="__start__")],
        ),
        FakeSnapshot(
            values={"x": 1},
            next=("only",),
            config=_ckpt("c0"),
            metadata={"source": "loop", "step": 0, "parents": {}},
            created_at="2026-04-22T16:00:00.001+00:00",
            tasks=[FakeTask(name="only")],
        ),
        FakeSnapshot(
            values={"x": 1, "y": 2},
            next=(),
            config=_ckpt("c1"),
            metadata={"source": "loop", "step": 1, "parents": {}},
            created_at="2026-04-22T16:00:00.002+00:00",
            tasks=[],
        ),
    ]
    with SqliteStore.open(db) as store:
        recorder = LangGraphRecorder(store)
        graph = FakeGraph(list(reversed(oldest_first)))

        with recorder.record(graph, thread_id="t1") as ref:
            pass

        nodes = store.get_nodes_for_run(ref.run_id)
        assert len(nodes) == 1
        assert nodes[0].node_name == "only"
        assert nodes[0].parent_node_id is None
        assert nodes[0].state_after == {"x": 1, "y": 2}


def test_cyclic_graph_preserves_step_ordering(tmp_path):
    """Same node_name can appear at different step_index values (loop)."""
    db = tmp_path / "k.db"
    oldest_first = [
        FakeSnapshot(
            values={},
            next=("__start__",),
            config=_ckpt("c-1"),
            metadata={"source": "input", "step": -1, "parents": {}},
            created_at="2026-04-22T16:00:00.000+00:00",
            tasks=[FakeTask(name="__start__")],
        ),
        FakeSnapshot(
            values={},
            next=("loop",),
            config=_ckpt("c0"),
            metadata={"source": "loop", "step": 0, "parents": {}},
            created_at="2026-04-22T16:00:00.001+00:00",
            tasks=[FakeTask(name="loop")],
        ),
        FakeSnapshot(
            values={"n": 1},
            next=("loop",),
            config=_ckpt("c1"),
            metadata={"source": "loop", "step": 1, "parents": {}},
            created_at="2026-04-22T16:00:00.002+00:00",
            tasks=[FakeTask(name="loop")],
        ),
        FakeSnapshot(
            values={"n": 2},
            next=(),
            config=_ckpt("c2"),
            metadata={"source": "loop", "step": 2, "parents": {}},
            created_at="2026-04-22T16:00:00.003+00:00",
            tasks=[],
        ),
    ]
    with SqliteStore.open(db) as store:
        recorder = LangGraphRecorder(store)
        graph = FakeGraph(list(reversed(oldest_first)))

        with recorder.record(graph, thread_id="t1") as ref:
            pass

        nodes = store.get_nodes_for_run(ref.run_id)
        assert [n.node_name for n in nodes] == ["loop", "loop"]
        assert [n.step_index for n in nodes] == [0, 1]
        assert nodes[1].parent_node_id == nodes[0].id
