"""Linear-pipeline adapter — implements `RecorderProtocol` (ADR-016).

Reference adapter satisfying ADR-014 criterion R1 (implementation half).
Zero external dependencies. Event model intentionally mirrors LangGraph
(discrete step → state snapshot); true event-model divergence testing
is deferred to the AutoGen adapter per R27 risks doc R-1.

A `LinearRuntime` is an ordered sequence of named step functions
``[(node_name, step_fn)]`` where ``step_fn(state: dict) -> dict`` is
pure-ish (any LLM / tool calls happen inside the fn and their outputs
are folded back into the returned state dict).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from chronos.adapters.protocols import AdapterError, ForkRef, RunRef
from chronos.core.models import Fork, Node, NodeKind, Run, RunStatus, Usage
from chronos.store import SqliteStore

# ---------------------------------------------------------------------------
# Public errors + references
# ---------------------------------------------------------------------------
#
# ``AdapterError`` / ``RunRef`` / ``ForkRef`` moved to
# ``chronos.adapters.protocols`` in R31-A (ADR-016 rollout step 2). They are
# re-exported from this module unchanged for backward compatibility.


StepFn = Callable[[dict[str, Any]], dict[str, Any]]
"""A single pipeline step: current state → next state."""


@dataclass
class LinearRuntime:
    """A named linear pipeline of step functions.

    Attributes:
        steps: Ordered list of ``(node_name, step_fn)`` pairs. Node names
            must be unique within a runtime; `LinearRecorder` uses them
            for fork `at_node_id` resolution and diff alignment.
        kind_map: Optional per-node kind override. Missing entries default
            to :attr:`NodeKind.FN`.
    """

    steps: list[tuple[str, StepFn]]
    kind_map: dict[str, NodeKind] = field(default_factory=dict)

    def __post_init__(self) -> None:
        seen: set[str] = set()
        for name, _ in self.steps:
            if name in seen:
                raise AdapterError(
                    f"duplicate node_name={name!r} in LinearRuntime — names must be unique"
                )
            seen.add(name)

    def step_index_of(self, node_name: str) -> int:
        """Return the 0-indexed position of ``node_name`` in :attr:`steps`."""
        for i, (name, _) in enumerate(self.steps):
            if name == node_name:
                return i
        raise AdapterError(f"node_name={node_name!r} not in LinearRuntime")


# ---------------------------------------------------------------------------
# The recorder
# ---------------------------------------------------------------------------


class LinearRecorder:
    """Records :class:`LinearRuntime` executions into a :class:`SqliteStore`.

    Conforms to ADR-016 ``RecorderProtocol`` at the signature level
    (parameter names ``runtime`` / ``thread_id`` / ``parent_run_id``
    match the Protocol). The LangGraph adapter keeps ``graph=`` for
    back-compat; new adapters like this one use ``runtime=`` directly.

    Usage metering:
        A step function MAY place a ``__chronos_usage__`` key in the
        state dict it returns. Three shapes are accepted for parity
        with the LangGraph adapter's ADR-015 UsageResult contract:

        - ``dict`` matching :class:`~chronos.core.models.Usage`
          (``{"prompt_tokens": int, "completion_tokens": int,
          "reasoning_tokens": int, ...}``)
        - A :class:`~chronos.core.models.Usage` instance
        - A duck-typed object exposing ``prompt_tokens`` /
          ``completion_tokens`` / ``reasoning_tokens`` attrs (e.g.
          the adapter-layer ``UsageResult`` dataclass — imported via
          duck typing to avoid creating a hard dep from this zero-dep
          adapter onto the langgraph usage module)

        If present, the key is popped out of ``state_after`` (to keep
        diffs clean) and attached to the node's ``usage`` field. If
        absent, ``node.usage`` is ``None`` — matching ADR-015 Layer 1.

    Args:
        store: Persistence target.
        adapter_name: Name written to ``Run.adapter``. Default
            ``"linear"``. Tests may override.
    """

    def __init__(self, store: SqliteStore, *, adapter_name: str = "linear") -> None:
        self._store = store
        self._adapter_name = adapter_name

    # ------------------------------------------------------------------
    # record() — original runs
    # ------------------------------------------------------------------

    @contextmanager
    def record(
        self,
        runtime: LinearRuntime,
        *,
        thread_id: str,
        initial_state: dict[str, Any] | None = None,
        task_description: str | None = None,
        tags: list[str] | None = None,
    ) -> Iterator[RunRef]:
        """Execute ``runtime`` end-to-end and persist as a canonical Run.

        Unlike the LangGraph adapter (which walks `graph.get_state_history()`
        on exit), the linear adapter executes the pipeline *inline* — it
        has to, because the "runtime" is just data, not a checkpointed
        executor. Each step's pre/post state becomes one :class:`Node`
        row.

        Args:
            runtime: The pipeline to execute.
            thread_id: User-supplied identifier for this execution thread.
                Persisted as ``Run.adapter_thread_id``.
            initial_state: Starting state dict. Defaults to empty dict.
            task_description: Optional free-form description.
            tags: Optional list of string tags.

        Yields:
            A :class:`RunRef`. On successful exit, ``ref.run_id`` and
            ``ref.node_ids`` are populated. On exception inside the
            ``with`` block (which would be a user runtime error — the
            executor itself runs inside this CM), a failed Run is still
            persisted and the exception re-raised.
        """
        ref = RunRef(thread_id=thread_id)
        start_state = dict(initial_state or {})
        try:
            yield ref
            # Execute pipeline AFTER user code inside `with` block, which
            # historically just yields. Mirrors LangGraphRecorder: user is
            # expected to pass configuration via the `with`-scope; the
            # adapter owns execution. Here execution is trivial.
            self._execute_and_persist(
                runtime=runtime,
                ref=ref,
                start_state=start_state,
                status_on_success=RunStatus.COMPLETED,
                task_description=task_description,
                tags=tags or [],
                first_step_index=0,
                first_parent_node_id=None,
                fork_context=None,
            )
        except AdapterError:
            raise
        except Exception as exc:
            # Record a failed run: we need to know how far execution got.
            # _execute_and_persist raised, so we do not have partial Node
            # rows yet; persist an empty Run for visibility.
            self._persist_failed_shell(
                ref=ref,
                task_description=task_description,
                tags=tags or [],
                error=str(exc),
            )
            raise

    # ------------------------------------------------------------------
    # fork() — ADR-005 semantics for linear runtimes
    # ------------------------------------------------------------------

    @contextmanager
    def fork(
        self,
        runtime: LinearRuntime,
        *,
        parent_run_id: str,
        at_node_id: str,
        overrides: dict[str, Any] | None = None,
        child_thread_id: str,
        reason: str | None = None,
        task_description: str | None = None,
        tags: list[str] | None = None,
    ) -> Iterator[ForkRef]:
        """Fork a recorded run: re-run the pipeline from ``at_node_id+1``.

        Semantics (satisfies R-2 postcondition from the risks doc):
        child run starts from parent node's ``state_after`` merged with
        ``overrides``, executes downstream steps only (not the forked
        node itself), and persists lineage via a :class:`Fork` row.

        Unlike LangGraph, there is no checkpointer — we rebuild state
        directly from the parent's persisted ``state_after`` and re-run
        the tail of the pipeline.
        """
        overrides = dict(overrides or {})

        # --- Pre-flight: load parent artifacts and validate ---
        parent_run = self._store.get_run(parent_run_id)
        if parent_run is None:
            raise AdapterError(f"parent_run_id={parent_run_id!r} not found in store")
        if parent_run.adapter != self._adapter_name:
            raise AdapterError(
                f"parent_run adapter={parent_run.adapter!r} cannot be forked by "
                f"LinearRecorder (adapter_name={self._adapter_name!r})"
            )

        parent_node = self._store.get_node(at_node_id)
        if parent_node is None:
            raise AdapterError(f"at_node_id={at_node_id!r} not found in store")
        if parent_node.run_id != parent_run_id:
            raise AdapterError(
                f"at_node_id={at_node_id!r} does not belong to parent_run_id={parent_run_id!r}"
            )

        if child_thread_id == parent_run.adapter_thread_id:
            raise AdapterError(
                f"child_thread_id={child_thread_id!r} must differ from parent "
                f"thread_id={parent_run.adapter_thread_id!r}"
            )

        # Locate the forked node in the runtime so we know where to resume.
        fork_step_index = runtime.step_index_of(parent_node.node_name)

        # Seed state: parent node's state_after + overrides (mirrors LangGraph).
        seeded_state = dict(parent_node.state_after or {})
        seeded_state.update(overrides)

        ref = ForkRef(
            parent_run_id=parent_run_id,
            at_node_id=at_node_id,
            child_thread_id=child_thread_id,
        )
        try:
            yield ref
            # Execute tail: steps AFTER fork_step_index only.
            tail_runtime = LinearRuntime(
                steps=runtime.steps[fork_step_index + 1 :],
                kind_map=runtime.kind_map,
            )
            self._execute_and_persist(
                runtime=tail_runtime,
                ref=ref,
                start_state=seeded_state,
                status_on_success=RunStatus.COMPLETED,
                task_description=task_description,
                tags=tags or [],
                first_step_index=parent_node.step_index + 1,
                first_parent_node_id=parent_node.id,
                fork_context={
                    "parent_run_id": parent_run_id,
                    "parent_node_id": at_node_id,
                    "overrides": overrides,
                    "reason": reason,
                },
            )
        except AdapterError:
            raise
        except Exception as exc:
            self._persist_failed_shell(
                ref=ref,
                task_description=task_description,
                tags=tags or [],
                error=str(exc),
            )
            raise

    # ------------------------------------------------------------------
    # Execution + persistence core
    # ------------------------------------------------------------------

    def _execute_and_persist(
        self,
        *,
        runtime: LinearRuntime,
        ref: RunRef | ForkRef,
        start_state: dict[str, Any],
        status_on_success: RunStatus,
        task_description: str | None,
        tags: list[str],
        first_step_index: int,
        first_parent_node_id: str | None,
        fork_context: dict[str, Any] | None,
    ) -> None:
        """Core executor: iterate runtime, capture pre/post state per step."""
        run_id = str(uuid.uuid4())
        started_at = _utcnow()

        nodes: list[Node] = []
        prev_node_id: str | None = first_parent_node_id
        step_cursor = first_step_index
        current_state = dict(start_state)

        for name, step_fn in runtime.steps:
            pre_state = dict(current_state)
            node_started_at = _utcnow()
            post_state = step_fn(pre_state)
            node_ended_at = _utcnow()

            if not isinstance(post_state, dict):
                raise AdapterError(
                    f"step {name!r} returned {type(post_state).__name__} — expected dict"
                )

            # Extract optional usage hint (Layer-4-ish per-node coercion).
            # Accepts three shapes for parity with the LangGraph adapter's
            # ADR-015 UsageResult contract:
            #   - dict: unpacked into Usage(...) (only the 3 token fields are
            #     valid kwargs on core.models.Usage; extras like model_name /
            #     cost_usd_cents are lifted onto Node separately below)
            #   - Usage: used as-is (core model, already persisted shape)
            #   - UsageResult: adapter-layer dataclass (imported lazily to
            #     avoid a hard dependency on the langgraph usage module from
            #     this zero-dep adapter)
            usage_obj: Usage | None = None
            hint_model_name: str | None = None
            hint_cost_usd_cents: int | None = None
            post_copy = dict(post_state)
            usage_hint = post_copy.pop("__chronos_usage__", None)
            if usage_hint is not None:
                if isinstance(usage_hint, Usage):
                    usage_obj = usage_hint
                elif isinstance(usage_hint, dict):
                    # core.models.Usage only accepts the 3 token fields;
                    # lift model_name / cost_usd_cents onto the Node instead.
                    hint = dict(usage_hint)
                    hint_model_name = hint.pop("model_name", None)
                    hint_cost_usd_cents = hint.pop("cost_usd_cents", None)
                    try:
                        usage_obj = Usage(**hint)
                    except (TypeError, ValueError):
                        usage_obj = None
                else:
                    # Duck-typed: assume it has prompt_tokens / completion_tokens.
                    # Matches UsageResult without importing it.
                    try:
                        usage_obj = Usage(
                            prompt_tokens=int(getattr(usage_hint, "prompt_tokens", 0)),
                            completion_tokens=int(getattr(usage_hint, "completion_tokens", 0)),
                            reasoning_tokens=int(getattr(usage_hint, "reasoning_tokens", 0)),
                        )
                        hint_model_name = getattr(usage_hint, "model_name", None)
                        hint_cost_usd_cents = getattr(usage_hint, "cost_usd_cents", None)
                    except (TypeError, ValueError):
                        # Malformed hint — skip rather than crash the run.
                        usage_obj = None

            kind = runtime.kind_map.get(name, NodeKind.FN)

            node = Node(
                id=str(uuid.uuid4()),
                run_id=run_id,
                step_index=step_cursor,
                node_name=name,
                kind=kind,
                parent_node_id=prev_node_id,
                started_at=node_started_at,
                ended_at=node_ended_at,
                state_after=post_copy,
                model_name=hint_model_name,
                usage=usage_obj,
                cost_usd_cents=hint_cost_usd_cents,
                metadata={
                    "adapter": self._adapter_name,
                    "linear_step": step_cursor,
                    "agent_id": "main",
                },
            )
            nodes.append(node)
            prev_node_id = node.id
            step_cursor += 1
            current_state = post_copy

        ended_at = _utcnow()

        thread_id = ref.thread_id if isinstance(ref, RunRef) else ref.child_thread_id

        run = Run(
            id=run_id,
            adapter=self._adapter_name,
            adapter_thread_id=thread_id,
            status=status_on_success,
            started_at=started_at,
            ended_at=ended_at,
            task_description=task_description,
            initial_state=dict(start_state),
            final_state=dict(current_state),
            tags=list(tags),
            metadata={"num_steps": len(nodes)},
        )

        # Persist atomically: Run + Nodes (+ Fork for fork paths).
        with self._store.transaction():
            self._store.put_run(run)
            for node in nodes:
                self._store.put_node(node)
            if fork_context is not None:
                fork = Fork(
                    id=str(uuid.uuid4()),
                    parent_run_id=fork_context["parent_run_id"],
                    parent_node_id=fork_context["parent_node_id"],
                    child_run_id=run_id,
                    edited_fields=dict(fork_context["overrides"]),
                    reason=fork_context["reason"],
                )
                self._store.put_fork(fork)
                if isinstance(ref, ForkRef):
                    ref.fork_id = fork.id

        # Populate ref fields.
        if isinstance(ref, RunRef):
            ref.run_id = run_id
        else:
            ref.child_run_id = run_id
        ref.node_ids = [n.id for n in nodes]

    def _persist_failed_shell(
        self,
        *,
        ref: RunRef | ForkRef,
        task_description: str | None,
        tags: list[str],
        error: str,
    ) -> None:
        """Persist a zero-node failed Run so debugger can see what was attempted."""
        run_id = str(uuid.uuid4())
        now = _utcnow()
        thread_id = ref.thread_id if isinstance(ref, RunRef) else ref.child_thread_id
        run = Run(
            id=run_id,
            adapter=self._adapter_name,
            adapter_thread_id=thread_id,
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
        if isinstance(ref, RunRef):
            ref.run_id = run_id
        else:
            ref.child_run_id = run_id


def _utcnow() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "AdapterError",
    "ForkRef",
    "LinearRecorder",
    "LinearRuntime",
    "RunRef",
    "StepFn",
]
