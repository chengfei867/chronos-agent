"""CrewAI adapter (ADR-021, R52) — event-bus recorder, sync-first.

Compared to the LangGraph (state-dict) and AutoGen (message-list) adapters,
the CrewAI adapter sits on a third paradigm: a **scoped event bus**. The
recorder subscribes to ``crewai_event_bus`` inside ``record()``'s
``scoped_handlers()`` context manager, buffers ``Node``-shaped work in a
thread-safe list, and drains the buffer to the :class:`SqliteStore` on
CM exit after ``crewai_event_bus.flush(timeout=...)`` has guaranteed all
background ``ThreadPoolExecutor`` handlers have landed.

Usage pattern (ADR-021 §D5 — no ``asyncio.run`` wrapper; CrewAI is
sync-first and ``Crew.kickoff`` is called inline inside the CM):

.. code-block:: python

    from chronos.adapters.crewai import crewai_adapter

    with crewai_adapter.build_recorder(store).record(crew, thread_id="t1") as ref:
        result = crew.kickoff(inputs={"topic": "weather"})
        ref.submit_result(result)  # optional; records final Run.final_state

Why event-bus-based (vs. compile-hook / monkey-patch / listener-class):
see ADR-021 §Alternatives. The `scoped_handlers()` CM gives us a
per-run, per-recorder handler attach/detach guarantee that cleanly maps
to :class:`RecorderProtocol`'s CM lifecycle (ADR-016 §P1), eliminating
handler-leak risk entirely.

R52 scope: scaffold only (duck-typed unit tests, no real
``import crewai``). A real-LLM spike (``tests/spikes/spike13_*``) is
tracked as ADR-021 §Follow-ups and is the R53 candidate gate.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from chronos.adapters.protocols import AdapterError, RunRef

from .recorder import CrewAIRecorder

if TYPE_CHECKING:
    from chronos.adapters.langgraph_usage import UsageExtractor
    from chronos.core.models import NodeKind
    from chronos.store import SqliteStore


# ---------------------------------------------------------------------------
# Module-level AdapterProtocol instance (ADR-016 P2, R32-B convention)
# ---------------------------------------------------------------------------


class _CrewAIAdapter:
    """Module-level :class:`AdapterProtocol` implementation for CrewAI.

    Thin factory over :class:`CrewAIRecorder`. Version constraint targets
    ``crewai>=0.80,<2.0`` (ADR-021 §D8 original floor; ADR-022 R53 raised
    the ceiling from ``<1.0`` to ``<2.0`` after spike13a verified 1.14.3
    was a source-compatible superset of the 0.80+ event-bus API).

    Construction channels:

    - ``kind_map`` — if provided, maps CrewAI event class names (e.g.
      ``"ToolUsageStartedEvent"``, ``"LLMCallCompletedEvent"``) to
      :class:`NodeKind`. Missing entries fall back to
      :data:`chronos.adapters.crewai.recorder._DEFAULT_KIND_MAP`.
    - ``usage_extractor`` — **not used**. CrewAI exposes ``usage`` on
      ``LLMCallCompletedEvent`` directly as a dict. Passing a non-``None``
      value raises :class:`AdapterError` to make this loud (mirrors the
      AutoGen adapter; ADR-021 §D7).
    - ``**adapter_specific``: currently only ``adapter_name: str``
      (default ``"crewai"``) and ``flush_timeout_s: float`` (default
      ``5.0`` — the ``crewai_event_bus.flush`` barrier required by
      ADR-021 §D1) are supported.
    """

    name: str = "crewai"
    version_constraint: str = ">=0.80,<2.0"

    def build_recorder(
        self,
        store: SqliteStore,
        *,
        kind_map: dict[str, NodeKind] | None = None,
        usage_extractor: UsageExtractor | None = None,
        **adapter_specific: Any,
    ) -> CrewAIRecorder:
        """Construct a :class:`CrewAIRecorder` bound to ``store``.

        See class docstring for channel semantics.
        """
        if usage_extractor is not None:
            raise AdapterError(
                "crewai_adapter.build_recorder(): CrewAI reads usage "
                "directly from LLMCallCompletedEvent.usage — the ADR-015 "
                "usage_extractor callback is not wired in. Pass None."
            )
        allowed: set[str] = {"adapter_name", "flush_timeout_s"}
        extra = set(adapter_specific) - allowed
        if extra:
            raise AdapterError(
                "crewai_adapter.build_recorder() got unknown adapter-specific "
                f"kwargs: {sorted(extra)}; allowed: {sorted(allowed)}"
            )
        adapter_name = adapter_specific.get("adapter_name", "crewai")
        flush_timeout_s = adapter_specific.get("flush_timeout_s", 5.0)
        return CrewAIRecorder(
            store,
            adapter_name=adapter_name,
            kind_map=kind_map,
            flush_timeout_s=flush_timeout_s,
        )


crewai_adapter = _CrewAIAdapter()
"""Module-level :class:`AdapterProtocol` instance for the CrewAI adapter.

Satisfies :class:`~chronos.adapters.protocols.AdapterProtocol` structurally
(verified by ``isinstance()`` via ``@runtime_checkable``). Import from
either :mod:`chronos.adapters.crewai` or :mod:`chronos.adapters`.
"""


__all__ = [
    "AdapterError",
    "CrewAIRecorder",
    "RunRef",
    "crewai_adapter",
]
