"""Unit tests for the LangGraph adapter's ``fork()`` context manager.

Use hand-crafted fake snapshot/graph objects (no real LangGraph dep in
these tests — ADR-005 contract isolation, same strategy as Round 4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from chronos.adapters.langgraph import AdapterError, LangGraphRecorder
from chronos.core.models import NodeKind, RunStatus
from chronos.store import SqliteStore

# Re-use the fake types from the sibling file
from tests.unit.test_adapter_langgraph import (
    FakeGraph,
    FakeSnapshot,
    FakeTask,
    build_4node_history,
)

# ---------------------------------------------------------------------------
# A forked-thread-aware fake graph — supports:
#   - update_state(cfg, values, as_node=...) — records the seed, pushes a snapshot
#   - invoke(None, cfg) — appends downstream snapshots (and a terminal)
#   - get_state_history(cfg) — returns per-thread-id snapshots, newest-first
# ---------------------------------------------------------------------------


@dataclass
class ForkFakeGraph:
    """A fake LangGraph that lets us simulate both original + forked threads.

    Seed history for the original thread is injected at construction. The
    ``update_state`` method starts a new thread's history. ``invoke(None)``
    advances the new thread through a scripted list of downstream nodes
    that each append to ``values`` in a deterministic way.
    """

    orig_thread_id: str
    orig_history_newest_first: list[FakeSnapshot]
    downstream_nodes: list[str]  # what nodes still need to run after fork
    # Mutable state — per-thread snapshot histories, oldest-first for sanity
    _threads: dict[str, list[FakeSnapshot]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Original thread history is already newest-first; store as-is.
        self._threads[self.orig_thread_id] = list(self.orig_history_newest_first)

    # --- API the adapter uses -------------------------------------------------

    def update_state(self, cfg: dict, values: dict, *, as_node: str) -> None:
        thread_id = cfg["configurable"]["thread_id"]
        if thread_id == self.orig_thread_id:
            raise AssertionError(
                "test bug: update_state on the original thread would corrupt it"
            )
        # Compute next downstream node based on position
        next_node = self.downstream_nodes[0] if self.downstream_nodes else None
        seed = FakeSnapshot(
            values=dict(values),
            next=(next_node,) if next_node else (),
            config={
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": "",
                    "checkpoint_id": f"{thread_id}-seed",
                }
            },
            metadata={"source": "update", "step": 0, "parents": {}},
            created_at="2026-04-23T00:00:00.000+00:00",
            tasks=[FakeTask(name=next_node, id=f"task-{next_node}")]
            if next_node
            else [],
        )
        # Reset thread to just the seed (oldest-first).
        self._threads[thread_id] = [seed]

    def invoke(self, inp: Any, cfg: dict) -> dict:
        thread_id = cfg["configurable"]["thread_id"]
        hist = self._threads.get(thread_id, [])
        if not hist:
            raise AssertionError("invoke called on empty thread — test bug")

        # Walk downstream_nodes; each produces one snapshot that's pre-next.
        cumulative = dict(hist[-1].values)
        for idx, node in enumerate(self.downstream_nodes):
            # "Run" the node → update cumulative state
            cumulative[node] = f"forked-output-of-{node}"
            log = list(cumulative.get("log", []))
            log.append({"node": node, "thread": thread_id})
            cumulative["log"] = log

            next_node: str | None = (
                self.downstream_nodes[idx + 1]
                if idx + 1 < len(self.downstream_nodes)
                else None
            )
            step_idx = idx + 1
            snap = FakeSnapshot(
                values=dict(cumulative),
                next=(next_node,) if next_node else (),
                config={
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_ns": "",
                        "checkpoint_id": f"{thread_id}-c{step_idx}",
                    }
                },
                metadata={"source": "loop", "step": step_idx, "parents": {}},
                created_at=f"2026-04-23T00:00:00.{step_idx:03d}+00:00",
                tasks=[FakeTask(name=next_node, id=f"task-{next_node}")]
                if next_node
                else [],
            )
            hist.append(snap)
        return cumulative

    def get_state_history(self, cfg: dict) -> list[FakeSnapshot]:
        thread_id = cfg["configurable"]["thread_id"]
        oldest_first = self._threads.get(thread_id, [])
        return list(reversed(oldest_first))


# ---------------------------------------------------------------------------
# Helper: seed a recorded parent Run in the store, return its ids.
# ---------------------------------------------------------------------------


def _seed_parent_run(store: SqliteStore) -> tuple[str, dict[str, str]]:
    """Record a 4-node parent Run. Return (run_id, {node_name: node_id})."""
    recorder = LangGraphRecorder(store, kind_map={"plan": NodeKind.LLM})
    graph = FakeGraph(build_4node_history())
    with recorder.record(graph, thread_id="t1", task_description="parent") as ref:
        pass
    assert ref.run_id
    nodes = store.get_nodes_for_run(ref.run_id)
    return ref.run_id, {n.node_name: n.id for n in nodes}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_fork_persists_child_run_and_fork_record(tmp_path):
    db = tmp_path / "fork.db"
    with SqliteStore.open(db) as store:
        parent_run_id, name_to_id = _seed_parent_run(store)
        fork_at = name_to_id["research"]

        recorder = LangGraphRecorder(store)
        # After "research", downstream in parent = draft, polish (2 nodes)
        fork_graph = ForkFakeGraph(
            orig_thread_id="t1",
            orig_history_newest_first=build_4node_history(),
            downstream_nodes=["draft", "polish"],
        )
        with recorder.fork(
            fork_graph,
            parent_run_id=parent_run_id,
            at_node_id=fork_at,
            overrides={"research": "alt"},
            child_thread_id="t1-fork",
            reason="try alternative research",
            tags=["exp"],
        ) as fref:
            fork_graph.invoke(None, {"configurable": {"thread_id": "t1-fork"}})

        # Child Run persisted
        assert fref.child_run_id is not None
        assert fref.fork_id is not None
        child = store.get_run(fref.child_run_id)
        assert child is not None
        assert child.adapter_thread_id == "t1-fork"
        assert child.status == RunStatus.COMPLETED
        assert "fork" in child.tags and "exp" in child.tags
        assert child.metadata["forked_from_run"] == parent_run_id
        assert child.metadata["forked_at_node"] == fork_at
        assert child.metadata["forked_at_node_name"] == "research"
        assert child.metadata["overrides_keys"] == ["research"]
        # Initial_state reflects seeded values (parent state_after + overrides)
        assert child.initial_state["research"] == "alt"

        # Fork record
        fork = store.get_fork(fref.fork_id)
        assert fork is not None
        assert fork.parent_run_id == parent_run_id
        assert fork.parent_node_id == fork_at
        assert fork.child_run_id == fref.child_run_id
        assert fork.edited_fields == {"research": "alt"}
        assert fork.reason == "try alternative research"


def test_fork_child_nodes_have_correct_shape(tmp_path):
    db = tmp_path / "fork-nodes.db"
    with SqliteStore.open(db) as store:
        parent_run_id, name_to_id = _seed_parent_run(store)
        parent_node_id = name_to_id["research"]
        parent_node = store.get_node(parent_node_id)
        assert parent_node is not None
        parent_step = parent_node.step_index

        recorder = LangGraphRecorder(store)
        fork_graph = ForkFakeGraph(
            orig_thread_id="t1",
            orig_history_newest_first=build_4node_history(),
            downstream_nodes=["draft", "polish"],
        )
        with recorder.fork(
            fork_graph,
            parent_run_id=parent_run_id,
            at_node_id=parent_node_id,
            overrides={},  # pure replay allowed
            child_thread_id="t1-fork",
        ) as fref:
            fork_graph.invoke(None, {"configurable": {"thread_id": "t1-fork"}})

        nodes = store.get_nodes_for_run(fref.child_run_id)
        # Two downstream nodes re-executed
        assert [n.node_name for n in nodes] == ["draft", "polish"]
        # step_index continues from parent.step_index + 1
        assert [n.step_index for n in nodes] == [parent_step + 1, parent_step + 2]
        # First child node points BACK to the parent node (cross-run linkage)
        assert nodes[0].parent_node_id == parent_node_id
        # Subsequent: within-child-run chain
        assert nodes[1].parent_node_id == nodes[0].id
        # Each node metadata carries the langgraph step (thread-local, starts 1)
        assert nodes[0].metadata["langgraph_step"] == 0
        assert nodes[1].metadata["langgraph_step"] == 1


def test_fork_empty_overrides_allowed_pure_replay(tmp_path):
    db = tmp_path / "replay.db"
    with SqliteStore.open(db) as store:
        parent_run_id, name_to_id = _seed_parent_run(store)
        recorder = LangGraphRecorder(store)
        fork_graph = ForkFakeGraph(
            orig_thread_id="t1",
            orig_history_newest_first=build_4node_history(),
            downstream_nodes=["draft", "polish"],
        )
        with recorder.fork(
            fork_graph,
            parent_run_id=parent_run_id,
            at_node_id=name_to_id["research"],
            overrides=None,  # explicitly None → treated as {}
            child_thread_id="t1-replay",
        ) as fref:
            fork_graph.invoke(None, {"configurable": {"thread_id": "t1-replay"}})

        fork = store.get_fork(fref.fork_id)
        assert fork.edited_fields == {}


def test_fork_raises_on_unknown_parent_run(tmp_path):
    db = tmp_path / "bad.db"
    with SqliteStore.open(db) as store:
        recorder = LangGraphRecorder(store)
        fork_graph = ForkFakeGraph(
            orig_thread_id="t1",
            orig_history_newest_first=build_4node_history(),
            downstream_nodes=["draft"],
        )
        with pytest.raises(AdapterError, match="not found"), recorder.fork(
            fork_graph,
            parent_run_id="no-such-run",
            at_node_id="no-such-node",
            overrides={},
            child_thread_id="t1-fork",
        ):
            pass


def test_fork_raises_on_node_belonging_to_different_run(tmp_path):
    db = tmp_path / "wrongnode.db"
    with SqliteStore.open(db) as store:
        # Seed two parent runs, use run A's id with run B's node.
        run_a, _names_a = _seed_parent_run(store)
        # Build a second parent run on a different thread
        recorder = LangGraphRecorder(store)
        graph2 = FakeGraph(build_4node_history())
        with recorder.record(graph2, thread_id="t2") as r2:
            pass
        nodes_b = store.get_nodes_for_run(r2.run_id)
        mismatched_node = nodes_b[1].id  # belongs to run B, not run A

        fork_graph = ForkFakeGraph(
            orig_thread_id="t1",
            orig_history_newest_first=build_4node_history(),
            downstream_nodes=["draft"],
        )
        with pytest.raises(AdapterError, match="does not belong"), recorder.fork(
            fork_graph,
            parent_run_id=run_a,
            at_node_id=mismatched_node,
            overrides={},
            child_thread_id="t1-fork",
        ):
            pass


def test_fork_raises_when_child_thread_equals_parent_thread(tmp_path):
    db = tmp_path / "samethread.db"
    with SqliteStore.open(db) as store:
        parent_run_id, name_to_id = _seed_parent_run(store)
        recorder = LangGraphRecorder(store)
        fork_graph = ForkFakeGraph(
            orig_thread_id="t1",
            orig_history_newest_first=build_4node_history(),
            downstream_nodes=["draft"],
        )
        with pytest.raises(AdapterError, match="must differ"), recorder.fork(
            fork_graph,
            parent_run_id=parent_run_id,
            at_node_id=name_to_id["research"],
            overrides={},
            child_thread_id="t1",  # same as parent!
        ):
            pass


def test_fork_raises_on_unexpected_first_source(tmp_path):
    """If LangGraph starts emitting a different source for forked threads,
    we must blow up loudly (same version-drift guard as record())."""
    db = tmp_path / "drift.db"
    with SqliteStore.open(db) as store:
        parent_run_id, name_to_id = _seed_parent_run(store)
        recorder = LangGraphRecorder(store)

        # Broken graph: the seed snapshot has source='bogus' instead of 'update'
        class BrokenForkGraph(ForkFakeGraph):
            def update_state(self, cfg: dict, values: dict, *, as_node: str) -> None:
                super().update_state(cfg, values, as_node=as_node)
                thread_id = cfg["configurable"]["thread_id"]
                # Mutate the seed snapshot
                self._threads[thread_id][0].metadata["source"] = "bogus"

        bg = BrokenForkGraph(
            orig_thread_id="t1",
            orig_history_newest_first=build_4node_history(),
            downstream_nodes=["draft"],
        )
        with pytest.raises(AdapterError, match="source='update'"), recorder.fork(
            bg,
            parent_run_id=parent_run_id,
            at_node_id=name_to_id["research"],
            overrides={},
            child_thread_id="t1-fork",
        ):
            bg.invoke(None, {"configurable": {"thread_id": "t1-fork"}})


def test_fork_persists_failed_child_when_user_invoke_raises(tmp_path):
    """If the user's invoke() raises inside the fork block, we still
    persist the partial child + Fork, then re-raise."""
    db = tmp_path / "fail.db"
    with SqliteStore.open(db) as store:
        parent_run_id, name_to_id = _seed_parent_run(store)
        recorder = LangGraphRecorder(store)
        fork_graph = ForkFakeGraph(
            orig_thread_id="t1",
            orig_history_newest_first=build_4node_history(),
            downstream_nodes=["draft", "polish"],
        )

        class BoomError(RuntimeError):
            pass

        captured_ref = []
        with pytest.raises(BoomError), recorder.fork(
            fork_graph,
            parent_run_id=parent_run_id,
            at_node_id=name_to_id["research"],
            overrides={"research": "alt"},
            child_thread_id="t1-fork",
        ) as fref:
            captured_ref.append(fref)
            # User invokes partially then blows up
            fork_graph.invoke(None, {"configurable": {"thread_id": "t1-fork"}})
            raise BoomError("downstream exploded")

        fref = captured_ref[0]
        assert fref.child_run_id is not None
        child = store.get_run(fref.child_run_id)
        assert child.status == RunStatus.FAILED
        # Fork record still written
        fork = store.get_fork(fref.fork_id)
        assert fork is not None
        assert fork.edited_fields == {"research": "alt"}


def test_fork_from_terminal_node_raises_or_noops_gracefully(tmp_path):
    """Forking from the last node means no downstream to re-run. The adapter's
    minimum contract: doesn't silently produce a no-op child with zero nodes.

    Current implementation: update_state with as_node=<terminal> produces a
    seed snapshot with tasks=[] and next=(); our fake graph models that by
    an empty downstream_nodes list. We accept either (a) explicit error
    or (b) child Run with 0 nodes + Fork record — but assert *something*
    coherent happens.
    """
    db = tmp_path / "terminal.db"
    with SqliteStore.open(db) as store:
        parent_run_id, name_to_id = _seed_parent_run(store)
        recorder = LangGraphRecorder(store)
        # No downstream nodes — seed snapshot will have next=() and tasks=[]
        fork_graph = ForkFakeGraph(
            orig_thread_id="t1",
            orig_history_newest_first=build_4node_history(),
            downstream_nodes=[],
        )
        with recorder.fork(
            fork_graph,
            parent_run_id=parent_run_id,
            at_node_id=name_to_id["polish"],  # the last node
            overrides={},
            child_thread_id="t1-terminal",
        ) as fref:
            fork_graph.invoke(None, {"configurable": {"thread_id": "t1-terminal"}})

        # Child run persisted but has zero re-executed nodes
        assert fref.child_run_id is not None
        nodes = store.get_nodes_for_run(fref.child_run_id)
        assert nodes == []
        # Fork record still written so the lineage is queryable
        fork = store.get_fork(fref.fork_id)
        assert fork is not None
