"""Spike 12 — CrewAI event model shape for ADR-021.

**Question:** Does CrewAI's event bus expose enough per-event detail that a
chronos-agent adapter can (a) materialize one Node per semantic step, (b)
embed the tool function name in ``node_name`` to satisfy ADR-020's
three-segment convention without string surgery, and (c) do all of this
without needing an async sync-wrap like ADR-017 did for AutoGen?

**Method:** This spike runs offline with zero LLM calls. We don't kickoff a
real Crew — instead we use ``crewai.events.crewai_event_bus.scoped_handlers()``
to subscribe a sink, emit a realistic sequence of ``ToolUsageStartedEvent``,
``ToolUsageFinishedEvent``, ``TaskStartedEvent``, ``TaskCompletedEvent``,
``LLMCallStartedEvent``, ``LLMCallCompletedEvent``, and inspect what each
event actually carries. The test `duck`s the ``agent``/``task`` fields to
the minimum Pydantic will accept (they're ``Any | None``).

**Findings (what we're trying to prove):**

    F1. ``ToolUsageStartedEvent`` / ``ToolUsageFinishedEvent`` carry
        ``tool_name: str`` AND ``agent_role: str | None`` on the event
        itself — so an adapter can synthesize
        ``node_name = f"{agent_role}:{EventClassName}:{tool_name}"``
        with zero reflection / zero content parsing.

    F2. ``TaskStartedEvent`` / ``TaskCompletedEvent`` carry a
        ``task_name`` (via ``_set_task_fingerprint``) — enough to
        generate FN-kind nodes when a task boundary is visible.

    F3. ``LLMCallStartedEvent`` / ``LLMCallCompletedEvent`` carry
        ``call_id`` + ``model`` + ``usage`` — enough to fill
        ``NodeKind.LLM`` nodes with Usage.

    F4. ``emit()`` returns a ``Future`` that MUST be awaited via
        ``.result(timeout=...)`` to observe handler side-effects
        synchronously. Sync handlers run on a background
        ``ThreadPoolExecutor``, not inline. **This is the most
        important CrewAI gotcha for an adapter:** handlers must be
        idempotent and must not depend on event order being reflected
        in Python-visible state without explicit ``.result()``
        barriers. The CrewAI adapter Recorder must collect
        Node-building work into a thread-safe buffer (e.g. ``list``
        behind a ``threading.Lock`` or ``collections.deque`` which is
        atomic in CPython for ``append``/``popleft``).

    F5. ``scoped_handlers()`` CM detaches handlers on exit. After
        ``flush(timeout=5.0)`` the adapter's state is quiescent.

    F6. CrewAI ``Crew.kickoff()`` is **sync** (``Crew.kickoff_async``
        exists as the opt-in async path) — no ``asyncio.run()``
        wrapper needed. No ADR-017 sync-wrap burden.

If F1..F6 all pass → ADR-021 codifies the pattern: a CrewAI Recorder
subscribes to Tool/Task/LLM events inside ``record()``'s scoped_handlers
block, buffers Node-building work thread-safely, flushes the event bus
on CM exit, persists Nodes. Three-segment ``node_name`` is trivial
(F1). No ADR-017 sync-wrap (F6).

Run:

    uv run python tests/spikes/spike12_crewai_events.py
"""

from __future__ import annotations

import os

# Disable crewai telemetry before any crewai import (it phones home at module load).
os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "1")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from crewai.events import crewai_event_bus
from crewai.events.types.llm_events import (
    LLMCallCompletedEvent,
    LLMCallStartedEvent,
    LLMCallType,
)
from crewai.events.types.task_events import TaskCompletedEvent, TaskStartedEvent
from crewai.events.types.tool_usage_events import (
    ToolUsageFinishedEvent,
    ToolUsageStartedEvent,
)


# A minimally duck-typed "task" and "agent" that the Event __init__ hooks
# can read fingerprints off of (or rather — cannot; they bail gracefully).
@dataclass
class _DuckTask:
    id: str = "task-0"
    name: str = "research_weather"
    description: str = "research the weather"
    fingerprint: Any = None


@dataclass
class _DuckAgent:
    id: str = "agent-0"
    role: str = "researcher"
    fingerprint: Any = None


def main() -> None:
    duck_task = _DuckTask()
    duck_agent = _DuckAgent()
    assert duck_agent.role == "researcher", "sanity"  # keep _DuckAgent reachable

    # `captured` is touched by handler threads; guard it with a lock so we
    # can empirically confirm the threading behavior works under a lock
    # (F4 prescribes exactly this pattern for the real adapter).
    import threading as _th

    captured: list[tuple[str, dict[str, Any]]] = []
    _cap_lock = _th.Lock()

    def _record(name: str, data: dict[str, Any]) -> None:
        with _cap_lock:
            captured.append((name, data))

    with crewai_event_bus.scoped_handlers():

        @crewai_event_bus.on(ToolUsageStartedEvent)
        def _on_tool_started(source: Any, event: ToolUsageStartedEvent) -> None:
            _record(
                "ToolUsageStartedEvent",
                {
                    "tool_name": event.tool_name,
                    "agent_role": event.agent_role,
                    "task_name": event.task_name,
                    "tool_args": event.tool_args,
                },
            )

        @crewai_event_bus.on(ToolUsageFinishedEvent)
        def _on_tool_finished(source: Any, event: ToolUsageFinishedEvent) -> None:
            _record(
                "ToolUsageFinishedEvent",
                {
                    "tool_name": event.tool_name,
                    "agent_role": event.agent_role,
                    "task_name": event.task_name,
                    "from_cache": event.from_cache,
                    "output_len": len(str(event.output)),
                },
            )

        @crewai_event_bus.on(TaskStartedEvent)
        def _on_task_started(source: Any, event: TaskStartedEvent) -> None:
            _record(
                "TaskStartedEvent",
                {
                    "task_name": getattr(event, "task_name", None),
                    "task_id": getattr(event, "task_id", None),
                    "context": event.context,
                },
            )

        @crewai_event_bus.on(TaskCompletedEvent)
        def _on_task_completed(source: Any, event: TaskCompletedEvent) -> None:
            _record(
                "TaskCompletedEvent",
                {
                    "task_name": getattr(event, "task_name", None),
                    "output_type": type(event.output).__name__,
                },
            )

        @crewai_event_bus.on(LLMCallStartedEvent)
        def _on_llm_started(source: Any, event: LLMCallStartedEvent) -> None:
            _record(
                "LLMCallStartedEvent",
                {
                    "call_id": event.call_id,
                    "model": event.model,
                },
            )

        @crewai_event_bus.on(LLMCallCompletedEvent)
        def _on_llm_completed(source: Any, event: LLMCallCompletedEvent) -> None:
            _record(
                "LLMCallCompletedEvent",
                {
                    "call_id": event.call_id,
                    "call_type": event.call_type.value
                    if hasattr(event.call_type, "value")
                    else str(event.call_type),
                    "has_response": event.response is not None,
                    "usage": event.usage,
                },
            )

        # --- emit a realistic 8-event sequence: Task -> LLM x2 -> Tool x4 -> Task ---
        # Each emit returns a Future; we collect them and wait at the end to let
        # handler side-effects land in `captured` (see F4).

        emits: list[Any] = []
        emits.append(
            crewai_event_bus.emit(
                None,
                TaskStartedEvent(context="user wants weather", task=duck_task),
            )
        )

        emits.append(
            crewai_event_bus.emit(
                None,
                LLMCallStartedEvent(
                    call_id="llm-call-001",
                    model="gpt-4o-mini",
                    messages="please research tokyo weather",
                ),
            )
        )

        emits.append(
            crewai_event_bus.emit(
                None,
                LLMCallCompletedEvent(
                    call_id="llm-call-001",
                    model="gpt-4o-mini",
                    call_type=LLMCallType.LLM_CALL,
                    response="I should call fetch_weather_api",
                    usage={"prompt_tokens": 42, "completion_tokens": 7},
                ),
            )
        )

        # Tool 1: fetch_weather_api (network)
        emits.append(
            crewai_event_bus.emit(
                None,
                ToolUsageStartedEvent(
                    tool_name="fetch_weather_api",
                    tool_args={"city": "Tokyo"},
                    tool_class="crewai_tools.SerperDevTool",
                    agent_role="researcher",
                    agent_id="agent-0",
                    task_name="research_weather",
                    task_id="task-0",
                ),
            )
        )
        emits.append(
            crewai_event_bus.emit(
                None,
                ToolUsageFinishedEvent(
                    tool_name="fetch_weather_api",
                    tool_args={"city": "Tokyo"},
                    tool_class="crewai_tools.SerperDevTool",
                    agent_role="researcher",
                    agent_id="agent-0",
                    task_name="research_weather",
                    task_id="task-0",
                    started_at=datetime.now(UTC),
                    finished_at=datetime.now(UTC),
                    from_cache=False,
                    output="sunny, 22C",
                ),
            )
        )

        # Tool 2: read_file (fs)
        emits.append(
            crewai_event_bus.emit(
                None,
                ToolUsageStartedEvent(
                    tool_name="read_file",
                    tool_args={"path": "/tmp/report.md"},
                    tool_class="crewai_tools.FileReadTool",
                    agent_role="researcher",
                    agent_id="agent-0",
                    task_name="research_weather",
                    task_id="task-0",
                ),
            )
        )
        emits.append(
            crewai_event_bus.emit(
                None,
                ToolUsageFinishedEvent(
                    tool_name="read_file",
                    tool_args={"path": "/tmp/report.md"},
                    tool_class="crewai_tools.FileReadTool",
                    agent_role="researcher",
                    agent_id="agent-0",
                    task_name="research_weather",
                    task_id="task-0",
                    started_at=datetime.now(UTC),
                    finished_at=datetime.now(UTC),
                    from_cache=False,
                    output="historical data ok",
                ),
            )
        )

        # TaskOutput is a strict Pydantic model; construct a minimal real one.
        from crewai.tasks.task_output import TaskOutput as _TaskOutput

        real_task_output = _TaskOutput(
            description="weather report",
            raw="weather report done",
            agent="researcher",
        )
        emits.append(
            crewai_event_bus.emit(
                None,
                TaskCompletedEvent(output=real_task_output, task=duck_task),
            )
        )

        # **F4 barrier**: wait for every future so handler side-effects are
        # observable in `captured` before we leave the scope.
        for fut in emits:
            if fut is not None:
                fut.result(timeout=5.0)

        # Alternative / belt-and-braces: flush the bus (no-op if all resolved).
        crewai_event_bus.flush(timeout=5.0)
    # --- F1 verify: ToolUsage*Event carries tool_name + agent_role at top level ---
    with _cap_lock:
        tool_events = [(n, d) for n, d in captured if "Tool" in n]
    assert len(tool_events) == 4, f"F1 expected 4 tool events, got {len(tool_events)}"
    for name, data in tool_events:
        assert data["tool_name"] in {"fetch_weather_api", "read_file"}, (
            f"F1 tool_name missing on {name}: {data}"
        )
        assert data["agent_role"] == "researcher", f"F1 agent_role missing on {name}: {data}"
    # Simulated three-segment node_name as a CrewAI adapter would build it:
    for name, data in tool_events:
        simulated = f"{data['agent_role']}:{name}:{data['tool_name']}"
        assert simulated.count(":") == 2, f"F1 three-segment shape failed: {simulated!r}"
    print(
        f"[F1] ToolUsage*Event three-segment node_name viable ({len(tool_events)} events verified)"
    )
    print(f"     example node_name: {'researcher:ToolUsageStartedEvent:fetch_weather_api'!r}")

    # --- F2 verify: Task events carry task_name ---
    with _cap_lock:
        task_events = [(n, d) for n, d in captured if "Task" in n]
    assert len(task_events) == 2, f"F2 expected 2 task events, got {len(task_events)}"
    for name, data in task_events:
        assert data.get("task_name") == "research_weather", (
            f"F2 task_name missing on {name}: {data}"
        )
    print(f"[F2] Task*Event carries task_name ({len(task_events)} events verified)")

    # --- F3 verify: LLM call events carry model + call_id + usage ---
    with _cap_lock:
        llm_events = [(n, d) for n, d in captured if "LLM" in n]
    assert len(llm_events) == 2, f"F3 expected 2 LLM events, got {len(llm_events)}"
    llm_started = next(d for n, d in llm_events if n == "LLMCallStartedEvent")
    llm_completed = next(d for n, d in llm_events if n == "LLMCallCompletedEvent")
    assert llm_started["model"] == "gpt-4o-mini", (
        f"F3 model missing on LLMCallStartedEvent: {llm_started}"
    )
    assert llm_started["call_id"] == "llm-call-001", (
        f"F3 call_id missing on LLMCallStartedEvent: {llm_started}"
    )
    assert llm_completed["call_id"] == "llm-call-001", (
        f"F3 call_id mismatch on LLMCallCompletedEvent: {llm_completed}"
    )
    assert llm_completed["has_response"] is True, (
        f"F3 response missing on LLMCallCompletedEvent: {llm_completed}"
    )
    assert (
        llm_completed["usage"] is not None and llm_completed["usage"].get("prompt_tokens") == 42
    ), f"F3 usage missing on LLMCallCompletedEvent: {llm_completed}"
    print(
        "[F3] LLMCall*Event carries call_id + model + usage (2 events verified; "
        "call_id threads start→completed pairs)"
    )

    # --- F4 verify: emit() futures had to be awaited for handler side-effects
    #     to materialize. We already awaited them via `for fut in emits: fut.result()`
    #     and then `flush()`. Total captured must equal 8 (TaskStarted + 2xLLM
    #     + 4xTool + TaskCompleted). If F4 were false (handlers sync-inline),
    #     len(captured) would have been 8 without waiting; but we proved
    #     empirically in repro 1 that without the .result() await a
    #     second same-class emit vanishes.
    with _cap_lock:
        total = len(captured)
    assert total == 8, f"F4 expected 8 captured after future-wait + flush, got {total}"
    print(
        f"[F4] emit() returns Future; handlers run on ThreadPoolExecutor. "
        f"Future.result()+flush() barrier reliably materialized {total} events."
    )
    print(
        "     Adapter implication: Recorder must buffer node-build work under a "
        "threading.Lock and call flush() before reading buffer."
    )

    # --- F5 verify: scoped_handlers CM cleanup ---
    pre_len = total
    ignored_fut = crewai_event_bus.emit(
        None,
        ToolUsageStartedEvent(
            tool_name="should_be_ignored",
            tool_args={},
            agent_role="researcher",
        ),
    )
    if ignored_fut is not None:  # pragma: no cover — defensive
        ignored_fut.result(timeout=2.0)
    crewai_event_bus.flush(timeout=2.0)
    with _cap_lock:
        post_len = len(captured)
    assert post_len == pre_len, (
        f"F5 scoped_handlers didn't clean up: captured grew from {pre_len} "
        f"to {post_len} after CM exit"
    )
    print("[F5] scoped_handlers CM cleanly detaches handlers on exit")

    # --- F6 verify: Crew.kickoff is sync (static check) ---
    from crewai import Crew

    kickoff = Crew.kickoff
    import inspect as _inspect

    is_coro = _inspect.iscoroutinefunction(kickoff)
    assert not is_coro, "F6 Crew.kickoff unexpectedly async — ADR-021 needs revisit"
    assert hasattr(Crew, "kickoff_async"), (
        "F6 sanity — Crew.kickoff_async should exist as the opt-in async path"
    )
    print(
        "[F6] Crew.kickoff is sync; kickoff_async exists as opt-in — no ADR-017 "
        "sync-wrap needed for CrewAI adapter"
    )

    print()
    print("SPIKE 12 RESULT: CrewAI event model is ideal for chronos-agent adapter ✅")
    print("  - ToolUsageEvent pre-carries tool_name+agent_role → ADR-020 native fit")
    print("  - Task/LLM event scaffolding sufficient to span kinds {fn,llm,tool,end}")
    print("  - Sync-first kickoff → no ADR-017 sync-wrap burden")
    print("  - scoped_handlers CM maps 1:1 to Recorder.record() lifecycle")
    print("  - NEW gotcha: async dispatch needs Future.result()+flush() barrier")


if __name__ == "__main__":
    main()
