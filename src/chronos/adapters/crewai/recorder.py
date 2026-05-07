"""CrewAI adapter recorder — ADR-021 event-bus recorder.

See :mod:`chronos.adapters.crewai` package docstring and ADR-021 for the
architectural rationale. This module implements the record half of
:class:`~chronos.adapters.protocols.RecorderProtocol`; ``fork()`` raises
:class:`AdapterError` (Phase 4 candidate; parallels AutoGen's R33-A
record-only stance).

.. warning::

   The recorder subscribes to ``crewai_event_bus`` inside
   ``record()``'s ``scoped_handlers()`` context manager. ``emit()`` on
   that bus is **not synchronous** — it dispatches handlers on a
   ``ThreadPoolExecutor`` and returns a ``concurrent.futures.Future``.
   Two consequences follow (ADR-021 §D1, §D2):

   1. The staging buffer is written from handler threads, so it MUST be
      protected by a ``threading.Lock``. The recorder manages this
      internally; callers don't need to care.
   2. ``crewai_event_bus.flush(timeout=...)`` MUST be called before the
      recorder reads the buffer, or same-class emits within a
      synchronous caller can race past the CM exit. The recorder does
      this in its ``finally`` block — again, transparent to callers.

   If you find yourself adding handlers outside the recorder, remember:
   without ``flush()``, what you read may not be what you emitted.

Event → Node mapping (default, see ADR-021 §D4 for overrides):

+---------------------------------+---------------------+
| CrewAI event class              | Default NodeKind    |
+=================================+=====================+
| ``TaskStartedEvent``            | ``FN``              |
+---------------------------------+---------------------+
| ``TaskCompletedEvent``          | ``FN``              |
+---------------------------------+---------------------+
| ``ToolUsageStartedEvent``       | ``TOOL``            |
+---------------------------------+---------------------+
| ``ToolUsageFinishedEvent``      | ``TOOL``            |
+---------------------------------+---------------------+
| ``LLMCallStartedEvent``         | ``LLM``             |
+---------------------------------+---------------------+
| ``LLMCallCompletedEvent``       | ``LLM``             |
+---------------------------------+---------------------+
| ``CrewKickoffCompletedEvent``   | ``END``             |
+---------------------------------+---------------------+

``node_name`` is three-segment per ADR-020 (and F1 of spike12):

- Tool: ``"{agent_role}:{EventClassName}:{tool_name}"``
- LLM:  ``"{agent_role or '*'}:{EventClassName}:{call_id}"``
- Task: ``"{agent_role or '*'}:{EventClassName}:{task_name}"``
- End:  ``"*:{EventClassName}:kickoff"``

The R44-A effect classifier only fires on TOOL nodes, so the
identity-token third segment for LLM/Task/End is classifier-inert by
construction (ADR-021 §D3).
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from chronos.adapters.effects import classify_effects
from chronos.adapters.protocols import AdapterError, ForkRef, RunRef
from chronos.core.models import Node, NodeKind, Run, RunStatus, Usage
from chronos.store import SqliteStore

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Default event-class → NodeKind mapping (ADR-021 §D4)
# ---------------------------------------------------------------------------

_DEFAULT_KIND_MAP: dict[str, NodeKind] = {
    "TaskStartedEvent": NodeKind.FN,
    "TaskCompletedEvent": NodeKind.FN,
    "ToolUsageStartedEvent": NodeKind.TOOL,
    "ToolUsageFinishedEvent": NodeKind.TOOL,
    "LLMCallStartedEvent": NodeKind.LLM,
    "LLMCallCompletedEvent": NodeKind.LLM,
    "CrewKickoffCompletedEvent": NodeKind.END,
}

# Event classes the recorder actively subscribes to. Agent-level events
# (``AgentExecutionStartedEvent`` / ``AgentExecutionCompletedEvent``) are
# deliberately excluded in the MVP — they'd double-count against
# task+tool+llm spans. See ADR-021 §D4 and the §Follow-ups entry for
# opt-in support.
_SUBSCRIBED_CLASSES: frozenset[str] = frozenset(_DEFAULT_KIND_MAP)

# Event classes that the classifier should be able to tag from node_name
# alone. Must match the tool-event family because the regex library in
# ``chronos.adapters.effects`` is tool-name-shaped (R44-A).
_TOOL_EVENT_CLASSES: frozenset[str] = frozenset({"ToolUsageStartedEvent", "ToolUsageFinishedEvent"})


# ---------------------------------------------------------------------------
# Staging buffer entry
# ---------------------------------------------------------------------------


@dataclass
class _PendingNode:
    """Intermediate representation of a Node, buffered between an event
    handler and the post-flush drain.

    Event handlers run on CrewAI's ``ThreadPoolExecutor``, so they must
    not touch the :class:`SqliteStore` directly. Instead, they build
    this thin dataclass and push it onto
    :attr:`CrewAIRecorder._buffer` under
    :attr:`CrewAIRecorder._lock`. After
    ``crewai_event_bus.flush(timeout=...)`` in ``record()``'s
    ``finally`` block, the main thread walks the buffer and writes
    every entry in a single :meth:`SqliteStore.transaction`.
    """

    event_cls: str
    node_name: str
    kind: NodeKind
    agent_role: str | None = None
    tool_name: str | None = None
    task_name: str | None = None
    call_id: str | None = None
    model_name: str | None = None
    usage: Usage | None = None
    state_after: dict[str, Any] = field(default_factory=dict)
    # Millisecond-resolution timestamp captured by the handler thread.
    # Used only to preserve emission order if two handlers race at the
    # same wall-clock second; the buffer append itself is FIFO under
    # the lock so the order is already well-defined.
    observed_at: datetime = field(default_factory=lambda: datetime.now(UTC))


# ---------------------------------------------------------------------------
# node_name builders — mirror ADR-020 three-segment shape
# ---------------------------------------------------------------------------


def _tool_node_name(event: Any) -> str:
    """Build the three-segment ``node_name`` for a ToolUsage*Event.

    Per ADR-021 §D3 / F1: ``tool_name`` and ``agent_role`` are both
    top-level fields on CrewAI's ``ToolUsage*Event``, so we build the
    shape with a pure string join. No reflection, no content parsing.

    Defensive fallback: if ``tool_name`` is missing (SDK drift), we
    emit ``"{agent_role}:{EventClassName}"`` and let the classifier
    miss gracefully rather than crash.
    """
    cls_name = type(event).__name__
    agent_role = getattr(event, "agent_role", None) or "*"
    tool_name = getattr(event, "tool_name", None)
    if not tool_name:
        return f"{agent_role}:{cls_name}"
    return f"{agent_role}:{cls_name}:{tool_name}"


def _llm_node_name(event: Any) -> str:
    """Build the three-segment ``node_name`` for an LLMCall*Event.

    The third segment is ``call_id``, which threads ``Started`` and
    ``Completed`` events together (F3 of spike12). Classifier-inert:
    the effects classifier only fires on TOOL kinds.
    """
    cls_name = type(event).__name__
    agent_role = getattr(event, "agent_role", None) or "*"
    call_id = getattr(event, "call_id", None) or "unknown"
    return f"{agent_role}:{cls_name}:{call_id}"


def _task_node_name(event: Any) -> str:
    """Build the three-segment ``node_name`` for a Task*Event."""
    cls_name = type(event).__name__
    agent_role = getattr(event, "agent_role", None) or "*"
    task_name = getattr(event, "task_name", None) or "unknown"
    return f"{agent_role}:{cls_name}:{task_name}"


def _end_node_name(event: Any) -> str:
    """Build the ``node_name`` for a CrewKickoffCompletedEvent.

    Kept shape-compatible with the other three builders for column
    alignment in CLI / Web views.
    """
    cls_name = type(event).__name__
    return f"*:{cls_name}:kickoff"


def _extract_usage(event: Any) -> Usage | None:
    """Copy LLMCallCompletedEvent.usage verbatim into :class:`Usage`.

    CrewAI models ``usage`` as a plain ``dict`` with
    ``prompt_tokens`` / ``completion_tokens`` / ``total_tokens`` keys
    (F3 of spike12). ``reasoning_tokens`` stays 0 — CrewAI doesn't
    surface it (same as AutoGen; ADR-021 §D7).
    """
    raw = getattr(event, "usage", None)
    if raw is None:
        return None
    if not isinstance(raw, dict):
        return None
    prompt = raw.get("prompt_tokens")
    completion = raw.get("completion_tokens")
    if prompt is None and completion is None:
        return None
    return Usage(
        prompt_tokens=int(prompt or 0),
        completion_tokens=int(completion or 0),
        reasoning_tokens=0,
    )


# ---------------------------------------------------------------------------
# Recorder
# ---------------------------------------------------------------------------


class CrewAIRecorder:
    """Records CrewAI ``Crew.kickoff()`` executions into a :class:`SqliteStore`.

    Conforms to ADR-016 :class:`RecorderProtocol` at the signature level.
    The recorder subscribes to the CrewAI event bus inside ``record()``'s
    ``scoped_handlers()`` CM (D1), buffers node-building work in a
    thread-safe list (D2), and drains to the store after
    ``crewai_event_bus.flush()`` (D1 barrier).

    Args:
        store: Persistence target.
        adapter_name: Written to ``Run.adapter``. Default ``"crewai"``.
        kind_map: Optional per-event-class override. Merged over
            :data:`_DEFAULT_KIND_MAP`.
        effects_map: Optional per-node-name override for the R44-A
            effects classifier.
        flush_timeout_s: Seconds to wait for
            ``crewai_event_bus.flush(...)`` in the CM ``finally`` block.
            Default ``5.0``. Raise this if your crew does heavy
            fan-out; lower it only if you know handlers are cheap.
    """

    def __init__(
        self,
        store: SqliteStore,
        *,
        adapter_name: str = "crewai",
        kind_map: dict[str, NodeKind] | None = None,
        effects_map: dict[str, list[str]] | None = None,
        flush_timeout_s: float = 5.0,
    ) -> None:
        self._store = store
        self._adapter_name = adapter_name
        self._kind_map: dict[str, NodeKind] = {**_DEFAULT_KIND_MAP}
        if kind_map:
            self._kind_map.update(kind_map)
        self._effects_map: dict[str, list[str]] = dict(effects_map or {})
        self._flush_timeout_s = float(flush_timeout_s)
        # Per-run buffer + lock — re-initialized inside record() so
        # recorder instances can be reused across runs.
        self._lock = threading.Lock()
        self._buffer: list[_PendingNode] = []

    # ------------------------------------------------------------------
    # kind resolution
    # ------------------------------------------------------------------

    def _kind_for(self, event: Any) -> NodeKind:
        cls = type(event).__name__
        return self._kind_map.get(cls, NodeKind.FN)

    # ------------------------------------------------------------------
    # Handler methods (thread-unsafe on their own; push through lock)
    # ------------------------------------------------------------------

    def _append(self, pending: _PendingNode) -> None:
        with self._lock:
            self._buffer.append(pending)

    def _on_tool_event(self, source: Any, event: Any) -> None:
        """Handler for ToolUsage{Started,Finished}Event.

        ``source`` is supplied by CrewAI's event bus (the object that
        emitted the event, usually the tool instance). The recorder
        doesn't currently use it.
        """
        del source
        pending = _PendingNode(
            event_cls=type(event).__name__,
            node_name=_tool_node_name(event),
            kind=self._kind_for(event),
            agent_role=getattr(event, "agent_role", None),
            tool_name=getattr(event, "tool_name", None),
            task_name=getattr(event, "task_name", None),
            state_after={
                "tool_name": getattr(event, "tool_name", None),
                "tool_args": getattr(event, "tool_args", None),
                "agent_role": getattr(event, "agent_role", None),
                "from_cache": getattr(event, "from_cache", None),
            },
        )
        self._append(pending)

    def _on_task_event(self, source: Any, event: Any) -> None:
        """Handler for Task{Started,Completed}Event."""
        del source
        pending = _PendingNode(
            event_cls=type(event).__name__,
            node_name=_task_node_name(event),
            kind=self._kind_for(event),
            agent_role=getattr(event, "agent_role", None),
            task_name=getattr(event, "task_name", None),
            state_after={
                "task_name": getattr(event, "task_name", None),
                "context": getattr(event, "context", None),
            },
        )
        self._append(pending)

    def _on_llm_event(self, source: Any, event: Any) -> None:
        """Handler for LLMCall{Started,Completed}Event."""
        del source
        cls_name = type(event).__name__
        usage = _extract_usage(event) if cls_name == "LLMCallCompletedEvent" else None
        model_name = getattr(event, "model", None)
        pending = _PendingNode(
            event_cls=cls_name,
            node_name=_llm_node_name(event),
            kind=self._kind_for(event),
            agent_role=getattr(event, "agent_role", None),
            call_id=getattr(event, "call_id", None),
            model_name=model_name,
            usage=usage,
            state_after={
                "call_id": getattr(event, "call_id", None),
                "model": model_name,
            },
        )
        self._append(pending)

    def _on_end_event(self, source: Any, event: Any) -> None:
        """Handler for CrewKickoffCompletedEvent."""
        del source
        pending = _PendingNode(
            event_cls=type(event).__name__,
            node_name=_end_node_name(event),
            kind=self._kind_for(event),
            state_after={},
        )
        self._append(pending)

    # ------------------------------------------------------------------
    # record() — sync CM (ADR-021 §D1, §D5)
    # ------------------------------------------------------------------

    @contextmanager
    def record(
        self,
        runtime: Any,
        *,
        thread_id: str,
        task_description: str | None = None,
        tags: list[str] | None = None,
    ) -> Iterator[RunRef]:
        """Record a CrewAI ``Crew.kickoff()`` execution.

        The user is expected to call ``crew.kickoff(...)`` (sync, no
        ``asyncio.run`` — ADR-021 §D5 / F6) inside the ``with`` block
        and optionally pass the returned ``CrewOutput`` via
        :meth:`RunRef.submit_result` (attached below) so the recorder
        can stamp ``Run.final_state`` with the crew output.

        Args:
            runtime: The CrewAI ``Crew`` instance. Stored only for
                identity purposes — the recorder never introspects it
                (ADR-016 A5). Pass ``None`` if you have no handle.
            thread_id: User-supplied identifier. Persisted as
                ``Run.adapter_thread_id``.
            task_description: Optional free-form description.
            tags: Optional list of string tags.

        Yields:
            A :class:`RunRef` extended with :meth:`submit_result`. On
            successful exit ``ref.run_id`` and ``ref.node_ids`` are
            populated. On exception inside the ``with`` block a failed
            Run is persisted and the exception re-raised.
        """
        del runtime  # ADR-016 A5: recorder does not introspect runtime.
        ref = RunRef(thread_id=thread_id)

        # Reset per-run buffer so the same recorder can be reused.
        with self._lock:
            self._buffer = []

        # Stash a final-state channel on the ref; hidden-but-usable, same
        # pattern as AutoGen's ``submit_result``.
        captured: dict[str, Any] = {"result": None}

        def submit_result(result: Any) -> None:
            captured["result"] = result

        ref.submit_result = submit_result  # type: ignore[attr-defined]

        # We import + subscribe lazily so the module is importable without
        # ``crewai`` in the environment (test suite & packaging use the
        # optional extra).
        try:
            from crewai.events import crewai_event_bus
        except ImportError as e:
            raise AdapterError(
                "CrewAIRecorder.record(): the 'crewai' package is not "
                "installed. Install the extra with 'pip install "
                "chronos-agent[crewai]' or add crewai>=0.80,<2.0 to your "
                "own deps."
            ) from e

        try:
            # Attempt to import canonical event classes. We import inside
            # the try so a partial / mismatched crewai install raises a
            # clean AdapterError instead of a bare ImportError leaking.
            from crewai.events.types.llm_events import (
                LLMCallCompletedEvent,
                LLMCallStartedEvent,
            )
            from crewai.events.types.task_events import (
                TaskCompletedEvent,
                TaskStartedEvent,
            )
            from crewai.events.types.tool_usage_events import (
                ToolUsageFinishedEvent,
                ToolUsageStartedEvent,
            )
        except ImportError as e:
            raise AdapterError(
                "CrewAIRecorder.record(): crewai>=0.80 is required — one "
                "or more of the ToolUsage/Task/LLMCall event modules is "
                "missing from the installed crewai. See ADR-021 §D8."
            ) from e

        # Optional: CrewKickoffCompletedEvent is the one D4 entry that's
        # lived in multiple locations across CrewAI minor versions. Tolerate
        # its absence — it's a nice-to-have END node, not a correctness
        # requirement.
        crew_end_event: type | None = None
        try:
            from crewai.events.types.crew_events import (
                CrewKickoffCompletedEvent,
            )

            crew_end_event = CrewKickoffCompletedEvent
        except ImportError:  # pragma: no cover — depends on installed crewai
            crew_end_event = None

        try:
            with crewai_event_bus.scoped_handlers():
                # Subscribe recorder handlers within the scoped CM so
                # detach is automatic on exit (F5).
                crewai_event_bus.on(ToolUsageStartedEvent)(self._on_tool_event)
                crewai_event_bus.on(ToolUsageFinishedEvent)(self._on_tool_event)
                crewai_event_bus.on(TaskStartedEvent)(self._on_task_event)
                crewai_event_bus.on(TaskCompletedEvent)(self._on_task_event)
                crewai_event_bus.on(LLMCallStartedEvent)(self._on_llm_event)
                crewai_event_bus.on(LLMCallCompletedEvent)(self._on_llm_event)
                if crew_end_event is not None:
                    crewai_event_bus.on(crew_end_event)(self._on_end_event)

                try:
                    yield ref
                except AdapterError:
                    crewai_event_bus.flush(timeout=self._flush_timeout_s)
                    self._persist_failed_shell(
                        ref=ref,
                        task_description=task_description,
                        tags=tags or [],
                        error="adapter error inside with-block",
                    )
                    raise
                except Exception as exc:
                    crewai_event_bus.flush(timeout=self._flush_timeout_s)
                    self._persist_failed_shell(
                        ref=ref,
                        task_description=task_description,
                        tags=tags or [],
                        error=str(exc),
                    )
                    raise
                else:
                    # ADR-021 §D1 flush barrier — required before reading
                    # the buffer, because emit() dispatches on a
                    # ThreadPoolExecutor (F4).
                    crewai_event_bus.flush(timeout=self._flush_timeout_s)
        finally:
            # scoped_handlers() has now detached everything; safe to leave.
            pass

        # Success path — drain the buffer to the store.
        with self._lock:
            pending_nodes = list(self._buffer)

        self._persist_run_and_nodes(
            ref=ref,
            pending=pending_nodes,
            task_description=task_description,
            tags=tags or [],
            final_result=captured["result"],
            status=RunStatus.COMPLETED,
        )

    # ------------------------------------------------------------------
    # record_from_pending() — test-only hook
    # ------------------------------------------------------------------

    def _drain_buffer_to_store(
        self,
        *,
        ref: RunRef,
        task_description: str | None = None,
        tags: list[str] | None = None,
        final_result: Any = None,
        status: RunStatus = RunStatus.COMPLETED,
    ) -> None:
        """Drain the recorder's internal buffer to the store.

        Intended for **tests only** — production callers go through
        ``record()`` which handles subscription + flush + drain as one
        atomic shape. Tests exercise handlers directly (no real
        ``crewai_event_bus``), then call this to persist.

        Thread-safe: reads the buffer under the same lock the handlers
        use. After drain the buffer is cleared so the recorder can be
        reused in a subsequent call.
        """
        with self._lock:
            pending = list(self._buffer)
            self._buffer = []
        self._persist_run_and_nodes(
            ref=ref,
            pending=pending,
            task_description=task_description,
            tags=tags or [],
            final_result=final_result,
            status=status,
        )

    # ------------------------------------------------------------------
    # fork() — not implemented in v0.4.x (ADR-021 §Follow-ups)
    # ------------------------------------------------------------------

    @contextmanager
    def fork(
        self,
        runtime: Any,
        *,
        parent_run_id: str,
        at_node_id: str,
        overrides: dict[str, Any] | None = None,
        child_thread_id: str,
        reason: str | None = None,
        task_description: str | None = None,
        tags: list[str] | None = None,
    ) -> Iterator[ForkRef]:
        """Not implemented — CrewAI fork is deferred to a later ADR.

        CrewAI's execution is event-driven on a live crew; forking
        requires re-seeding crew state + re-invoking kickoff from a
        checkpoint, which CrewAI's API does not expose as a first-class
        operation. Tracked as a follow-up to ADR-021.
        """
        raise AdapterError(
            "CrewAIRecorder.fork() is not implemented in v0.4.x — tracked "
            "as a follow-up to ADR-021. See adapter package docstring."
        )
        # Unreachable but keeps mypy happy about the generator contract.
        yield ForkRef(  # pragma: no cover
            parent_run_id=parent_run_id,
            at_node_id=at_node_id,
            child_thread_id=child_thread_id,
        )

    # ------------------------------------------------------------------
    # persistence helpers
    # ------------------------------------------------------------------

    def _persist_run_and_nodes(
        self,
        *,
        ref: RunRef,
        pending: list[_PendingNode],
        task_description: str | None,
        tags: list[str],
        final_result: Any,
        status: RunStatus,
    ) -> None:
        run_id = str(uuid.uuid4())
        now = datetime.now(UTC)

        # Build a final_state that reflects the submitted result (if any)
        # and otherwise summarises pending count. Keeps parity with the
        # AutoGen adapter's convention.
        if final_result is not None:
            # CrewAI's CrewOutput has a .raw attribute in recent versions;
            # fall back to repr() for anything else.
            raw = getattr(final_result, "raw", None)
            final_state: dict[str, Any] = {
                "crew_output_raw": raw if isinstance(raw, str) else repr(final_result),
                "event_count": len(pending),
            }
        else:
            final_state = {"event_count": len(pending)}

        run = Run(
            id=run_id,
            adapter=self._adapter_name,
            adapter_thread_id=ref.thread_id,
            status=status,
            started_at=now,
            ended_at=now,
            task_description=task_description,
            initial_state={},
            final_state=final_state,
            tags=list(tags),
        )
        node_ids: list[str] = []
        with self._store.transaction():
            self._store.put_run(run)

            prev_node_id: str | None = None
            for step_index, p in enumerate(pending):
                node_id = str(uuid.uuid4())
                # The effects classifier reads node_name + kind + model_name.
                # Only TOOL events carry tool_name in the third segment, so
                # LLM/Task nodes fall through with an empty tag list
                # naturally (ADR-021 §D3).
                effects = classify_effects(
                    node_name=p.node_name,
                    kind=p.kind,
                    model_name=p.model_name,
                    override=self._effects_map.get(p.node_name),
                )
                metadata: dict[str, Any] = {
                    "event_cls": p.event_cls,
                    "effects": effects,
                }
                if p.agent_role is not None:
                    metadata["agent_role"] = p.agent_role
                if p.tool_name is not None:
                    metadata["tool_name"] = p.tool_name
                if p.task_name is not None:
                    metadata["task_name"] = p.task_name
                if p.call_id is not None:
                    metadata["call_id"] = p.call_id

                node = Node(
                    id=node_id,
                    run_id=run_id,
                    step_index=step_index,
                    node_name=p.node_name,
                    kind=p.kind,
                    parent_node_id=prev_node_id,
                    started_at=now,
                    ended_at=now,
                    state_after=dict(p.state_after),
                    model_name=p.model_name,
                    usage=p.usage,
                    metadata=metadata,
                )
                self._store.put_node(node)
                node_ids.append(node_id)
                prev_node_id = node_id

        ref.run_id = run_id
        ref.node_ids = node_ids

    def _persist_failed_shell(
        self,
        *,
        ref: RunRef,
        task_description: str | None,
        tags: list[str],
        error: str,
    ) -> None:
        run_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        run = Run(
            id=run_id,
            adapter=self._adapter_name,
            adapter_thread_id=ref.thread_id,
            status=RunStatus.FAILED,
            started_at=now,
            ended_at=now,
            task_description=task_description,
            initial_state={},
            final_state=None,
            tags=list(tags),
            metadata={"error": error},
        )
        with self._store.transaction():
            self._store.put_run(run)
        ref.run_id = run_id
        ref.node_ids = []
