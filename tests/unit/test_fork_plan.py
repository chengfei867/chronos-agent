"""Unit tests for :mod:`chronos.fork_plan` — the portable artifact format."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chronos import __version__
from chronos.fork_plan import (
    FORK_PLAN_VERSION,
    ForkPlan,
    ForkPlanError,
    load_plan,
    plan_from_dict,
)

# ---------------------------------------------------------------------------
# ForkPlan.recorder_kwargs — the fields handed off to recorder.fork()
# ---------------------------------------------------------------------------


def test_recorder_kwargs_minimal() -> None:
    plan = ForkPlan(
        parent_run_id="run-1",
        parent_node_id="node-1",
        parent_node_name="research",
        parent_node_index=2,
        child_thread_id="t1-fork-abc",
        overrides={"research": "v2"},
    )
    kwargs = plan.recorder_kwargs()
    assert kwargs == {
        "parent_run_id": "run-1",
        "at_node_id": "node-1",
        "overrides": {"research": "v2"},
        "child_thread_id": "t1-fork-abc",
    }


def test_recorder_kwargs_includes_optional_only_when_set() -> None:
    plan = ForkPlan(
        parent_run_id="r",
        parent_node_id="n",
        parent_node_name="x",
        parent_node_index=0,
        child_thread_id="t-fork",
        overrides={},
        reason="swap model",
        tags=["alt"],
        task_description="fork: alt model",
    )
    kwargs = plan.recorder_kwargs()
    assert kwargs["reason"] == "swap model"
    assert kwargs["tags"] == ["alt"]
    assert kwargs["task_description"] == "fork: alt model"


def test_recorder_kwargs_copies_mutables() -> None:
    overrides = {"a": [1, 2, 3]}
    plan = ForkPlan(
        parent_run_id="r",
        parent_node_id="n",
        parent_node_name="x",
        parent_node_index=0,
        child_thread_id="t-fork",
        overrides=overrides,
        tags=["x"],
    )
    kwargs = plan.recorder_kwargs()
    kwargs["overrides"]["a"].append(4)
    kwargs["tags"].append("y")
    assert plan.overrides == {"a": [1, 2, 3]}
    assert plan.tags == ["x"]


# ---------------------------------------------------------------------------
# to_dict / to_json / dump
# ---------------------------------------------------------------------------


def _minimal_plan() -> ForkPlan:
    return ForkPlan(
        parent_run_id="run-1",
        parent_node_id="node-2",
        parent_node_name="research",
        parent_node_index=2,
        child_thread_id="t-fork-01",
        overrides={"research": "alt"},
        reason="swap prompt",
        tags=["demo"],
    )


def test_to_dict_has_stable_key_order() -> None:
    plan = _minimal_plan()
    d = plan.to_dict()
    keys = list(d.keys())
    # Version key comes first so readers can bail early on unknown versions.
    assert keys[0] == "chronos_fork_plan_version"
    # parent_* identifiers come before child_thread_id/overrides.
    assert keys.index("parent_run_id") < keys.index("child_thread_id")
    assert keys.index("child_thread_id") < keys.index("overrides")


def test_to_dict_records_provenance() -> None:
    plan = _minimal_plan()
    d = plan.to_dict()
    assert d["chronos_fork_plan_version"] == FORK_PLAN_VERSION
    assert d["chronos_version"] == __version__
    assert isinstance(d["generated_at"], str) and "T" in d["generated_at"]


def test_to_json_round_trips_unicode() -> None:
    plan = ForkPlan(
        parent_run_id="r",
        parent_node_id="n",
        parent_node_name="研究",
        parent_node_index=0,
        child_thread_id="t-fork",
        overrides={"note": "你好"},
    )
    parsed = json.loads(plan.to_json())
    assert parsed["parent_node_name"] == "研究"
    assert parsed["overrides"]["note"] == "你好"


def test_dump_creates_parent_dirs_and_adds_trailing_newline(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "dir" / "plan.json"
    plan = _minimal_plan()
    written = plan.dump(target)
    assert written == target
    text = target.read_text(encoding="utf-8")
    assert text.endswith("\n")
    reloaded = load_plan(target)
    assert reloaded.parent_run_id == plan.parent_run_id
    assert reloaded.overrides == plan.overrides


# ---------------------------------------------------------------------------
# load_plan / plan_from_dict — validation
# ---------------------------------------------------------------------------


def test_load_plan_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_plan(tmp_path / "nope.json")


def test_load_plan_invalid_json(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{ not json ", encoding="utf-8")
    with pytest.raises(ForkPlanError, match="invalid JSON"):
        load_plan(bad)


def test_plan_from_dict_rejects_non_object() -> None:
    with pytest.raises(ForkPlanError, match="JSON object"):
        plan_from_dict([1, 2])  # type: ignore[arg-type]


def test_plan_from_dict_rejects_missing_version() -> None:
    with pytest.raises(ForkPlanError, match="chronos_fork_plan_version"):
        plan_from_dict({"parent_run_id": "x"})


def test_plan_from_dict_rejects_future_version() -> None:
    with pytest.raises(ForkPlanError, match="unsupported fork plan version"):
        plan_from_dict(
            {
                "chronos_fork_plan_version": 99,
                "parent_run_id": "r",
                "parent_node_id": "n",
                "parent_node_name": "x",
                "parent_node_index": 0,
                "child_thread_id": "t",
                "overrides": {},
            }
        )


def test_plan_from_dict_reports_missing_required() -> None:
    with pytest.raises(ForkPlanError, match="missing required fields"):
        plan_from_dict(
            {
                "chronos_fork_plan_version": FORK_PLAN_VERSION,
                "parent_run_id": "r",
                # missing parent_node_id, parent_node_name, etc.
            }
        )


def test_plan_from_dict_rejects_non_dict_overrides() -> None:
    with pytest.raises(ForkPlanError, match="overrides"):
        plan_from_dict(
            {
                "chronos_fork_plan_version": FORK_PLAN_VERSION,
                "parent_run_id": "r",
                "parent_node_id": "n",
                "parent_node_name": "x",
                "parent_node_index": 0,
                "child_thread_id": "t",
                "overrides": [("a", 1)],
            }
        )


def test_plan_from_dict_rejects_bad_tags() -> None:
    with pytest.raises(ForkPlanError, match="tags"):
        plan_from_dict(
            {
                "chronos_fork_plan_version": FORK_PLAN_VERSION,
                "parent_run_id": "r",
                "parent_node_id": "n",
                "parent_node_name": "x",
                "parent_node_index": 0,
                "child_thread_id": "t",
                "overrides": {},
                "tags": ["ok", 42],
            }
        )


# ---------------------------------------------------------------------------
# ForkPlan.to_python -- ADR-013 alt C, pastable Python stub
# ---------------------------------------------------------------------------


def _sample_plan() -> ForkPlan:
    return ForkPlan(
        parent_run_id="run-abc123",
        parent_node_id="node-xyz",
        parent_node_name="research",
        parent_node_index=3,
        child_thread_id="thread-fork-001",
        overrides={"research": "use Bing", "max_results": 5},
        reason="try cheaper search",
        tags=["experiment", "cost-reduction"],
    )


def test_to_python_is_valid_python_source() -> None:
    """Generated stub must compile under Python 3.11+."""
    src = _sample_plan().to_python()
    compile(src, "<generated>", "exec")


def test_to_python_inlines_fork_kwargs() -> None:
    """Stub must inline every recorder_kwargs() field as a Python literal."""
    plan = _sample_plan()
    src = plan.to_python()
    kwargs = plan.recorder_kwargs()
    # Inlined kwargs appear as ``key=repr(value),`` -- check each key shows up.
    for key in kwargs:
        assert f"{key}=" in src, f"missing kwarg: {key}"
    # Sanity: the stub must NOT fall back to reading the JSON file.
    assert "load_plan" not in src
    assert ".json" not in src


def test_to_python_contains_todo_user_markers() -> None:
    """Two TODO(user) blocks must be present so the user knows what to wire."""
    src = _sample_plan().to_python()
    assert src.count("TODO(user)") >= 2


def test_to_python_includes_provenance_header() -> None:
    """Docstring header must carry plan provenance for audit."""
    plan = _sample_plan()
    src = plan.to_python()
    assert plan.parent_run_id in src
    assert plan.child_thread_id in src
    assert plan.chronos_version in src
    assert plan.generated_at in src


def test_to_python_custom_variable_names() -> None:
    """recorder_var / graph_var let the caller match their own code."""
    src = _sample_plan().to_python(recorder_var="rec", graph_var="my_graph")
    assert "rec.fork(" in src
    assert "my_graph," in src
    assert "my_graph.invoke(" in src
    # Default names should NOT appear when overridden.
    assert "recorder.fork(" not in src


def test_to_python_handles_no_reason() -> None:
    """reason=None must not raise and must produce a visible placeholder."""
    plan = ForkPlan(
        parent_run_id="run-x",
        parent_node_id="node-y",
        parent_node_name="n",
        parent_node_index=0,
        child_thread_id="t",
        overrides={},
        reason=None,
    )
    src = plan.to_python()
    compile(src, "<generated>", "exec")
    assert "(no reason provided)" in src


def test_to_python_ends_with_single_newline() -> None:
    """Safe-to-pipe contract: exactly one trailing newline."""
    src = _sample_plan().to_python()
    assert src.endswith("\n")
    assert not src.endswith("\n\n")


# --- R23-A regression tests: stub must be executable, not just compilable ---


def test_to_python_executable_with_mocked_recorder_and_graph() -> None:
    """R23-A regression: the generated stub must *run*, not just compile.

    We exec the stub with a mock recorder (context-manager returning a
    ForkRef-shaped object) and a mock graph (no-op .invoke). This guards
    against field-name typos in the ``ref.XXX`` access at the end of the
    stub. Regression for R22 bug where stub used ``ref.run_id`` but
    ForkRef exposes ``child_run_id``.
    """
    from contextlib import contextmanager
    from dataclasses import dataclass

    @dataclass
    class _FakeForkRef:
        # Must carry at minimum the fields the stub touches after exit.
        child_run_id: str | None = None
        fork_id: str | None = None
        node_ids: list[str] | None = None

    class _FakeRecorder:
        def __init__(self) -> None:
            self.fork_calls: list[dict] = []

        @contextmanager
        def fork(self, graph, **kwargs):
            self.fork_calls.append(kwargs)
            ref = _FakeForkRef()
            yield ref
            # After yield: populate as the real recorder does.
            ref.child_run_id = "fake-child-run-id"

    class _FakeGraph:
        def __init__(self) -> None:
            self.invocations: list[tuple] = []

        def invoke(self, state, cfg):
            self.invocations.append((state, cfg))
            return {}

    plan = _sample_plan()
    src = plan.to_python()

    # Capture printed output from the stub.
    import io
    import sys

    stub_globals: dict = {
        "recorder": _FakeRecorder(),
        "graph": _FakeGraph(),
    }
    buf = io.StringIO()
    old_stdout, sys.stdout = sys.stdout, buf
    try:
        exec(compile(src, "<generated>", "exec"), stub_globals)
    finally:
        sys.stdout = old_stdout

    # Recorder.fork was called with every recorder_kwargs value.
    rec = stub_globals["recorder"]
    assert len(rec.fork_calls) == 1
    kwargs = rec.fork_calls[0]
    for k, v in plan.recorder_kwargs().items():
        assert kwargs[k] == v, f"fork kwarg {k!r} mismatch"

    # Graph.invoke called once with (None, {configurable: {thread_id: ...}}).
    gr = stub_globals["graph"]
    assert len(gr.invocations) == 1
    state, cfg = gr.invocations[0]
    assert state is None
    assert cfg == {"configurable": {"thread_id": plan.child_thread_id}}

    # Print line actually reached and used the correct ForkRef field.
    assert "fake-child-run-id" in buf.getvalue(), (
        f"stub print line did not reach/fire or used wrong field; captured={buf.getvalue()!r}"
    )


def test_to_python_example_comments_use_real_import_paths() -> None:
    """R23-A regression: the commented-out example must use real public paths.

    R22 first draft suggested ``from chronos.store.sqlite import SqliteStore``
    and ``SqliteStore("..."); store.open()`` which are both wrong. The
    public API lives at ``chronos.store`` and ``chronos.adapters``, and the
    store is opened via the ``SqliteStore.open(path)`` classmethod used as a
    context manager.
    """
    src = _sample_plan().to_python()
    # Public import paths.
    assert "from chronos.store import SqliteStore" in src
    assert "from chronos.adapters import LangGraphRecorder" in src
    # Correct open idiom.
    assert "SqliteStore.open(" in src
    # Buggy patterns must NOT appear.
    assert "chronos.store.sqlite" not in src
    assert "chronos.adapters.langgraph" not in src
    assert "store.open()" not in src  # bare method call -- not the idiom


def test_to_python_uses_child_run_id_not_run_id() -> None:
    """R23-A regression guard: ``ref.run_id`` is not a valid ForkRef field.

    ForkRef has ``child_run_id``, ``fork_id``, ``node_ids``. Any stub that
    references ``ref.run_id`` will AttributeError at the print line.
    """
    src = _sample_plan().to_python()
    assert "ref.child_run_id" in src
    assert "ref.run_id" not in src


def test_to_python_mentions_checkpointer_persistence_gotcha() -> None:
    """R23-C: stub must warn about the checkpointer-persistence pitfall.

    Child runs only step through graph nodes if the parent and the fork
    share a persistent or cross-call-live checkpointer. An InMemorySaver
    built per factory call produces an empty child (only the fork record,
    zero new node ids). The stub must tell users this before they write
    their graph factory.
    """
    src = _sample_plan().to_python()
    # Must name the concrete failure mode and the concrete fix.
    assert "checkpointer" in src
    assert "SqliteSaver" in src
    # Must point users at the case study for the full explanation.
    assert "fork-via-emit-python" in src
