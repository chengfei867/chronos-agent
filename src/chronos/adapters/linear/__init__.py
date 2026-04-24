"""Linear-pipeline reference adapter (ADR-014 R1 impl, R28).

A minimal, zero-dependency recorder implementation that conforms to
`RecorderProtocol` (ADR-016). Exists to prove the Protocol can be filled
by a non-LangGraph runtime. Event model is intentionally similar to
LangGraph (discrete step → state snapshot); the R27 risks doc R-1
documents this limitation — real event-model divergence testing
requires AutoGen and is deferred to Phase 2 proper.

A `LinearRuntime` is a sequence of ``(node_name, step_fn)`` pairs where
each ``step_fn: dict -> dict`` takes the current state and returns the
next state. `LinearRecorder` wraps execution to capture each step as a
Chronos `Node`.

R32-B adds :data:`linear_adapter`, a module-level
:class:`~chronos.adapters.protocols.AdapterProtocol` instance.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from chronos.adapters.protocols import AdapterError

from .recorder import (
    ForkRef,
    LinearRecorder,
    LinearRuntime,
    RunRef,
    StepFn,
)

if TYPE_CHECKING:
    from chronos.adapters.langgraph_usage import UsageExtractor
    from chronos.core.models import NodeKind
    from chronos.store import SqliteStore


# ---------------------------------------------------------------------------
# Module-level AdapterProtocol instance (ADR-016 P2, R32-B)
# ---------------------------------------------------------------------------


class _LinearAdapter:
    """Module-level :class:`AdapterProtocol` implementation for the Linear adapter.

    Thin factory over :class:`LinearRecorder`. No runtime library means
    :attr:`version_constraint` is the empty string (ADR-016 P2 allows
    this for dependency-free adapters like this reference implementation).

    Construction channels:

    - ``kind_map`` and ``usage_extractor`` are **not** accepted by
      :class:`LinearRecorder`; the Linear adapter carries ``kind_map``
      on :class:`LinearRuntime` instead (per-runtime, not per-recorder)
      and handles usage via the ``__chronos_usage__`` state-key hint
      rather than an extractor callback. For signature parity with
      :class:`AdapterProtocol`, :meth:`build_recorder` accepts both kwargs
      but raises :class:`AdapterError` if either is non-``None`` — the
      caller is otherwise silently misled into thinking these channels
      are active.
    - ``**adapter_specific`` supports ``adapter_name: str`` (forwarded
      to :class:`LinearRecorder`'s ``adapter_name`` kwarg — useful for
      tests that want to distinguish two Linear instances). Unknown
      keys raise :class:`AdapterError`.
    """

    name: str = "linear"
    version_constraint: str = ""

    def build_recorder(
        self,
        store: SqliteStore,
        *,
        kind_map: dict[str, NodeKind] | None = None,
        usage_extractor: UsageExtractor | None = None,
        **adapter_specific: Any,
    ) -> LinearRecorder:
        """Construct a :class:`LinearRecorder` bound to ``store``.

        Matches :class:`AdapterProtocol.build_recorder`. See class docstring
        for Linear-specific channel routing.
        """
        if kind_map is not None:
            raise AdapterError(
                "linear_adapter.build_recorder(): kind_map is carried on "
                "LinearRuntime, not the recorder; pass it when constructing "
                "LinearRuntime(steps=..., kind_map=...)"
            )
        if usage_extractor is not None:
            raise AdapterError(
                "linear_adapter.build_recorder(): Linear adapter uses the "
                "'__chronos_usage__' state-dict key for per-step usage "
                "metering, not a usage_extractor callback. See "
                "LinearRecorder docstring."
            )
        # Only 'adapter_name' is an allowed adapter-specific kwarg.
        allowed: set[str] = {"adapter_name"}
        extra = set(adapter_specific) - allowed
        if extra:
            raise AdapterError(
                "linear_adapter.build_recorder() got unknown adapter-specific "
                f"kwargs: {sorted(extra)}; allowed: {sorted(allowed)}"
            )
        adapter_name = adapter_specific.get("adapter_name", "linear")
        return LinearRecorder(store, adapter_name=adapter_name)


linear_adapter = _LinearAdapter()
"""Module-level :class:`AdapterProtocol` instance for the Linear adapter.

Satisfies :class:`~chronos.adapters.protocols.AdapterProtocol` structurally
(verified by ``isinstance()`` via ``@runtime_checkable``). Import from
either :mod:`chronos.adapters.linear` or :mod:`chronos.adapters`.
"""


__all__ = [
    "AdapterError",
    "ForkRef",
    "LinearRecorder",
    "LinearRuntime",
    "RunRef",
    "StepFn",
    "linear_adapter",
]
