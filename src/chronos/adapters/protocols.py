"""Adapter interface — framework-agnostic contract for Chronos recorders.

This module formalises ADR-016's three Protocols and the two shared
dataclass references that every adapter exposes. It is the single source
of truth for what any adapter — `LangGraphRecorder`, `LinearRecorder`,
and future AutoGen/CrewAI adapters — must look like from the outside.

Rollout step 2 of ADR-016 (R31-A): the `RunRef` / `ForkRef` / `AdapterError`
definitions used to live in `chronos.adapters.langgraph` and a duplicate
set lived in `chronos.adapters.linear.recorder`. They now live here and
are re-exported from both adapter modules for backward compatibility.
**Import from either location is stable** — the adapter modules keep
their historical import paths; new code and cross-adapter code should
prefer `from chronos.adapters.protocols import ...`.

Public surface
--------------

Dataclass references (returned from recorder context managers):

- :class:`RunRef`    — handle yielded by ``Recorder.record()``
- :class:`ForkRef`   — handle yielded by ``Recorder.fork()``

Exception:

- :class:`AdapterError` — the one legal framework-leak exception per the
  ADR-016 lifecycle contract. Any other exception escaping from an
  adapter is a bug.

Protocols (structural — `runtime_checkable` for instance checks):

- :class:`RecorderProtocol`       — core record/fork contract
- :class:`AdapterProtocol`        — plugin / constructor shape
- :class:`NodeIdentityResolver`   — pluggable framework → (name, kind) hook

Design notes
------------

- Every Protocol is `@runtime_checkable` so tests can `isinstance()` an
  adapter against the contract. This is test-only convenience; `Protocol`
  remains *structural* — conformance is verified by use, not by
  inheritance (see ADR-016 §Consequences).
- No implementation logic lives here. This file is intentionally thin;
  all behaviour is in adapter modules.
- `typing.Any` is used for ``runtime`` / ``event`` payloads deliberately
  (ADR-016 A5): forcing a ``Runtime`` Protocol would bake framework
  knowledge back into the interface.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from chronos.adapters.langgraph_usage import UsageExtractor
    from chronos.core.models import NodeKind
    from chronos.store import SqliteStore


# ---------------------------------------------------------------------------
# Exception (the one legal leak)
# ---------------------------------------------------------------------------


class AdapterError(RuntimeError):
    """Raised when adapter invariants or framework-shape expectations fail.

    Per ADR-016, this is the **only** framework-leak exception adapters are
    allowed to raise. Everything else (``KeyError`` from a missing snapshot
    field, ``AttributeError`` from an SDK drift, etc.) must be caught and
    re-wrapped. Nothing in the adapter layer should leak framework-specific
    exceptions to callers.

    Typical triggers:

    - Runtime / framework emitted an unexpected shape (SDK version drift)
    - ``thread_id`` / ``at_node_id`` / ``parent_run_id`` validation failures
    - Fork invariant violations (e.g. child ``thread_id`` equals parent's)
    """


# ---------------------------------------------------------------------------
# References — mutable handles yielded by record() / fork()
# ---------------------------------------------------------------------------


@dataclass
class RunRef:
    """Mutable handle yielded from a recorder's ``record()`` context manager.

    Inside the ``with`` block the handle is partially populated
    (``run_id`` is ``None`` until exit). On normal exit, the adapter
    populates ``run_id`` and appends the persisted ``Node`` ids to
    ``node_ids`` in step order, *before* returning control to the caller.
    On exception, the run is persisted with ``status=FAILED`` and the
    original exception is re-raised.

    Attributes:
        thread_id: The framework's thread/session identifier for this run.
        run_id: Populated on CM exit with the persisted ``Run.id`` (UUID).
        node_ids: Persisted ``Node.id`` values in step order (append-only).
    """

    thread_id: str
    run_id: str | None = None
    node_ids: list[str] = field(default_factory=list)


@dataclass
class ForkRef:
    """Mutable handle yielded from a recorder's ``fork()`` context manager.

    Populated on context-manager exit with the child ``Run``'s id, the
    ``Fork`` record id, and the persisted child-side ``Node`` ids.

    Attributes:
        parent_run_id: The ``Run.id`` being forked from.
        at_node_id: The ``Node.id`` within ``parent_run_id`` that anchors
            the fork (child state = parent ``state_after`` + overrides).
        child_thread_id: Framework thread id for the child run; must
            differ from the parent run's ``thread_id``.
        child_run_id: Populated on CM exit with the child ``Run.id``.
        fork_id: Populated on CM exit with the ``Fork.id`` row id.
        node_ids: Child-side persisted node ids in step order.
    """

    parent_run_id: str
    at_node_id: str
    child_thread_id: str
    child_run_id: str | None = None
    fork_id: str | None = None
    node_ids: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# P1. RecorderProtocol — the core record/fork contract
# ---------------------------------------------------------------------------


@runtime_checkable
class RecorderProtocol(Protocol):
    """Framework-agnostic recorder interface (ADR-016 P1).

    Every adapter's recorder class must expose ``record()`` and ``fork()``
    context managers with the signatures below. Semantics (ADR-016 §P1):

    1. **record() CM contract**:
       - Enter: yield a ``RunRef(thread_id=...)`` with ``run_id=None``,
         ``node_ids=[]``.
       - Normal exit: persist ``Run`` + ``Node``s with ``status=COMPLETED``;
         populate ``ref.run_id`` and ``ref.node_ids`` before returning.
       - Exception from the user block: persist with ``status=FAILED``,
         populate the ref, **re-raise**.
       - Empty runs (user never invoked ``runtime``) are a silent no-op.

    2. **fork() CM contract**:
       - Enter: validate ``parent_run_id`` / ``at_node_id`` exist in the
         store; ensure ``at_node_id.run_id == parent_run_id``; ensure
         ``child_thread_id`` differs from the parent's. Seed the child
         execution so the runtime resumes from the parent node's
         ``state_after`` merged with ``overrides``.
       - Normal exit: persist child ``Run`` + ``Node``s + ``Fork`` row;
         populate ``ref.child_run_id``, ``ref.fork_id``, ``ref.node_ids``.
       - Exception from the user block: persist with ``status=FAILED``
         (child run still committed for inspection), **re-raise**.

    3. **Atomicity**: persistence happens in a single ``store.transaction()``.
    4. **Idempotency**: re-entering ``record()`` with the same ``thread_id``
       is legal and creates a *new* ``Run``.
    5. **Errors**: structural drift raises :class:`AdapterError`; nothing
       else should leak.

    Note:
        ``runtime`` is :class:`typing.Any` by design (ADR-016 A5). Each
        adapter knows the concrete runtime type (LangGraph ``Graph``,
        AutoGen ``GroupChatManager``, etc.); cross-adapter code never
        inspects it.
    """

    def record(
        self,
        runtime: Any,
        *,
        thread_id: str,
        task_description: str | None = None,
        tags: list[str] | None = None,
    ) -> AbstractContextManager[RunRef]:
        """Open a recording context. See class docstring for lifecycle."""
        ...

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
    ) -> AbstractContextManager[ForkRef]:
        """Open a fork context. See class docstring for lifecycle."""
        ...


# ---------------------------------------------------------------------------
# P2. AdapterProtocol — module / plugin shape
# ---------------------------------------------------------------------------


@runtime_checkable
class AdapterProtocol(Protocol):
    """Module-level plugin shape (ADR-016 P2).

    What every adapter package exposes at import time: a way to construct
    a conformant recorder, the adapter's canonical name, and the runtime
    library version range it supports.

    This Protocol is intentionally minimal — it hands the caller a
    :class:`RecorderProtocol`. Everything else (callback bridges,
    framework-specific configuration) is an internal concern of the
    adapter, passed through ``**adapter_specific``.

    No adapter *instance* registrations ship in R31-A; this Protocol is
    the contract against which R31+ work (AutoGen adapter module exposing
    ``autogen_adapter: AdapterProtocol``) will be written.

    Attributes:
        name: Canonical adapter name (``"langgraph"``, ``"autogen"``,
            ``"crewai"``, ``"linear"``).
        version_constraint: PEP 440 / PEP 508 style range for the runtime
            library (e.g. ``">=0.4,<0.6"``). Empty string for
            dependency-free adapters such as ``linear``.
    """

    name: str
    version_constraint: str

    def build_recorder(
        self,
        store: SqliteStore,
        *,
        kind_map: dict[str, NodeKind] | None = None,
        usage_extractor: UsageExtractor | None = None,
        **adapter_specific: Any,
    ) -> RecorderProtocol:
        """Construct a conformant recorder bound to ``store``.

        ``**adapter_specific`` is the pressure-release valve (ADR-016 §P2):
        LangGraph has zero extra kwargs today; AutoGen is expected to
        accept ``group_chat_filter=`` or similar. Keyword-only,
        adapter-owned; cross-adapter code never passes these.
        """
        ...


# ---------------------------------------------------------------------------
# P3. NodeIdentityResolver — pluggable (event) → (name, kind) mapping
# ---------------------------------------------------------------------------


@runtime_checkable
class NodeIdentityResolver(Protocol):
    """Maps a framework-native execution event to ``(node_name, NodeKind)``.

    LangGraph derives ``node_name`` from ``source='loop' + writes``;
    other frameworks extract it differently (AutoGen: speaker name from
    message; CrewAI: agent role + task). This Protocol is the single
    framework-specific piece of state-machine semantics we expose as a
    hook, so adapter authors don't have to invent their own event taxonomy.

    Returning ``None`` signals "this event is not a node boundary" and
    the recorder should skip it (useful for intermediate streaming
    deltas, heartbeats, etc.).

    Phase 1 default resolver for LangGraph is trivial and lives inside
    :class:`~chronos.adapters.langgraph.LangGraphRecorder` — no user
    exposure yet. The Protocol is documented now so Phase 2 adapter
    authors have a named hook.
    """

    def resolve(self, event: Any) -> tuple[str, NodeKind] | None:
        """Return ``(node_name, node_kind)`` for ``event``, or ``None``."""
        ...


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------

__all__ = [
    "AdapterError",
    "AdapterProtocol",
    "ForkRef",
    "NodeIdentityResolver",
    "RecorderProtocol",
    "RunRef",
]
