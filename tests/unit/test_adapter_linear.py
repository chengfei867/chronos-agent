"""Unit tests for the Linear-pipeline adapter (R28).

The linear adapter is a zero-dependency reference implementation of
`RecorderProtocol` (ADR-016) and satisfies ADR-014 criterion R1 (impl).
These tests verify:

1. Happy-path record (state accumulates across steps).
2. Usage hint extraction (``__chronos_usage__`` popped from state_after).
3. Fork semantics (resumes from ``at_node_id+1`` with overrides merged).
4. Error handling (AdapterError for contract violations, failed-shell
   Run persisted when user step raises).
5. Structural conformance to the LangGraphRecorder public shape (both
   expose ``record(runtime, *, thread_id, ...)`` and ``fork(runtime, *,
   parent_run_id, at_node_id, ...)``) — duck check for ADR-016.
"""

from __future__ import annotations

import inspect

import pytest

from chronos.adapters.langgraph import LangGraphRecorder
from chronos.adapters.linear import (
    AdapterError,
    ForkRef,
    LinearRecorder,
    LinearRuntime,
    RunRef,
)
from chronos.core.models import NodeKind, RunStatus
from chronos.store import SqliteStore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path):
    db = tmp_path / "chronos.db"
    with SqliteStore.open(db) as s:
        yield s


def _increment_step(state: dict) -> dict:
    """Simple deterministic step: {"n": X} → {"n": X+1}."""
    return {"n": state.get("n", 0) + 1}


def _appender(tag: str):
    """Factory for a step that appends ``tag`` to a list under ``"trail"``."""

    def _step(state: dict) -> dict:
        new = dict(state)
        new["trail"] = [*list(state.get("trail", [])), tag]
        return new

    return _step


# ---------------------------------------------------------------------------
# LinearRuntime construction
# ---------------------------------------------------------------------------


class TestLinearRuntime:
    def test_duplicate_node_names_rejected(self):
        with pytest.raises(AdapterError, match="duplicate node_name"):
            LinearRuntime(steps=[("a", _increment_step), ("a", _increment_step)])

    def test_step_index_of_known(self):
        rt = LinearRuntime(steps=[("alpha", _increment_step), ("beta", _increment_step)])
        assert rt.step_index_of("alpha") == 0
        assert rt.step_index_of("beta") == 1

    def test_step_index_of_unknown_raises(self):
        rt = LinearRuntime(steps=[("alpha", _increment_step)])
        with pytest.raises(AdapterError, match="not in LinearRuntime"):
            rt.step_index_of("nope")

    def test_kind_map_defaults_to_empty(self):
        rt = LinearRuntime(steps=[("a", _increment_step)])
        assert rt.kind_map == {}


# ---------------------------------------------------------------------------
# LinearRecorder.record happy paths
# ---------------------------------------------------------------------------


class TestRecordHappy:
    def test_record_single_step_persists_run_and_node(self, store):
        rec = LinearRecorder(store)
        rt = LinearRuntime(steps=[("only", _increment_step)])
        with rec.record(rt, thread_id="t1", initial_state={"n": 5}) as ref:
            pass
        assert ref.run_id is not None
        assert len(ref.node_ids) == 1

        run = store.get_run(ref.run_id)
        assert run is not None
        assert run.adapter == "linear"
        assert run.adapter_thread_id == "t1"
        assert run.status == RunStatus.COMPLETED
        assert run.initial_state == {"n": 5}
        assert run.final_state == {"n": 6}

        nodes = store.get_nodes_for_run(ref.run_id)
        assert len(nodes) == 1
        assert nodes[0].node_name == "only"
        assert nodes[0].step_index == 0
        assert nodes[0].kind == NodeKind.FN
        assert nodes[0].state_after == {"n": 6}
        assert nodes[0].parent_node_id is None

    def test_record_multi_step_chains_parent_node_ids(self, store):
        rec = LinearRecorder(store)
        rt = LinearRuntime(
            steps=[("a", _appender("A")), ("b", _appender("B")), ("c", _appender("C"))]
        )
        with rec.record(rt, thread_id="t2") as ref:
            pass
        nodes = sorted(store.get_nodes_for_run(ref.run_id), key=lambda n: n.step_index)
        assert [n.node_name for n in nodes] == ["a", "b", "c"]
        assert [n.step_index for n in nodes] == [0, 1, 2]
        # Parent chain: None -> a.id -> b.id
        assert nodes[0].parent_node_id is None
        assert nodes[1].parent_node_id == nodes[0].id
        assert nodes[2].parent_node_id == nodes[1].id
        # State accumulates
        assert nodes[-1].state_after == {"trail": ["A", "B", "C"]}

    def test_record_default_initial_state_is_empty(self, store):
        rec = LinearRecorder(store)
        rt = LinearRuntime(steps=[("x", _increment_step)])
        with rec.record(rt, thread_id="t3") as ref:
            pass
        run = store.get_run(ref.run_id)
        assert run.initial_state == {}
        assert run.final_state == {"n": 1}

    def test_record_kind_map_applied(self, store):
        rec = LinearRecorder(store)
        rt = LinearRuntime(
            steps=[("llm_call", _increment_step)],
            kind_map={"llm_call": NodeKind.LLM},
        )
        with rec.record(rt, thread_id="t4") as ref:
            pass
        nodes = store.get_nodes_for_run(ref.run_id)
        assert nodes[0].kind == NodeKind.LLM

    def test_record_usage_hint_extracted_and_popped(self, store):
        rec = LinearRecorder(store)

        def llm_step(state: dict) -> dict:
            return {
                "answer": 42,
                "__chronos_usage__": {
                    "prompt_tokens": 10,
                    "completion_tokens": 20,
                    "reasoning_tokens": 0,
                },
            }

        rt = LinearRuntime(steps=[("llm", llm_step)])
        with rec.record(rt, thread_id="t5") as ref:
            pass
        nodes = store.get_nodes_for_run(ref.run_id)
        assert nodes[0].usage is not None
        assert nodes[0].usage.prompt_tokens == 10
        assert nodes[0].usage.completion_tokens == 20
        # Hint removed from state_after to keep diffs clean
        assert "__chronos_usage__" not in nodes[0].state_after
        assert nodes[0].state_after == {"answer": 42}

    def test_record_tags_and_task_description_persisted(self, store):
        rec = LinearRecorder(store)
        rt = LinearRuntime(steps=[("s", _increment_step)])
        with rec.record(
            rt, thread_id="t6", task_description="demo task", tags=["demo", "r28"]
        ) as ref:
            pass
        run = store.get_run(ref.run_id)
        assert run.task_description == "demo task"
        assert run.tags == ["demo", "r28"]

    def test_record_num_steps_in_metadata(self, store):
        rec = LinearRecorder(store)
        rt = LinearRuntime(steps=[("a", _increment_step), ("b", _increment_step)])
        with rec.record(rt, thread_id="t7") as ref:
            pass
        run = store.get_run(ref.run_id)
        assert run.metadata["num_steps"] == 2


# ---------------------------------------------------------------------------
# LinearRecorder.record error paths
# ---------------------------------------------------------------------------


class TestRecordErrors:
    def test_step_returning_non_dict_raises_adaptererror(self, store):
        rec = LinearRecorder(store)

        def bad(_state: dict):
            return "not a dict"  # type: ignore[return-value]

        rt = LinearRuntime(steps=[("bad", bad)])
        with pytest.raises(AdapterError, match="expected dict"), rec.record(rt, thread_id="terr1"):
            pass

    def test_step_raising_persists_failed_shell(self, store):
        rec = LinearRecorder(store)

        def explodes(_state: dict) -> dict:
            raise RuntimeError("boom")

        rt = LinearRuntime(steps=[("explodes", explodes)])
        with pytest.raises(RuntimeError, match="boom"), rec.record(rt, thread_id="terr2") as ref:
            pass
        # Failed shell Run persisted
        assert ref.run_id is not None
        run = store.get_run(ref.run_id)
        assert run.status == RunStatus.FAILED
        assert "boom" in run.metadata.get("error", "")
        # No node rows for the failed attempt (shell-only)
        assert store.get_nodes_for_run(ref.run_id) == []


# ---------------------------------------------------------------------------
# LinearRecorder.fork
# ---------------------------------------------------------------------------


class TestFork:
    @pytest.fixture
    def parent_run(self, store):
        """Seed a 3-step parent run; return (recorder, runtime, ref)."""
        rec = LinearRecorder(store)
        rt = LinearRuntime(
            steps=[("a", _appender("A")), ("b", _appender("B")), ("c", _appender("C"))]
        )
        with rec.record(rt, thread_id="parent") as ref:
            pass
        return rec, rt, ref

    def test_fork_at_middle_node_resumes_tail(self, store, parent_run):
        rec, rt, parent_ref = parent_run
        nodes = sorted(store.get_nodes_for_run(parent_ref.run_id), key=lambda n: n.step_index)
        node_b = nodes[1]  # fork AFTER node b: only "c" re-runs
        with rec.fork(
            rt,
            parent_run_id=parent_ref.run_id,
            at_node_id=node_b.id,
            child_thread_id="child",
            overrides={"trail": ["X", "Y"]},
            reason="testing override",
        ) as fref:
            pass
        assert fref.child_run_id is not None
        assert fref.fork_id is not None
        # Child has exactly 1 node (step "c" only; "a" and "b" are skipped)
        child_nodes = store.get_nodes_for_run(fref.child_run_id)
        assert len(child_nodes) == 1
        assert child_nodes[0].node_name == "c"
        # step_index continues from parent: b.step_index=1 → child c.step_index=2
        assert child_nodes[0].step_index == node_b.step_index + 1
        # Child's first node parent_node_id links back to parent's node_b
        assert child_nodes[0].parent_node_id == node_b.id
        # State override applied before tail runs
        assert child_nodes[0].state_after == {"trail": ["X", "Y", "C"]}

        # Fork record persisted with lineage + edited_fields
        fork = store.get_fork(fref.fork_id)
        assert fork.parent_run_id == parent_ref.run_id
        assert fork.parent_node_id == node_b.id
        assert fork.child_run_id == fref.child_run_id
        assert fork.edited_fields == {"trail": ["X", "Y"]}
        assert fork.reason == "testing override"

    def test_fork_at_last_node_produces_empty_child(self, store, parent_run):
        rec, rt, parent_ref = parent_run
        nodes = sorted(store.get_nodes_for_run(parent_ref.run_id), key=lambda n: n.step_index)
        node_c = nodes[-1]  # last node; no tail to re-run
        with rec.fork(
            rt,
            parent_run_id=parent_ref.run_id,
            at_node_id=node_c.id,
            child_thread_id="child2",
        ) as fref:
            pass
        child_run = store.get_run(fref.child_run_id)
        assert child_run.status == RunStatus.COMPLETED
        assert store.get_nodes_for_run(fref.child_run_id) == []

    def test_fork_unknown_parent_run_raises(self, store, parent_run):
        rec, rt, _ = parent_run
        with (
            pytest.raises(AdapterError, match="not found in store"),
            rec.fork(
                rt,
                parent_run_id="00000000-0000-0000-0000-000000000000",
                at_node_id="whatever",
                child_thread_id="c",
            ),
        ):
            pass

    def test_fork_unknown_at_node_raises(self, store, parent_run):
        rec, rt, parent_ref = parent_run
        with (
            pytest.raises(AdapterError, match=r"at_node_id.*not found"),
            rec.fork(
                rt,
                parent_run_id=parent_ref.run_id,
                at_node_id="00000000-0000-0000-0000-000000000000",
                child_thread_id="c",
            ),
        ):
            pass

    def test_fork_mismatched_parent_raises(self, store, parent_run):
        """at_node_id that belongs to a DIFFERENT parent run is rejected."""
        rec, rt, parent_ref = parent_run
        # Make a second parent run
        with rec.record(rt, thread_id="parent2") as other_ref:
            pass
        other_node = store.get_nodes_for_run(other_ref.run_id)[0]
        with (
            pytest.raises(AdapterError, match="does not belong"),
            rec.fork(
                rt,
                parent_run_id=parent_ref.run_id,
                at_node_id=other_node.id,
                child_thread_id="c",
            ),
        ):
            pass

    def test_fork_same_thread_id_rejected(self, store, parent_run):
        rec, rt, parent_ref = parent_run
        node = store.get_nodes_for_run(parent_ref.run_id)[0]
        with (
            pytest.raises(AdapterError, match="must differ from parent"),
            rec.fork(
                rt,
                parent_run_id=parent_ref.run_id,
                at_node_id=node.id,
                child_thread_id="parent",  # same as parent → rejected
            ),
        ):
            pass

    def test_fork_rejects_non_linear_parent(self, store, parent_run):
        _rec, rt, parent_ref = parent_run
        # Recorder configured to treat "linear" runs as foreign
        other_rec = LinearRecorder(store, adapter_name="pretend-not-linear")
        node = store.get_nodes_for_run(parent_ref.run_id)[0]
        with (
            pytest.raises(AdapterError, match="cannot be forked by"),
            other_rec.fork(
                rt,
                parent_run_id=parent_ref.run_id,
                at_node_id=node.id,
                child_thread_id="c",
            ),
        ):
            pass

    def test_fork_step_fn_raising_persists_failed_shell(self, store, parent_run):
        rec, _rt, parent_ref = parent_run

        def explodes(_state: dict) -> dict:
            raise RuntimeError("fork-time boom")

        # New runtime with a failing tail step
        rt = LinearRuntime(
            steps=[
                ("a", _appender("A")),
                ("b", _appender("B")),
                ("c", explodes),
            ]
        )
        node_b = sorted(store.get_nodes_for_run(parent_ref.run_id), key=lambda n: n.step_index)[1]
        with (
            pytest.raises(RuntimeError, match="fork-time boom"),
            rec.fork(
                rt,
                parent_run_id=parent_ref.run_id,
                at_node_id=node_b.id,
                child_thread_id="child-failed",
            ) as fref,
        ):
            pass
        assert fref.child_run_id is not None
        child_run = store.get_run(fref.child_run_id)
        assert child_run.status == RunStatus.FAILED


# ---------------------------------------------------------------------------
# Structural conformance to the RecorderProtocol (ADR-016)
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    """Duck-check that LinearRecorder and LangGraphRecorder share the public
    shape required by ADR-016's RecorderProtocol. This is the structural
    half of 'R1 impl' — the Protocol dataclass in protocols.py is a future
    refactor (ADR-016 rollout step 2)."""

    def test_record_signature_matches(self):
        sig_linear = inspect.signature(LinearRecorder.record)
        sig_lg = inspect.signature(LangGraphRecorder.record)
        # Both expose kwargs-after-runtime that overlap on ADR-016 contract
        required = {"thread_id", "task_description", "tags"}
        assert required.issubset(set(sig_linear.parameters))
        assert required.issubset(set(sig_lg.parameters))

    def test_fork_signature_matches(self):
        sig_linear = inspect.signature(LinearRecorder.fork)
        sig_lg = inspect.signature(LangGraphRecorder.fork)
        required = {
            "parent_run_id",
            "at_node_id",
            "overrides",
            "child_thread_id",
            "reason",
            "task_description",
            "tags",
        }
        assert required.issubset(set(sig_linear.parameters))
        assert required.issubset(set(sig_lg.parameters))

    def test_record_yields_runref_with_expected_fields(self, store):
        rec = LinearRecorder(store)
        rt = LinearRuntime(steps=[("x", _increment_step)])
        with rec.record(rt, thread_id="t") as ref:
            # Mirrors LangGraphRecorder.record: mutable handle with thread_id,
            # run_id (None until exit), node_ids list
            assert isinstance(ref, RunRef)
            assert ref.thread_id == "t"
            assert ref.run_id is None
            assert ref.node_ids == []
        assert ref.run_id is not None
        assert len(ref.node_ids) == 1

    def test_fork_yields_forkref_with_expected_fields(self, store):
        rec = LinearRecorder(store)
        rt = LinearRuntime(steps=[("a", _appender("A")), ("b", _appender("B"))])
        with rec.record(rt, thread_id="parent-pc") as pref:
            pass
        node_a = sorted(store.get_nodes_for_run(pref.run_id), key=lambda n: n.step_index)[0]
        with rec.fork(
            rt,
            parent_run_id=pref.run_id,
            at_node_id=node_a.id,
            child_thread_id="child-pc",
        ) as fref:
            assert isinstance(fref, ForkRef)
            assert fref.parent_run_id == pref.run_id
            assert fref.child_thread_id == "child-pc"
            assert fref.child_run_id is None
            assert fref.fork_id is None
        assert fref.child_run_id is not None
        assert fref.fork_id is not None
