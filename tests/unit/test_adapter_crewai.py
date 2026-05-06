"""Unit tests for the CrewAI adapter (R52, ADR-021).

Does NOT require a real ``crewai`` install — tests synthesise event
objects via a factory that builds named subclasses of a dataclass base so
``type(event).__name__`` matches the CrewAI event class names the
recorder dispatches on.

For ``record()`` itself we install a minimal fake ``crewai.events``
module tree into ``sys.modules`` via a fixture so the lazy imports
inside ``record()`` succeed without needing the real package.

Coverage:

1. Handler methods → ``_PendingNode`` buffer shape (node_name,
   agent_role, tool_name, kind).
2. ``_drain_buffer_to_store`` end-to-end: Run + Node rows persisted,
   effects classifier fires on TOOL nodes, usage copied from
   ``LLMCallCompletedEvent.usage``.
3. Thread-safe buffering: handlers called concurrently from a
   ``ThreadPoolExecutor`` land every event (no drops under lock).
4. ``record()`` happy path with patched ``crewai.events`` module — CM
   yields a RunRef, subscribes handlers, drains on exit.
5. ``record()`` failure path: exception inside ``with`` → failed-shell
   Run + re-raise.
6. ``record()`` missing crewai: AdapterError with install hint.
7. ``fork()`` raises AdapterError with ADR-021 pointer.
8. Structural conformance: ``CrewAIRecorder`` satisfies
   :class:`RecorderProtocol`; ``crewai_adapter`` satisfies
   :class:`AdapterProtocol`.
9. Adapter factory channels: ``usage_extractor`` rejected, unknown
   adapter-specific kwarg rejected, ``adapter_name`` / ``flush_timeout_s``
   plumbed through.
10. ``node_name`` fallback when ``tool_name`` is missing (SDK drift
    defence).
"""

from __future__ import annotations

import sys
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
from itertools import pairwise
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from chronos.adapters.crewai import CrewAIRecorder, crewai_adapter
from chronos.adapters.crewai.recorder import (
    _DEFAULT_KIND_MAP,
    _extract_usage,
    _llm_node_name,
    _PendingNode,
    _task_node_name,
    _tool_node_name,
)
from chronos.adapters.protocols import (
    AdapterError,
    AdapterProtocol,
    RecorderProtocol,
    RunRef,
)
from chronos.core.models import NodeKind, RunStatus
from chronos.store import SqliteStore

# ---------------------------------------------------------------------------
# Stub CrewAI event factory
# ---------------------------------------------------------------------------


@dataclass
class _BaseStubEvent:
    """Duck-typed base. The recorder reads attributes with getattr(),
    so we only populate what each event class needs per ADR-021 §D3.
    """

    agent_role: str | None = None
    tool_name: str | None = None
    tool_args: Any = None
    task_name: str | None = None
    context: Any = None
    call_id: str | None = None
    model: str | None = None
    usage: dict[str, int] | None = None
    from_cache: bool | None = None


def _ev(cls_name: str, **kwargs: Any) -> _BaseStubEvent:
    """Create an event whose ``type(ev).__name__`` is ``cls_name``.

    The recorder dispatches on the runtime class name (which is how
    CrewAI itself names its event classes), so we synthesise a fresh
    subclass with the right ``__name__`` every call.
    """
    subclass = type(cls_name, (_BaseStubEvent,), {})
    return subclass(**kwargs)  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# SqliteStore fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Any) -> Iterator[SqliteStore]:
    db = tmp_path / "crewai.db"
    with SqliteStore.open(db) as s:
        yield s


# ---------------------------------------------------------------------------
# 1. Handler methods — verify _PendingNode shape
# ---------------------------------------------------------------------------


class TestHandlers:
    def test_tool_started_builds_three_segment_node_name(self, store: SqliteStore) -> None:
        rec = CrewAIRecorder(store)
        ev = _ev(
            "ToolUsageStartedEvent",
            agent_role="Researcher",
            tool_name="web_search",
            tool_args={"q": "weather"},
        )
        rec._on_tool_event(source=None, event=ev)
        assert len(rec._buffer) == 1
        p = rec._buffer[0]
        assert p.node_name == "Researcher:ToolUsageStartedEvent:web_search"
        assert p.kind is NodeKind.TOOL
        assert p.agent_role == "Researcher"
        assert p.tool_name == "web_search"

    def test_tool_name_fallback_when_missing(self, store: SqliteStore) -> None:
        """SDK drift defence — recorder must not crash on missing field."""
        rec = CrewAIRecorder(store)
        ev = _ev("ToolUsageStartedEvent", agent_role="Bot")
        rec._on_tool_event(source=None, event=ev)
        p = rec._buffer[0]
        # Two-segment fallback per _tool_node_name docstring.
        assert p.node_name == "Bot:ToolUsageStartedEvent"
        assert p.kind is NodeKind.TOOL

    def test_llm_completed_extracts_usage(self, store: SqliteStore) -> None:
        rec = CrewAIRecorder(store)
        ev = _ev(
            "LLMCallCompletedEvent",
            agent_role="Researcher",
            call_id="c-42",
            model="gpt-4o-mini",
            usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        )
        rec._on_llm_event(source=None, event=ev)
        p = rec._buffer[0]
        assert p.node_name == "Researcher:LLMCallCompletedEvent:c-42"
        assert p.kind is NodeKind.LLM
        assert p.model_name == "gpt-4o-mini"
        assert p.usage is not None
        assert p.usage.prompt_tokens == 100
        assert p.usage.completion_tokens == 50
        assert p.usage.reasoning_tokens == 0

    def test_llm_started_does_not_extract_usage(self, store: SqliteStore) -> None:
        rec = CrewAIRecorder(store)
        ev = _ev(
            "LLMCallStartedEvent",
            agent_role="Researcher",
            call_id="c-1",
            model="gpt-4o-mini",
            usage={"prompt_tokens": 1},  # would be ignored for Started anyway
        )
        rec._on_llm_event(source=None, event=ev)
        assert rec._buffer[0].usage is None

    def test_llm_missing_agent_role_uses_wildcard(self, store: SqliteStore) -> None:
        rec = CrewAIRecorder(store)
        ev = _ev("LLMCallStartedEvent", call_id="c-5")
        rec._on_llm_event(source=None, event=ev)
        assert rec._buffer[0].node_name == "*:LLMCallStartedEvent:c-5"

    def test_task_event_builds_three_segment(self, store: SqliteStore) -> None:
        rec = CrewAIRecorder(store)
        ev = _ev(
            "TaskStartedEvent",
            agent_role="Writer",
            task_name="summarize_report",
            context={"inputs": "foo"},
        )
        rec._on_task_event(source=None, event=ev)
        p = rec._buffer[0]
        assert p.node_name == "Writer:TaskStartedEvent:summarize_report"
        assert p.kind is NodeKind.FN

    def test_end_event_builds_kickoff_node_name(self, store: SqliteStore) -> None:
        rec = CrewAIRecorder(store)
        ev = _ev("CrewKickoffCompletedEvent")
        rec._on_end_event(source=None, event=ev)
        p = rec._buffer[0]
        assert p.node_name == "*:CrewKickoffCompletedEvent:kickoff"
        assert p.kind is NodeKind.END

    def test_kind_map_override(self, store: SqliteStore) -> None:
        """User can re-map a CrewAI event class to a different NodeKind."""
        rec = CrewAIRecorder(store, kind_map={"ToolUsageStartedEvent": NodeKind.FN})
        ev = _ev("ToolUsageStartedEvent", agent_role="X", tool_name="t")
        rec._on_tool_event(source=None, event=ev)
        assert rec._buffer[0].kind is NodeKind.FN


# ---------------------------------------------------------------------------
# 2. _drain_buffer_to_store end-to-end
# ---------------------------------------------------------------------------


class TestDrain:
    def test_drain_persists_run_and_nodes(self, store: SqliteStore) -> None:
        rec = CrewAIRecorder(store)
        # Simulate a small event sequence the way CrewAI would emit it.
        rec._on_task_event(None, _ev("TaskStartedEvent", agent_role="R", task_name="t1"))
        rec._on_llm_event(None, _ev("LLMCallStartedEvent", agent_role="R", call_id="c1"))
        rec._on_tool_event(
            None,
            _ev(
                "ToolUsageStartedEvent",
                agent_role="R",
                tool_name="web_search",
            ),
        )
        rec._on_tool_event(
            None,
            _ev(
                "ToolUsageFinishedEvent",
                agent_role="R",
                tool_name="web_search",
            ),
        )
        rec._on_llm_event(
            None,
            _ev(
                "LLMCallCompletedEvent",
                agent_role="R",
                call_id="c1",
                model="gpt-4o-mini",
                usage={"prompt_tokens": 10, "completion_tokens": 5},
            ),
        )
        rec._on_task_event(None, _ev("TaskCompletedEvent", agent_role="R", task_name="t1"))
        rec._on_end_event(None, _ev("CrewKickoffCompletedEvent"))

        ref = RunRef(thread_id="thread-A")
        rec._drain_buffer_to_store(ref=ref, task_description="demo", tags=["ci"])

        assert ref.run_id is not None
        assert len(ref.node_ids) == 7
        run = store.get_run(ref.run_id)
        assert run is not None
        assert run.adapter == "crewai"
        assert run.adapter_thread_id == "thread-A"
        assert run.status is RunStatus.COMPLETED
        assert run.tags == ["ci"]

        nodes = store.get_nodes_for_run(ref.run_id)
        assert len(nodes) == 7
        # step_index must be monotonically increasing from 0
        assert [n.step_index for n in nodes] == list(range(7))
        # parent chain wired per-event
        assert nodes[0].parent_node_id is None
        for prev, curr in pairwise(nodes):
            assert curr.parent_node_id == prev.id

        # TOOL nodes carry classified effects in metadata
        tool_nodes = [n for n in nodes if n.kind is NodeKind.TOOL]
        assert len(tool_nodes) == 2
        for n in tool_nodes:
            assert "effects" in n.metadata
            assert n.metadata["event_cls"].startswith("ToolUsage")

        # LLM completion node carries usage
        llm_completed = [
            n
            for n in nodes
            if n.kind is NodeKind.LLM and n.metadata.get("event_cls") == "LLMCallCompletedEvent"
        ]
        assert len(llm_completed) == 1
        assert llm_completed[0].usage is not None
        assert llm_completed[0].usage.prompt_tokens == 10
        assert llm_completed[0].model_name == "gpt-4o-mini"

        # Drain should have cleared the buffer so the recorder is reusable
        assert rec._buffer == []

    def test_drain_empty_buffer_persists_run_with_zero_nodes(self, store: SqliteStore) -> None:
        rec = CrewAIRecorder(store)
        ref = RunRef(thread_id="t-empty")
        rec._drain_buffer_to_store(ref=ref)
        assert ref.run_id is not None
        assert ref.node_ids == []
        run = store.get_run(ref.run_id)
        assert run is not None
        assert run.final_state == {"event_count": 0}

    def test_drain_with_effects_override(self, store: SqliteStore) -> None:
        """User can override effect tags for a specific node_name."""
        rec = CrewAIRecorder(
            store,
            effects_map={"R:ToolUsageStartedEvent:custom_tool": ["net", "dangerous"]},
        )
        rec._on_tool_event(
            None,
            _ev("ToolUsageStartedEvent", agent_role="R", tool_name="custom_tool"),
        )
        ref = RunRef(thread_id="t-override")
        rec._drain_buffer_to_store(ref=ref)
        nodes = store.get_nodes_for_run(ref.run_id)  # type: ignore[arg-type]
        assert nodes[0].metadata["effects"] == ["net", "dangerous"]


# ---------------------------------------------------------------------------
# 3. Thread-safety: concurrent handler dispatch via ThreadPoolExecutor
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_handlers_no_drops(self, store: SqliteStore) -> None:
        """Simulates CrewAI's event-bus ThreadPoolExecutor fan-out (F4).

        100 parallel handler invocations must all land in the buffer.
        """
        rec = CrewAIRecorder(store)
        n = 100

        def fire(i: int) -> None:
            rec._on_tool_event(
                None,
                _ev(
                    "ToolUsageStartedEvent",
                    agent_role=f"A{i % 5}",
                    tool_name=f"t{i}",
                ),
            )

        with ThreadPoolExecutor(max_workers=16) as exe:
            futures = [exe.submit(fire, i) for i in range(n)]
            wait(futures)
            for f in futures:
                # Surface any handler-side exception.
                f.result()

        assert len(rec._buffer) == n
        # Every unique tool_name must be present — no drops.
        names = {p.tool_name for p in rec._buffer}
        assert names == {f"t{i}" for i in range(n)}


# ---------------------------------------------------------------------------
# 4, 5, 6. record() — patched crewai.events module tree
# ---------------------------------------------------------------------------


class _FakeEventBus:
    """Minimal stand-in for ``crewai_event_bus``.

    Captures handler registrations per event type (by class-name) so the
    test can fire events directly after the CM activates subscription.
    ``scoped_handlers()`` is a no-op CM — the fake bus is created fresh
    per test so isolation is implicit.
    """

    def __init__(self) -> None:
        self.handlers: dict[str, list[Any]] = {}
        self.flush_calls: list[float] = []

    def scoped_handlers(self) -> Any:
        bus = self

        class _CM:
            def __enter__(self) -> _FakeEventBus:
                return bus

            def __exit__(
                self,
                exc_type: Any,
                exc: Any,
                tb: Any,
            ) -> None:
                return None

        return _CM()

    def on(self, event_cls: type) -> Any:
        def decorator(fn: Any) -> Any:
            self.handlers.setdefault(event_cls.__name__, []).append(fn)
            return fn

        return decorator

    def flush(self, timeout: float = 0.0) -> None:
        self.flush_calls.append(timeout)

    def emit(self, event: Any) -> None:
        """Fire ``event`` to all handlers registered for its class name."""
        for fn in self.handlers.get(type(event).__name__, []):
            fn(source=None, event=event)


@pytest.fixture
def patched_crewai(monkeypatch: pytest.MonkeyPatch) -> Iterator[_FakeEventBus]:
    """Install a minimal ``crewai.events`` module tree with a fake bus.

    Cleans up on teardown so no cross-test leakage.
    """
    bus = _FakeEventBus()

    # Build stub event class hierarchy
    def _make_cls(name: str) -> type:
        return type(name, (_BaseStubEvent,), {})

    event_names = [
        "ToolUsageStartedEvent",
        "ToolUsageFinishedEvent",
        "TaskStartedEvent",
        "TaskCompletedEvent",
        "LLMCallStartedEvent",
        "LLMCallCompletedEvent",
        "CrewKickoffCompletedEvent",
    ]
    classes = {name: _make_cls(name) for name in event_names}

    # Root crewai + crewai.events with the bus object
    root = ModuleType("crewai")
    events = ModuleType("crewai.events")
    events.crewai_event_bus = bus  # type: ignore[attr-defined]
    types_pkg = ModuleType("crewai.events.types")
    tool_mod = ModuleType("crewai.events.types.tool_usage_events")
    tool_mod.ToolUsageStartedEvent = classes["ToolUsageStartedEvent"]  # type: ignore[attr-defined]
    tool_mod.ToolUsageFinishedEvent = classes["ToolUsageFinishedEvent"]  # type: ignore[attr-defined]
    task_mod = ModuleType("crewai.events.types.task_events")
    task_mod.TaskStartedEvent = classes["TaskStartedEvent"]  # type: ignore[attr-defined]
    task_mod.TaskCompletedEvent = classes["TaskCompletedEvent"]  # type: ignore[attr-defined]
    llm_mod = ModuleType("crewai.events.types.llm_events")
    llm_mod.LLMCallStartedEvent = classes["LLMCallStartedEvent"]  # type: ignore[attr-defined]
    llm_mod.LLMCallCompletedEvent = classes["LLMCallCompletedEvent"]  # type: ignore[attr-defined]
    crew_mod = ModuleType("crewai.events.types.crew_events")
    crew_mod.CrewKickoffCompletedEvent = classes["CrewKickoffCompletedEvent"]  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "crewai", root)
    monkeypatch.setitem(sys.modules, "crewai.events", events)
    monkeypatch.setitem(sys.modules, "crewai.events.types", types_pkg)
    monkeypatch.setitem(sys.modules, "crewai.events.types.tool_usage_events", tool_mod)
    monkeypatch.setitem(sys.modules, "crewai.events.types.task_events", task_mod)
    monkeypatch.setitem(sys.modules, "crewai.events.types.llm_events", llm_mod)
    monkeypatch.setitem(sys.modules, "crewai.events.types.crew_events", crew_mod)

    # Stash the classes so tests can construct events with the right types
    bus._classes = classes  # type: ignore[attr-defined]

    yield bus


class TestRecordCM:
    def test_record_happy_path(self, store: SqliteStore, patched_crewai: _FakeEventBus) -> None:
        rec = CrewAIRecorder(store, flush_timeout_s=2.5)
        classes: dict[str, type] = patched_crewai._classes  # type: ignore[attr-defined]

        with rec.record(None, thread_id="t-happy") as ref:
            # User-side: emit a short run through the fake bus
            patched_crewai.emit(classes["TaskStartedEvent"](agent_role="R", task_name="t1"))
            patched_crewai.emit(
                classes["ToolUsageStartedEvent"](agent_role="R", tool_name="web_search")
            )
            patched_crewai.emit(
                classes["ToolUsageFinishedEvent"](agent_role="R", tool_name="web_search")
            )
            patched_crewai.emit(classes["TaskCompletedEvent"](agent_role="R", task_name="t1"))
            # simulate CrewOutput
            ref.submit_result(SimpleNamespace(raw="done"))  # type: ignore[attr-defined]

        assert ref.run_id is not None
        assert len(ref.node_ids) == 4
        # flush was called (at least once) on clean exit
        assert patched_crewai.flush_calls == [2.5]

        run = store.get_run(ref.run_id)
        assert run is not None
        assert run.status is RunStatus.COMPLETED
        assert run.final_state is not None
        assert run.final_state["crew_output_raw"] == "done"
        assert run.final_state["event_count"] == 4

    def test_record_exception_inside_with(
        self, store: SqliteStore, patched_crewai: _FakeEventBus
    ) -> None:
        rec = CrewAIRecorder(store)

        with (
            pytest.raises(RuntimeError, match="kickoff boom"),
            rec.record(None, thread_id="t-fail") as ref,
        ):
            # Emit one event then raise — recorder should persist a
            # failed-shell Run and not record the event as if the
            # run completed.
            patched_crewai.emit(
                patched_crewai._classes[  # type: ignore[attr-defined]
                    "TaskStartedEvent"
                ](agent_role="R", task_name="t1")
            )
            raise RuntimeError("kickoff boom")

        assert ref.run_id is not None
        assert ref.node_ids == []
        run = store.get_run(ref.run_id)
        assert run is not None
        assert run.status is RunStatus.FAILED
        assert run.metadata is not None
        assert "kickoff boom" in run.metadata["error"]

    def test_record_missing_crewai_raises(
        self, store: SqliteStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No crewai.events module → AdapterError with install hint."""
        # Wipe any installed crewai modules so the lazy import fails.
        for modname in list(sys.modules):
            if modname == "crewai" or modname.startswith("crewai."):
                monkeypatch.delitem(sys.modules, modname, raising=False)
        # Also block future imports.
        import builtins

        real_import = builtins.__import__

        def blocking_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "crewai.events" or name.startswith("crewai."):
                raise ImportError(f"No module named {name!r}")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", blocking_import)

        rec = CrewAIRecorder(store)
        with (
            pytest.raises(
                AdapterError,
                match=r"crewai.*not installed|chronos-agent\[crewai\]",
            ),
            rec.record(None, thread_id="t-no-crewai"),
        ):
            pass


# ---------------------------------------------------------------------------
# 7. fork() not implemented
# ---------------------------------------------------------------------------


class TestForkDeferred:
    def test_fork_raises_adapter_error(self, store: SqliteStore) -> None:
        rec = CrewAIRecorder(store)
        with (
            pytest.raises(AdapterError, match=r"not implemented.*ADR-021"),
            rec.fork(
                None,
                parent_run_id="r1",
                at_node_id="n1",
                child_thread_id="c1",
            ),
        ):
            pass


# ---------------------------------------------------------------------------
# 8. Structural conformance
# ---------------------------------------------------------------------------


class TestConformance:
    def test_recorder_satisfies_protocol(self, store: SqliteStore) -> None:
        rec = CrewAIRecorder(store)
        assert isinstance(rec, RecorderProtocol)

    def test_adapter_satisfies_protocol(self) -> None:
        assert isinstance(crewai_adapter, AdapterProtocol)
        assert crewai_adapter.name == "crewai"
        assert "0.80" in crewai_adapter.version_constraint


# ---------------------------------------------------------------------------
# 9. Adapter factory channels
# ---------------------------------------------------------------------------


class TestAdapterFactory:
    def test_build_recorder_default(self, store: SqliteStore) -> None:
        rec = crewai_adapter.build_recorder(store)
        assert isinstance(rec, CrewAIRecorder)
        assert rec._adapter_name == "crewai"
        assert rec._flush_timeout_s == 5.0

    def test_build_recorder_custom_name_and_flush(self, store: SqliteStore) -> None:
        rec = crewai_adapter.build_recorder(store, adapter_name="crewai-prod", flush_timeout_s=10.0)
        assert rec._adapter_name == "crewai-prod"
        assert rec._flush_timeout_s == 10.0

    def test_build_recorder_rejects_usage_extractor(self, store: SqliteStore) -> None:
        with pytest.raises(AdapterError, match="usage_extractor"):
            crewai_adapter.build_recorder(
                store,
                usage_extractor=lambda ev: None,  # type: ignore[arg-type]
            )

    def test_build_recorder_rejects_unknown_kwarg(self, store: SqliteStore) -> None:
        with pytest.raises(AdapterError, match="unknown adapter-specific"):
            crewai_adapter.build_recorder(store, bogus_kwarg=True)

    def test_build_recorder_with_kind_map(self, store: SqliteStore) -> None:
        rec = crewai_adapter.build_recorder(store, kind_map={"TaskStartedEvent": NodeKind.LLM})
        assert rec._kind_map["TaskStartedEvent"] is NodeKind.LLM
        # Defaults still present for other event classes
        assert rec._kind_map["ToolUsageStartedEvent"] is NodeKind.TOOL


# ---------------------------------------------------------------------------
# 10. Pure helper coverage — module-level functions
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_default_kind_map_covers_7_event_classes(self) -> None:
        assert len(_DEFAULT_KIND_MAP) == 7
        assert _DEFAULT_KIND_MAP["ToolUsageStartedEvent"] is NodeKind.TOOL
        assert _DEFAULT_KIND_MAP["LLMCallCompletedEvent"] is NodeKind.LLM
        assert _DEFAULT_KIND_MAP["CrewKickoffCompletedEvent"] is NodeKind.END

    def test_extract_usage_handles_dict(self) -> None:
        ev = _ev("LLMCallCompletedEvent", usage={"prompt_tokens": 3, "completion_tokens": 7})
        u = _extract_usage(ev)
        assert u is not None
        assert u.prompt_tokens == 3
        assert u.completion_tokens == 7

    def test_extract_usage_returns_none_when_absent(self) -> None:
        ev = _ev("LLMCallCompletedEvent")
        assert _extract_usage(ev) is None

    def test_extract_usage_returns_none_for_non_dict(self) -> None:
        ev = _ev("LLMCallCompletedEvent")
        ev.usage = "not-a-dict"  # type: ignore[assignment]
        assert _extract_usage(ev) is None

    def test_extract_usage_returns_none_when_both_keys_missing(self) -> None:
        ev = _ev("LLMCallCompletedEvent", usage={"total_tokens": 10})
        assert _extract_usage(ev) is None

    def test_tool_node_name_wildcard_agent(self) -> None:
        ev = _ev("ToolUsageStartedEvent", tool_name="web")
        assert _tool_node_name(ev) == "*:ToolUsageStartedEvent:web"

    def test_llm_node_name_unknown_call_id(self) -> None:
        ev = _ev("LLMCallStartedEvent", agent_role="A")
        assert _llm_node_name(ev) == "A:LLMCallStartedEvent:unknown"

    def test_task_node_name_unknown_task(self) -> None:
        ev = _ev("TaskStartedEvent")
        assert _task_node_name(ev) == "*:TaskStartedEvent:unknown"

    def test_pending_node_observed_at_auto(self) -> None:
        p = _PendingNode(event_cls="X", node_name="a:X:t", kind=NodeKind.TOOL)
        assert p.observed_at is not None
        # Lock is its own type and should be unique per recorder
        rec1 = CrewAIRecorder.__new__(CrewAIRecorder)
        rec1._lock = threading.Lock()
        rec1._buffer = []
        assert rec1._lock is not None
